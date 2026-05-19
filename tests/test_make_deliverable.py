#!/usr/bin/env python3
"""Validation suite for scripts/make_deliverable.py (E1a).

Builds a throwaway git fixture with a REAL nested git repo for
the submodule gitlink (so the parent tree stays clean) and
checks the deliverable contract: denylist (incl. nested tracked
paths), HEAD source, dirty hard-fail, external-source manifest,
and deterministic archives. Stdlib only; no network.

Run: python -m unittest tests.test_make_deliverable -v
"""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "make_deliverable.py"

INCLUDE = ["README.md", "common/c.c", "scripts/a.py", "env.bat",
           "scripts/build_report.py",
           "docs/METHODOLOGY.md", "docs/SETUP.md",
           "tools/TOOLCHAIN.lock"]
DENY = ["docs/Phase1_Benchmark_Report.pdf", "notes/x.md",
        "reference/y.txt", "tools/gcc/bin/foo", "AGENTS.md",
        "CLAUDE.local.md", ".claude/cfg",
        "scripts/__pycache__/x.pyc",
        "chibios/benchmark_chibios/build/x.o"]


def _git(repo: Path, *args):
    r = subprocess.run(["git", "-C", str(repo)] + list(args),
                        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr}")
    return r.stdout


class MakeDeliverableTest(unittest.TestCase):

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.repo = Path(self._t.name) / "repo"
        self.repo.mkdir(parents=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        _git(self.repo, "config", "commit.gpgsign", "false")
        for rel in INCLUDE + DENY:
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"content {rel}\n", encoding="utf-8")
        (self.repo / ".gitmodules").write_text(
            '[submodule "sub/mod"]\n\tpath = sub/mod\n'
            '\turl = https://example/sub.git\n', encoding="utf-8")
        # Real nested repo so the gitlink is consistent and the
        # parent tree stays clean (Codex e1a review).
        sub = self.repo / "sub" / "mod"
        sub.mkdir(parents=True)
        _git(sub, "init", "-q")
        _git(sub, "config", "user.email", "s@s")
        _git(sub, "config", "user.name", "s")
        _git(sub, "config", "commit.gpgsign", "false")
        (sub / "f.txt").write_text("nested\n", encoding="utf-8")
        _git(sub, "add", "-A")
        _git(sub, "commit", "-q", "-m", "sub")
        self.sub_sha = _git(sub, "rev-parse", "HEAD").strip()
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "fixture")

    def tearDown(self):
        self._t.cleanup()

    def _run(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo-root",
             str(self.repo)] + list(extra),
            capture_output=True, text=True, encoding="utf-8")

    def test_01_dry_run_writes_nothing(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dry-run", r.stdout)
        self.assertIn("common/c.c", r.stdout)
        self.assertNotIn("Phase1_Benchmark_Report.pdf", r.stdout)
        self.assertFalse((self.repo / "dist").exists())

    def test_02_write_clean_builds_archive(self):
        r = self._run("--write")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        dist = self.repo / "dist"
        tgz = list(dist.glob("rtos-benchmark-*.tar.gz"))
        self.assertEqual(len(tgz), 1)
        self.assertTrue(list(dist.glob("rtos-benchmark-*.zip")))
        self.assertTrue((dist / "SHA256SUMS").is_file())
        with tarfile.open(tgz[0]) as tf:
            names = tf.getnames()
        rel = sorted(n.split("/", 1)[1] for n in names)
        for inc in INCLUDE:
            self.assertIn(inc, rel)
        for bad in DENY:
            self.assertNotIn(bad, rel)
        self.assertNotIn("sub/mod", rel)
        for gen in ("EXTERNAL_SOURCES.lock",
                    "DELIVERABLE_NOTICE.txt", "MANIFEST.sha256"):
            self.assertIn(gen, rel)
        self.assertEqual(rel, sorted(rel))
        self.assertTrue(all("\\" not in n for n in names))

    def test_03_external_sources_records_gitlink(self):
        self._run("--write")
        tgz = list((self.repo / "dist")
                   .glob("rtos-benchmark-*.tar.gz"))[0]
        with tarfile.open(tgz) as tf:
            m = [n for n in tf.getnames()
                 if n.endswith("EXTERNAL_SOURCES.lock")][0]
            data = json.loads(tf.extractfile(m).read())
        sub = data["submodules"][0]
        self.assertEqual(sub["path"], "sub/mod")
        self.assertEqual(sub["commit"], self.sub_sha)
        self.assertEqual(sub["url"], "https://example/sub.git")

    def test_04_dirty_tree_blocks_write(self):
        (self.repo / "untracked.txt").write_text("x")
        r = self._run("--write")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dirty", r.stdout + r.stderr)
        self.assertFalse((self.repo / "dist").exists())

    def test_05_dirty_tree_dryrun_warns(self):
        (self.repo / "untracked.txt").write_text("x")
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WARNING", r.stdout)
        self.assertIn("would not be releasable", r.stdout.lower())

    def test_06_missing_gitmodules_url_blocks_write(self):
        (self.repo / ".gitmodules").write_text(
            '[submodule "sub/mod"]\n\tpath = sub/mod\n',
            encoding="utf-8")
        _git(self.repo, "add", ".gitmodules")
        _git(self.repo, "commit", "-q", "-m", "drop url")
        r = self._run("--write")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no .gitmodules URL", r.stdout + r.stderr)

    def test_07_deterministic_archives(self):
        o1 = Path(self._t.name) / "o1"
        o2 = Path(self._t.name) / "o2"
        self.assertEqual(self._run("--write", "--out",
                                   str(o1)).returncode, 0)
        self.assertEqual(self._run("--write", "--out",
                                   str(o2)).returncode, 0)
        for pat in ("rtos-benchmark-*.tar.gz",
                    "rtos-benchmark-*.zip"):
            a = list(o1.glob(pat))[0].read_bytes()
            b = list(o2.glob(pat))[0].read_bytes()
            self.assertEqual(hashlib.sha256(a).hexdigest(),
                             hashlib.sha256(b).hexdigest(),
                             f"non-deterministic: {pat}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
