#!/usr/bin/env python3
"""Validation suite for scripts/release_manifest.py (hardened, Codex -016/-017/-018).

Two layers:
  - TestBuildManifest: fixture/negative tests with injected git + west callables
    (clean -> provenance_ready true / release_ready false; dirty/+/-/U/missing-
    lock/missing-direct-req/git-failure/west-failure refused; manifest repo
    commit == root_commit).
  - TestWestProjects: `west manifest --freeze --active-only` parsing + per-project
    consistency, with an injected west runner (frozen YAML) + per-project git
    runner over a fixtured workspace (valid; unresolvable revision; wrong
    checkout; dirty; missing/uncloned project; failed west command).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_manifest as rm  # noqa: E402


def _proc(returncode=0, stdout="", stderr=""):
    class R:
        pass
    R.returncode = returncode
    R.stdout = stdout
    R.stderr = stderr
    return R


class TestBuildManifest(unittest.TestCase):
    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tools").mkdir()
        (root / "tools" / "TOOLCHAIN.lock").write_text(
            "lock\n", encoding="utf-8")
        (root / rm.DIRECT_REQUIREMENTS).write_text(
            "pyserial==3.5\n", encoding="utf-8")
        wz = root / "zephyr" / "benchmark_zephyr"
        wz.mkdir(parents=True)
        (wz / "west.yml").write_text(
            "manifest:\n  projects:\n    - name: zephyr\n"
            "      revision: v4.4.0\n", encoding="utf-8")
        return root

    def _git(self, *, dirty=False, head="a" * 40, submodules=None, fail=()):
        sub = submodules if submodules is not None else (
            f" {'b' * 40} chibios/ChibiOS (ver21.11.5)\n"
            f" {'c' * 40} freertos/FreeRTOS-Kernel (V11.3.0)\n"
            f" {'d' * 40} freertos/stm32_hal (v1.12.1)\n")

        def git(root, *args, runner=None):
            if fail and args[:len(fail)] == fail:
                raise rm.ManifestError("simulated git failure")
            if args[0] == "status":
                return "M x\n" if dirty else ""
            if args[:2] == ("rev-parse", "HEAD"):
                return head + "\n"
            if args[:2] == ("submodule", "status"):
                return sub
            raise rm.ManifestError(f"unexpected git args {args}")
        return git

    def _west_ok(self):
        def west(root):
            return {
                "projects": {"zephyr": {"commit": "e" * 40},
                             "hal_stm32": {"commit": "f" * 40}},
                "manifest_repo": {"path": "benchmark_zephyr", "commit": None,
                                  "commit_source": "root_commit"},
            }
        return west

    def _west_fail(self):
        def west(root):
            raise rm.ManifestError("west boom")
        return west

    def test_clean_provenance_ready(self):
        m = rm.build_manifest(self._root(), git=self._git(head="a" * 40),
                              west=self._west_ok())
        self.assertEqual(len(m["root_commit"]), 40)
        self.assertIn("chibios/ChibiOS", m["submodules"])
        self.assertIn("zephyr", m["zephyr_west_projects"])
        self.assertEqual(len(m["toolchain_lock_sha256"]), 64)
        self.assertEqual(
            len(m["publication_direct_requirements_sha256"]), 64)
        self.assertIs(m["provenance_ready"], True)
        self.assertIs(m["release_ready"], False)
        self.assertTrue(m["remaining_gates"])
        # manifest repo commit is the root commit, not null.
        self.assertEqual(m["zephyr_west_manifest_repo"]["commit"], "a" * 40)
        self.assertEqual(
            m["zephyr_west_manifest_repo"]["commit_source"], "root_commit")

    def test_dirty_tree_refused(self):
        with self.assertRaises(rm.ManifestError):
            rm.build_manifest(self._root(), git=self._git(dirty=True),
                              west=self._west_ok())

    def test_west_failure_refused(self):
        with self.assertRaises(rm.ManifestError):
            rm.build_manifest(self._root(), git=self._git(),
                              west=self._west_fail())

    def test_submodule_plus_marker_refused(self):
        sub = f"+{'b' * 40} chibios/ChibiOS (heads/x)\n"
        with self.assertRaises(rm.ManifestError):
            rm.build_manifest(self._root(), git=self._git(submodules=sub),
                              west=self._west_ok())

    def test_submodule_u_marker_refused(self):
        sub = f"U{'b' * 40} chibios/ChibiOS (merge)\n"
        with self.assertRaises(rm.ManifestError):
            rm.build_manifest(self._root(), git=self._git(submodules=sub),
                              west=self._west_ok())

    def test_uninitialized_submodule_refused(self):
        sub = f"-{'b' * 40} chibios/ChibiOS\n"
        with self.assertRaises(rm.ManifestError):
            rm.build_manifest(self._root(), git=self._git(submodules=sub),
                              west=self._west_ok())

    def test_missing_lock_refused(self):
        root = self._root()
        (root / "tools" / "TOOLCHAIN.lock").unlink()
        with self.assertRaises(rm.ManifestError):
            rm.build_manifest(root, git=self._git(), west=self._west_ok())

    def test_missing_direct_requirements_refused(self):
        root = self._root()
        (root / rm.DIRECT_REQUIREMENTS).unlink()
        with self.assertRaises(rm.ManifestError):
            rm.build_manifest(root, git=self._git(), west=self._west_ok())

    def test_git_failure_refused(self):
        with self.assertRaises(rm.ManifestError):
            rm.build_manifest(self._root(),
                              git=self._git(fail=("rev-parse",)),
                              west=self._west_ok())


class TestWestProjects(unittest.TestCase):
    def _ws(self, git_paths) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ws = root / "zephyr"
        (ws / ".west").mkdir(parents=True)
        for p in git_paths:
            (ws / p / ".git").mkdir(parents=True)
        return root

    def _freeze(self, projects):
        """projects: list of (name, revision, path|None) -> frozen YAML text."""
        lines = ["manifest:", "  projects:"]
        for name, rev, path in projects:
            lines.append(f"  - name: {name}")
            lines.append(f"    revision: {rev}")
            if path:
                lines.append(f"    path: {path}")
        lines += ["  self:", "    path: benchmark_zephyr"]
        return "\n".join(lines) + "\n"

    def _west(self, freeze_text, *, cwd_box=None):
        def west(cmd, cwd):
            if cwd_box is not None:
                cwd_box.append(Path(cwd))
            return _proc(stdout=freeze_text)
        return west

    def _git(self, *, head="e" * 40, dirty=False):
        def git(cmd, cwd):
            sub = cmd[3:]  # drop ["git", "-C", <path>]
            if sub[0] == "rev-parse":
                return _proc(stdout=head + "\n")
            if sub[0] == "status":
                return _proc(stdout="M x\n" if dirty else "")
            return _proc(returncode=1, stderr="unexpected")
        return git

    def test_valid_workspace(self):
        box = []
        root = self._ws(["zephyr", "modules/lib/acpica"])
        ft = self._freeze([("zephyr", "e" * 40, None),
                           ("acpica", "e" * 40, "modules/lib/acpica")])
        info = rm._west_projects(root, west_runner=self._west(ft, cwd_box=box),
                                 git_runner=self._git(head="e" * 40))
        self.assertEqual(box[0], root / "zephyr")  # west ran in the workspace
        self.assertEqual(info["projects"]["zephyr"]["commit"], "e" * 40)
        self.assertIn("acpica", info["projects"])
        self.assertEqual(
            info["manifest_repo"]["commit_source"], "root_commit")

    def test_unresolvable_revision_fails(self):
        root = self._ws(["zephyr"])
        ft = self._freeze([("zephyr", "nonexistent-revision", None)])
        with self.assertRaises(rm.ManifestError):
            rm._west_projects(root, west_runner=self._west(ft),
                              git_runner=self._git())

    def test_wrong_checkout_fails(self):
        root = self._ws(["zephyr"])
        ft = self._freeze([("zephyr", "e" * 40, None)])  # resolved e*40
        with self.assertRaises(rm.ManifestError):
            rm._west_projects(root, west_runner=self._west(ft),
                              git_runner=self._git(head="9" * 40))  # != resolved

    def test_dirty_project_fails(self):
        root = self._ws(["zephyr"])
        ft = self._freeze([("zephyr", "e" * 40, None)])
        with self.assertRaises(rm.ManifestError):
            rm._west_projects(root, west_runner=self._west(ft),
                              git_runner=self._git(head="e" * 40, dirty=True))

    def test_missing_project_fails(self):
        root = self._ws([])  # no project .git dirs
        ft = self._freeze([("zephyr", "e" * 40, None)])
        with self.assertRaises(rm.ManifestError):
            rm._west_projects(root, west_runner=self._west(ft),
                              git_runner=self._git())

    def test_west_command_failed(self):
        root = self._ws(["zephyr"])

        def bad_west(cmd, cwd):
            return _proc(returncode=1, stderr="boom")
        with self.assertRaises(rm.ManifestError):
            rm._west_projects(root, west_runner=bad_west,
                              git_runner=self._git())


if __name__ == "__main__":
    unittest.main()
