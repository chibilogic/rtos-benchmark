#!/usr/bin/env python3
"""Validation suite for scripts/setup.py (ADR-021 follow-up;
Codex 2026-05-21-setup-orchestrator-plan-review-001 REQ 3).

Fully offline: no real subprocess, no real network, no real
filesystem changes outside a temp dir. All side effects are
mocked.

Run: python -m unittest tests.test_setup -v
"""
from __future__ import annotations
import os
import subprocess
import sys
import unittest
from argparse import Namespace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "setup.py"

sys.path.insert(0, str(SCRIPT.parent))
import setup as su  # type: ignore  # noqa: E402


def _args(**over) -> Namespace:
    """Default argparse Namespace for build_plan()."""
    base = dict(skip_tests=False, skip_zephyr=False,
                check_only=False, use_current_python=False)
    base.update(over)
    return Namespace(**base)


class EnvIsolationMixin:
    """Clears SSL_CERT_FILE / SSL_CERT_DIR / VIRTUAL_ENV in setUp,
    restores in tearDown."""

    def setUp(self):
        super().setUp()
        self._env_keys = ("SSL_CERT_FILE", "SSL_CERT_DIR",
                          "VIRTUAL_ENV")
        self._saved = {k: os.environ.get(k) for k in self._env_keys}
        for k in self._env_keys:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()


# ---------------------------------------------------------------
# build_plan() - pure function; mock filesystem + env.
# ---------------------------------------------------------------

class BuildPlanTest(EnvIsolationMixin, unittest.TestCase):

    def _plan(self, args, *,
              truststore_importable=True,
              zephyr_venv_exists=True,
              west_installed=True,
              west_init=True):
        with patch.object(su, '_truststore_importable',
                          return_value=truststore_importable), \
             patch.object(su, 'needs_zephyr_venv',
                          return_value=not zephyr_venv_exists), \
             patch.object(su, 'needs_west_install',
                          return_value=not west_installed), \
             patch.object(su, 'needs_west_init',
                          return_value=not west_init):
            return su.build_plan(args, Path("/fake/python"))

    def test_01_full_plan_when_nothing_present(self):
        plan = self._plan(_args(),
                          truststore_importable=False,
                          zephyr_venv_exists=False,
                          west_installed=False,
                          west_init=False)
        names = [s.name for s in plan]
        self.assertEqual(names, [
            "submodules", "ssl-truststore", "bootstrap-toolchain",
            "host-deps", "tests", "zephyr-venv",
            "zephyr-west-install", "zephyr-west-init",
            "zephyr-west-update",
        ])

    def test_02_skip_tests_replaces_tests_step(self):
        plan = self._plan(_args(skip_tests=True))
        names = [s.name for s in plan]
        self.assertIn("tests-skip", names)
        self.assertNotIn("tests", names)

    def test_03_skip_zephyr_terminates_after_zephyr_skip(self):
        plan = self._plan(_args(skip_zephyr=True))
        names = [s.name for s in plan]
        self.assertEqual(names[-1], "zephyr-skip")
        for n in ("zephyr-venv", "zephyr-venv-skip",
                  "zephyr-west-install", "zephyr-west-skip",
                  "zephyr-west-init", "zephyr-west-init-skip",
                  "zephyr-west-update"):
            self.assertNotIn(n, names)

    def test_04_ssl_cert_file_env_skips_truststore_install(self):
        os.environ["SSL_CERT_FILE"] = "/tmp/fake.pem"
        plan = self._plan(_args(), truststore_importable=False)
        names = [s.name for s in plan]
        self.assertIn("ssl-truststore-skip", names)
        self.assertNotIn("ssl-truststore", names)

    def test_05_ssl_cert_dir_env_skips_truststore_install(self):
        os.environ["SSL_CERT_DIR"] = "/tmp/fake-dir"
        plan = self._plan(_args(), truststore_importable=False)
        names = [s.name for s in plan]
        self.assertIn("ssl-truststore-skip", names)
        self.assertNotIn("ssl-truststore", names)

    def test_06_truststore_install_ordered_before_bootstrap(self):
        plan = self._plan(_args(), truststore_importable=False)
        names = [s.name for s in plan]
        ix_ts = names.index("ssl-truststore")
        ix_bs = names.index("bootstrap-toolchain")
        self.assertLess(ix_ts, ix_bs,
                        f"ssl-truststore at {ix_ts} must come "
                        f"before bootstrap-toolchain at {ix_bs}")

    def test_07_truststore_already_importable_skips_install(self):
        plan = self._plan(_args(), truststore_importable=True)
        names = [s.name for s in plan]
        self.assertIn("ssl-truststore-skip", names)
        self.assertNotIn("ssl-truststore", names)

    def test_08_zephyr_venv_exists_emits_reuse(self):
        plan = self._plan(_args(), zephyr_venv_exists=True)
        names = [s.name for s in plan]
        self.assertIn("zephyr-venv-skip", names)
        self.assertNotIn("zephyr-venv", names)

    def test_09_zephyr_west_init_exists_emits_reuse(self):
        plan = self._plan(_args(), west_init=True)
        names = [s.name for s in plan]
        self.assertIn("zephyr-west-init-skip", names)
        self.assertNotIn("zephyr-west-init", names)

    def test_10_west_update_always_present_when_zephyr_not_skipped(self):
        for w_init in (True, False):
            for w_install in (True, False):
                for v_exists in (True, False):
                    plan = self._plan(
                        _args(),
                        zephyr_venv_exists=v_exists,
                        west_installed=w_install,
                        west_init=w_init)
                    names = [s.name for s in plan]
                    self.assertIn("zephyr-west-update", names,
                                  f"missing for v={v_exists} "
                                  f"i={w_install} init={w_init}")


