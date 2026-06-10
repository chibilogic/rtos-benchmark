# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
"""Unit tests for scripts/loadable_image.py (ADR-025).

These cover the pure logic (hashing + lock augmentation) without requiring the
ARM toolchain; the objcopy-dependent path is exercised by the lab harness.
"""

import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SPEC = importlib.util.spec_from_file_location(
    "loadable_image", os.path.join(_REPO, "scripts", "loadable_image.py"))
li = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(li)


class Sha256Test(unittest.TestCase):
    def test_known_vectors(self):
        self.assertEqual(
            li.sha256_bytes(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca"
            "495991b7852b855")
        self.assertEqual(
            li.sha256_bytes(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb"
            "410ff61f20015ad")


class ProfileFromLockTest(unittest.TestCase):
    def test_extracts_profile(self):
        self.assertEqual(
            li._profile_from_lock("fair_perf_campaign.lock.json"),
            "fair_perf")
        self.assertEqual(
            li._profile_from_lock("realistic_tickless_campaign.lock.json"),
            "realistic_tickless")

    def test_rejects_other_names(self):
        self.assertIsNone(li._profile_from_lock("random.json"))


class AugmentLockTest(unittest.TestCase):
    def _lock(self):
        return {"rtoses": {
            "chibios":  {"elf": "x", "elf_sha256": "AAA",
                         "map": "y", "map_sha256": "BBB"},
            "freertos": {"elf": "z", "elf_sha256": "CCC",
                         "map": "w", "map_sha256": "DDD"}}}

    def test_adds_field_keeps_originals(self):
        lock = self._lock()
        calls = []

        def fake_hash(elf):
            calls.append(elf)
            return "HASH_" + os.path.basename(elf)

        n = li.augment_lock(lock, "fair_perf", "/raw", fake_hash)
        self.assertEqual(n, 2)
        chib = lock["rtoses"]["chibios"]
        # New field, computed from the manifest-bound run01 ELF path.
        self.assertEqual(chib["loadable_image_sha256"],
                         "HASH_chibios_fair_perf_run01.elf")
        self.assertTrue(any("chibios_fair_perf_run01.elf" in c
                            for c in calls))
        # Measured identity fields are left untouched.
        self.assertEqual(chib["elf_sha256"], "AAA")
        self.assertEqual(chib["map_sha256"], "BBB")
        self.assertEqual(chib["elf"], "x")

    def test_idempotent(self):
        lock = self._lock()
        li.augment_lock(lock, "fair_perf", "/raw",
                        lambda e: "H_" + os.path.basename(e))
        first = lock["rtoses"]["chibios"]["loadable_image_sha256"]
        li.augment_lock(lock, "fair_perf", "/raw",
                        lambda e: "H_" + os.path.basename(e))
        self.assertEqual(lock["rtoses"]["chibios"]["loadable_image_sha256"],
                         first)


if __name__ == "__main__":
    unittest.main()
