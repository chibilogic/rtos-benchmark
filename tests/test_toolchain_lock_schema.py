#!/usr/bin/env python3
"""Lock-level invariants validation (Codex
2026-05-20-adr021-patch-set-3-plan-review-001 MISSING DESIGN 5,
applied at 2026-05-21 patch set 3b)."""
from __future__ import annotations
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK = REPO_ROOT / "tools" / "TOOLCHAIN.lock"
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class ToolchainLockSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))

    def test_01_schema_version_present(self) -> None:
        self.assertEqual(self.lock.get("schema_version"), 2,
                         "lock must declare schema_version=2")

    def test_02_platforms_present(self) -> None:
        plats = self.lock.get("platforms", {})
        self.assertIn("windows-x86_64", plats)
        self.assertIn("linux-x86_64", plats)

    def test_03_managed_entries_have_https_url(self) -> None:
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                if not spec.get("managed", True):
                    continue
                url = spec.get("url", "")
                self.assertTrue(url.startswith("https://"),
                                f"{plat}/{name} url must be https")

    def test_04_managed_entries_have_64_hex_sha256(self) -> None:
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                if not spec.get("managed", True):
                    continue
                sha = spec.get("sha256", "")
                self.assertTrue(SHA256_HEX_RE.match(sha),
                                f"{plat}/{name} sha256 must be 64-hex")

    def test_05_no_latest_in_url(self) -> None:
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                url = spec.get("url", "")
                self.assertNotIn("latest", url.lower(),
                                 f"{plat}/{name} url must be "
                                 f"version-pinned, not 'latest'")

    def test_06_destination_under_tools_platform(self) -> None:
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                if not spec.get("managed", True):
                    continue
                dest = spec.get("destination", "")
                self.assertTrue(dest.startswith(f"tools/{plat}/"),
                                f"{plat}/{name} destination must be "
                                f"under tools/{plat}/")

    def test_07_expect_non_empty(self) -> None:
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                if not spec.get("managed", True):
                    continue
                self.assertTrue(spec.get("expect"),
                                f"{plat}/{name} expect must be "
                                f"non-empty")

    def test_08_unmanaged_requires_skip_reason(self) -> None:
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                if spec.get("managed", True):
                    continue
                self.assertTrue(spec.get("skip_reason"),
                                f"{plat}/{name} (managed=false) "
                                f"must have non-empty skip_reason")

    def test_09_unmanaged_has_no_url_sha(self) -> None:
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                if spec.get("managed", True):
                    continue
                self.assertNotIn("url", spec,
                                 f"{plat}/{name} (unmanaged) must "
                                 f"not have url")
                self.assertNotIn("sha256", spec,
                                 f"{plat}/{name} (unmanaged) must "
                                 f"not have sha256")

    def test_10_managed_has_inspection_block(self) -> None:
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                if not spec.get("managed", True):
                    continue
                insp = spec.get("inspection")
                self.assertIsInstance(insp, dict,
                                      f"{plat}/{name} must have "
                                      f"'inspection' dict block")

    def test_11_inspection_required_fields(self) -> None:
        required = ("date", "host", "sha256_computed_locally",
                    "members_total", "absolute_paths",
                    "path_traversals", "symlinks", "hardlinks",
                    "special_files",
                    "bootstrap_end_to_end_executed_on_host",
                    "bootstrap_execution_host")
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                if not spec.get("managed", True):
                    continue
                insp = spec.get("inspection", {})
                for f in required:
                    self.assertIn(f, insp,
                                  f"{plat}/{name} inspection missing"
                                  f" field '{f}'")

    def test_12_inspection_bootstrap_fields_type_contract(self) -> None:
        # Codex CODE_REVIEW 2026-05-21-adr021-patch-set-3b-ssl-code-
        # review-001 IMPORTANT 1: enforce the normalized contract.
        for plat, comps in self.lock["platforms"].items():
            for name, spec in comps.items():
                if not spec.get("managed", True):
                    continue
                insp = spec.get("inspection", {})
                executed = insp.get(
                    "bootstrap_end_to_end_executed_on_host")
                self.assertIsInstance(executed, bool,
                                      f"{plat}/{name} "
                                      f"bootstrap_end_to_end_executed"
                                      f"_on_host must be bool")
                host = insp.get("bootstrap_execution_host")
                self.assertTrue(host is None
                                or (isinstance(host, str) and host),
                                f"{plat}/{name} "
                                f"bootstrap_execution_host must be "
                                f"null or non-empty string")
                if executed:
                    self.assertIsInstance(host, str,
                                          f"{plat}/{name} executed="
                                          f"true requires "
                                          f"bootstrap_execution_host "
                                          f"string")


if __name__ == "__main__":
    unittest.main(verbosity=2)