# ---------------------------------------------------------------
# preflight().
# ---------------------------------------------------------------

class PreflightTest(unittest.TestCase):

    def test_11_missing_git_fails_with_clear_message(self):
        def fake_which(name):
            return None if name == "git" else "/usr/bin/" + name
        with patch.object(su.shutil, "which",
                          side_effect=fake_which):
            with self.assertRaises(SystemExit) as cm:
                su.preflight()
        self.assertIn("git", str(cm.exception))
        self.assertIn("PATH", str(cm.exception))

    def test_12_missing_make_fails_with_educational_message(self):
        def fake_which(name):
            return None if name == "make" else "/usr/bin/" + name
        with patch.object(su.shutil, "which",
                          side_effect=fake_which):
            with self.assertRaises(SystemExit) as cm:
                su.preflight()
        msg = str(cm.exception)
        self.assertIn("make", msg)
        self.assertIn("MSYS2", msg)
        self.assertIn("apt install make", msg)
        self.assertIn("docs/SETUP.md", msg)

    def test_13_python_too_old_fails(self):
        import collections
        Fake = collections.namedtuple(
            "FakeVer", ["major", "minor", "micro",
                        "releaselevel", "serial"])
        fake = Fake(3, 9, 0, "final", 0)
        with patch.object(su.sys, "version_info", fake):
            with self.assertRaises(SystemExit) as cm:
                su.preflight()
        self.assertIn("Python 3.10", str(cm.exception))

    def test_14_all_prereqs_present_passes(self):
        with patch.object(su.shutil, "which",
                          side_effect=lambda n: "/usr/bin/" + n):
            su.preflight()  # must not raise


# ---------------------------------------------------------------
# _in_venv() and resolve_host_python().
# ---------------------------------------------------------------

class VenvResolutionTest(EnvIsolationMixin, unittest.TestCase):

    def test_15_in_venv_true_when_virtual_env_set(self):
        os.environ["VIRTUAL_ENV"] = "/tmp/fake-venv"
        self.assertTrue(su._in_venv())

    def test_16_use_current_python_returns_sys_executable(self):
        with patch.object(su, "_in_venv", return_value=False):
            py = su.resolve_host_python(use_current=True)
        self.assertEqual(py, Path(sys.executable).resolve())

    def test_17_in_venv_returns_sys_executable_no_venv_creation(self):
        with patch.object(su, "_in_venv", return_value=True), \
             patch.object(su.venv, "EnvBuilder") as mock_eb:
            py = su.resolve_host_python(use_current=False)
            mock_eb.assert_not_called()
        self.assertEqual(py, Path(sys.executable).resolve())


# ---------------------------------------------------------------
# needs_truststore_install().
# ---------------------------------------------------------------

