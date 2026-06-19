#!/usr/bin/env python3
"""Validation suite for scripts/release_gate.py (review P2.2; hardened -020).

Fixture workspace + injected HTTP fetcher. The build_report fixture carries a
MISLEADING comment ('set PUBLICATION_STATUS = "published"') before the real
assignment, so a regex would false-pass; release_gate must use ast and read the
real value. Covers: all-published passes; a draft real assignment (with the
decoy comment) fails; missing tag / release / undownloadable / mismatched ZIP;
missing README; a README that omits the ZIP; empty/stale immutable URLs.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_gate as rg  # noqa: E402

TAG = "phase1-v1.0"


class TestReleaseGate(unittest.TestCase):
    def _root(self, *, status="published", urls=True, readme="names",
              ) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        pub = root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        self.zip_name = "phase1-raw-logs-22360106b1f4.zip"
        self.zip_bytes = b"PK\x03\x04 fake zip payload"
        (pub / self.zip_name).write_bytes(self.zip_bytes)
        self.zip_sha = hashlib.sha256(self.zip_bytes).hexdigest()
        (pub / (self.zip_name + ".sha256")).write_text(
            f"{self.zip_sha}  {self.zip_name}\n", encoding="utf-8")
        if readme == "names":
            (pub / "README.md").write_text(
                f"Asset: {self.zip_name}\n", encoding="utf-8")
        elif readme == "omits":
            (pub / "README.md").write_text(
                "Asset: phase1-raw-logs-old.zip\n", encoding="utf-8")
        # readme == "missing": no README file
        if urls == "noncanonical":
            repo = f'"https://example.invalid/{TAG}"'
            logs = (f'"https://example.invalid/{TAG}/published-logs/phase1/'
                    f'{self.zip_name}"')
        elif urls:
            repo = (f'"https://github.com/chibilogic/rtos-benchmark/tree/'
                    f'{TAG}"')
            logs = (f'"https://raw.githubusercontent.com/chibilogic/'
                    f'rtos-benchmark/{TAG}/published-logs/phase1/'
                    f'{self.zip_name}"')
        else:
            repo = logs = '""'
        (root / "scripts").mkdir()
        # The decoy comment must NOT be picked up instead of the assignment.
        (root / "scripts" / "build_report.py").write_text(
            '# Fill the URLs and set PUBLICATION_STATUS = "published" at Gate D\n'
            f'PUBLIC_REPOSITORY_URL = {repo}\n'
            f'PUBLIC_RAW_LOGS_URL = {logs}\n'
            f'PUBLICATION_STATUS = "{status}"\n', encoding="utf-8")
        return root

    def _fetch(self, *, tag=200, release=200, raw=200, raw_body=None):
        def fetch(url):
            if "git/refs/tags" in url:
                return tag, b""
            if "releases/tags" in url:
                return release, b""
            if "raw.githubusercontent.com" in url:
                return raw, (self.zip_bytes if raw_body is None else raw_body)
            return 404, b""
        return fetch

    def test_published_passes(self):
        self.assertEqual(rg.run_gate(self._root(), fetch=self._fetch()), [])

    def test_draft_with_decoy_comment_fails(self):
        # The decoy comment says "published"; the real assignment is draft.
        out = rg.run_gate(self._root(status="draft"), fetch=self._fetch())
        self.assertTrue(any("PUBLICATION_STATUS" in f and "draft" in f
                            for f in out), out)

    def test_missing_tag_fails(self):
        out = rg.run_gate(self._root(), fetch=self._fetch(tag=404))
        self.assertTrue(any("tag" in f for f in out), out)

    def test_missing_release_fails(self):
        out = rg.run_gate(self._root(), fetch=self._fetch(release=404))
        self.assertTrue(any("Release" in f for f in out), out)

    def test_raw_zip_undownloadable_fails(self):
        out = rg.run_gate(self._root(), fetch=self._fetch(raw=404))
        self.assertTrue(any("not downloadable" in f for f in out), out)

    def test_zip_sha_mismatch_fails(self):
        out = rg.run_gate(self._root(), fetch=self._fetch(raw_body=b"x"))
        self.assertTrue(any("sha256" in f for f in out), out)

    def test_missing_readme_fails(self):
        out = rg.run_gate(self._root(readme="missing"), fetch=self._fetch())
        self.assertTrue(any("README missing" in f for f in out), out)

    def test_readme_omits_name_fails(self):
        out = rg.run_gate(self._root(readme="omits"), fetch=self._fetch())
        self.assertTrue(any("does not name" in f for f in out), out)

    def test_empty_urls_fail(self):
        out = rg.run_gate(self._root(urls=False), fetch=self._fetch())
        self.assertTrue(any("PUBLIC_REPOSITORY_URL" in f for f in out), out)
        self.assertTrue(any("PUBLIC_RAW_LOGS_URL" in f for f in out), out)

    def test_noncanonical_urls_fail(self):
        # URLs on another host with the tag as a mere substring must fail.
        out = rg.run_gate(self._root(urls="noncanonical"), fetch=self._fetch())
        self.assertTrue(any("PUBLIC_REPOSITORY_URL" in f for f in out), out)
        self.assertTrue(any("PUBLIC_RAW_LOGS_URL" in f for f in out), out)

    def test_local_sidecar_mismatch_raises(self):
        root = self._root()
        side = (root / "published-logs" / "phase1"
                / (self.zip_name + ".sha256"))
        side.write_text("deadbeef  " + self.zip_name + "\n", encoding="utf-8")
        with self.assertRaises(rg.GateError):
            rg.run_gate(root, fetch=self._fetch())


if __name__ == "__main__":
    unittest.main()