class TrustStoreNeedsInstallTest(EnvIsolationMixin,
                                  unittest.TestCase):

    def test_18_ssl_cert_file_set_returns_false(self):
        os.environ["SSL_CERT_FILE"] = "/tmp/fake.pem"
        with patch.object(su, "_truststore_importable",
                          return_value=False):
            self.assertFalse(
                su.needs_truststore_install(Path("/fake/py")))

    def test_19_ssl_cert_dir_set_returns_false(self):
        os.environ["SSL_CERT_DIR"] = "/tmp/fake-dir"
        with patch.object(su, "_truststore_importable",
                          return_value=False):
            self.assertFalse(
                su.needs_truststore_install(Path("/fake/py")))

    def test_20_no_env_and_importable_returns_false(self):
        with patch.object(su, "_truststore_importable",
                          return_value=True):
            self.assertFalse(
                su.needs_truststore_install(Path("/fake/py")))

    def test_21_no_env_and_not_importable_returns_true(self):
        with patch.object(su, "_truststore_importable",
                          return_value=False):
            self.assertTrue(
                su.needs_truststore_install(Path("/fake/py")))


# ---------------------------------------------------------------
# execute_plan() - fail-fast and zephyr-venv inline action.
# ---------------------------------------------------------------

class ExecutePlanTest(unittest.TestCase):

    def test_22_nonzero_exit_propagates_and_stops_remaining(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append(cmd)
            if len(calls) == 1:
                return subprocess.CompletedProcess(cmd, 0)
            return subprocess.CompletedProcess(cmd, 7)

        steps = [
            su.Step(name="ok", description="ok", cmd=["true"]),
            su.Step(name="fail", description="fail",
                    cmd=["false"]),
            su.Step(name="never", description="never",
                    cmd=["never"]),
        ]
        with patch.object(su.subprocess, "run",
                          side_effect=fake_run):
            rc = su.execute_plan(Path("/fake/py"), steps)
        self.assertEqual(rc, 7)
        self.assertEqual(len(calls), 2,
                         f"third step ran; calls={calls}")

    def test_23_all_zero_returns_zero(self):
        steps = [su.Step(name="a", description="a", cmd=["x"]),
                 su.Step(name="b", description="b", cmd=["y"])]
        with patch.object(
                su.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0)):
            rc = su.execute_plan(Path("/fake/py"), steps)
        self.assertEqual(rc, 0)

    def test_24_cmd_none_step_is_skipped_no_subprocess(self):
        steps = [
            su.Step(name="info", description="just info"),
            su.Step(name="run", description="r", cmd=["true"]),
        ]
        with patch.object(
                su.subprocess, "run",
                return_value=subprocess.CompletedProcess(
                    [], 0)) as m:
            rc = su.execute_plan(Path("/fake/py"), steps)
        self.assertEqual(rc, 0)
        self.assertEqual(m.call_count, 1)

    def test_25_zephyr_venv_step_calls_ensure_zephyr_venv(self):
        steps = [su.Step(name="zephyr-venv",
                         description="create zephyr/.venv")]
        with patch.object(su, "ensure_zephyr_venv") as mock_ez:
            rc = su.execute_plan(Path("/fake/py"), steps)
        self.assertEqual(rc, 0)
        mock_ez.assert_called_once()


# ---------------------------------------------------------------
# Repo root resolution from __file__.
# ---------------------------------------------------------------

class RepoRootResolutionTest(unittest.TestCase):

    def test_26_repo_root_resolves_from_setup_script_location(self):
        self.assertEqual(
            su.REPO_ROOT,
            Path(__file__).resolve().parents[1])

    def test_27_host_venv_is_under_repo_root(self):
        self.assertEqual(su.HOST_VENV,
                         su.REPO_ROOT / ".venv-host")

    def test_28_zephyr_venv_is_under_zephyr_subdir(self):
        self.assertEqual(su.ZEPHYR_VENV,
                         su.REPO_ROOT / "zephyr" / ".venv")


# ---------------------------------------------------------------
# print_plan() dry-run output format.
# ---------------------------------------------------------------

class PrintPlanTest(unittest.TestCase):

    def test_29_print_plan_includes_names_descriptions_commands(self):
        steps = [
            su.Step(name="a", description="alpha desc",
                    cmd=["cmd-a", "x"]),
            su.Step(name="b", description="beta info"),
        ]
        with patch("sys.stdout", new_callable=StringIO) as buf:
            su.print_plan(Path("/fake/py"), steps)
        out = buf.getvalue()
        for needle in ("a", "alpha desc", "cmd-a", "b",
                       "beta info", "dry-run", "no side-effects"):
            self.assertIn(needle, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
