#!/usr/bin/env python3
"""Validation suite for scripts/zephyr_cflags_audit.py."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT    = REPO_ROOT / "scripts" / "zephyr_cflags_audit.py"


GOOD_FLAGS = [
    "-mcpu=cortex-m7",
    "-mthumb",
    "-mfpu=fpv5-d16",
    "-mfloat-abi=hard",
    "-O2",
    "-fomit-frame-pointer",
    "-falign-functions=16",
    "-ffunction-sections",
    "-fdata-sections",
    "-fno-common",
    "-fno-strict-aliasing",
]


def common_entry(name: str, *extra_flags: str) -> dict:
    # benchmark common/*.c sources pulled in by
    # zephyr/benchmark_zephyr/CMakeLists.txt::target_sources.
    return {
        "directory": "/build",
        "command":   make_command(*extra_flags),
        "file":      f"/repo/common/{name}",
    }


def make_command(*extra_flags: str) -> str:
    args = (["arm-none-eabi-gcc"] + GOOD_FLAGS + list(extra_flags)
            + ["-c", "-o", "out.o", "main.c"])
    return " ".join(args)


def app_entry(name: str, *extra_flags: str) -> dict:
    return {
        "directory": "/build",
        "command":   make_command(*extra_flags),
        "file":      f"/src/benchmark_zephyr/src/{name}",
    }


# Codex round 2026-05-14-bucket-c-track-001 IMPORTANT 1
# (publishable-profile source-set completeness gate). The
# audit now requires every expected app + common source to be
# present in the in-scope set. Tests that drove the per-entry
# logic only had 1-3 fixtures; they now build on the full
# expected set and inject the focused failure on top.
APP_BASENAMES = (
    "main.c",
    "test_ctxsw_irq.c",
    "test_thread_handoff.c",
    "test_mutex_uncontended.c",
    "test_mutex_pi.c",
)
COMMON_BASENAMES = (
    "dwt_cycle_counter.c",
    "benchmark_stats.c",
    "bench_button.c",
)


def full_app_set() -> list[dict]:
    """All 8 expected entries with clean flags. Tests that
    want to exercise the per-entry gate mutate one entry of
    this set after copying it."""
    return ([app_entry(n) for n in APP_BASENAMES]
            + [common_entry(n) for n in COMMON_BASENAMES])


def hal_entry(name: str) -> dict:
    # HAL entries are NOT audited; we put garbage flags here on
    # purpose to make sure the script ignores them.
    return {
        "directory": "/build",
        "command":   "arm-none-eabi-gcc -Os -flto -c -o hal.o hal.c",
        "file":      f"/zephyr/drivers/{name}",
    }


def write_cc(build_dir: Path, app_entries: list,
             hal_entries: list | None = None) -> None:
    entries = list(app_entries) + list(hal_entries or [])
    (build_dir / "compile_commands.json").write_text(
        json.dumps(entries), encoding="utf-8")


def run_audit(build_dir: Path, profile: str
              ) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT),
           "--build-dir", str(build_dir),
           "--profile", profile]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", env=env)


class ZephyrCflagsAuditTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.build_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_01_clean_fair_perf_passes(self):
        write_cc(self.build_dir, full_app_set(),
                 [hal_entry("uart.c")])
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("8 Zephyr application object", proc.stdout)

    def test_02_missing_required_flag_fails(self):
        entries = [
            app_entry("main.c"),
            app_entry("test_ctxsw_irq.c"),
        ]
        entries[1]["command"] = entries[1]["command"].replace(
            "-fomit-frame-pointer ", "")
        write_cc(self.build_dir, entries)
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing flag -fomit-frame-pointer",
                      proc.stderr)
        self.assertIn("test_ctxsw_irq.c", proc.stderr)

    def test_03_forbidden_flag_fails(self):
        bad = app_entry("main.c", "-flto")
        write_cc(self.build_dir, [bad])
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("forbidden flag -flto", proc.stderr)

    def test_04_lto_variant_fails(self):
        bad = app_entry("main.c", "-flto=auto")
        write_cc(self.build_dir, [bad])
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("forbidden flag -flto", proc.stderr)

    def test_05_realistic_tickless_same_contract(self):
        write_cc(self.build_dir, full_app_set())
        proc = run_audit(self.build_dir, "realistic_tickless")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    def test_06_debug_dev_skipped(self):
        bad = {"directory": "/build",
               "command": "arm-none-eabi-gcc -Os -flto -c main.c",
               "file":    "/src/benchmark_zephyr/src/main.c"}
        write_cc(self.build_dir, [bad])
        proc = run_audit(self.build_dir, "debug_dev")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("audit skipped", proc.stdout)

    def test_07_no_app_entries_fails(self):
        write_cc(self.build_dir, [], [hal_entry("uart.c")])
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no application sources matched",
                      proc.stderr)

    def test_08_missing_cc_file_fails(self):
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("compile_commands.json", proc.stderr)
        self.assertIn("not found", proc.stderr)

    def test_09_arguments_format_supported(self):
        # Use the 'arguments' (list) JSON variant for one
        # entry and the canonical 'command' (string) variant
        # for the remaining 7 entries needed by the
        # completeness gate.
        e_args = {
            "directory": "/build",
            "arguments": ["arm-none-eabi-gcc"] + GOOD_FLAGS + [
                "-c", "-o", "out.o", "main.c"],
            "file":      "/src/benchmark_zephyr/src/main.c",
        }
        rest = ([app_entry(n) for n in APP_BASENAMES[1:]]
                + [common_entry(n) for n in COMMON_BASENAMES])
        (self.build_dir / "compile_commands.json").write_text(
            json.dumps([e_args] + rest), encoding="utf-8")
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    def test_10_hal_entries_not_audited(self):
        write_cc(self.build_dir,
                 full_app_set(),
                 [hal_entry("uart.c"), hal_entry("rcc.c")])
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    # --- Codex round-3 item 3 PASS_WITH_FIXES followup -----------

    def test_11_common_entry_audited_passes(self):
        # common/*.c sources are compiled into the Zephyr app
        # target; they must satisfy the same flag contract.
        # full_app_set() already includes all 3 common
        # entries plus the 5 app entries required by the
        # publishable-profile completeness gate.
        write_cc(self.build_dir, full_app_set())
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("8 Zephyr application object", proc.stdout)

    def test_12_common_entry_bad_flag_fails(self):
        # Inject a missing required flag on a common/ entry.
        bad = common_entry("dwt_cycle_counter.c")
        bad["command"] = bad["command"].replace(
            "-fno-common ", "")
        write_cc(self.build_dir,
                 [app_entry("main.c"), bad])
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("dwt_cycle_counter.c", proc.stderr)
        self.assertIn("missing flag -fno-common", proc.stderr)

    def test_13_O1_fails(self):
        e = app_entry("main.c")
        e["command"] = e["command"].replace(" -O2 ", " -O1 ")
        write_cc(self.build_dir, [e])
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("-O1", proc.stderr)

    def test_14_Og_fails(self):
        e = app_entry("main.c")
        e["command"] = e["command"].replace(" -O2 ", " -Og ")
        write_cc(self.build_dir, [e])
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("-Og", proc.stderr)

    def test_15_O2_followed_by_Og_fails(self):
        # GCC uses the last -O on the command line. -O2 followed
        # by -Og means effective optimization is -Og.
        e = app_entry("main.c", "-Og")
        write_cc(self.build_dir, [e])
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("wrong effective optimization", proc.stderr)
        self.assertIn("-Og", proc.stderr)

    # --- Codex round 2026-05-14-bucket-c-track-001 follow-up ---

    def test_17_completeness_missing_test_thread_handoff_fails(
            self):
        entries = full_app_set()
        # Drop test_thread_handoff.c from the in-scope set.
        entries = [e for e in entries
                   if not e["file"].endswith(
                       "test_thread_handoff.c")]
        write_cc(self.build_dir, entries)
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing source test_thread_handoff.c",
                      proc.stderr)

    def test_18_completeness_missing_bench_button_fails(self):
        entries = [e for e in full_app_set()
                   if not e["file"].endswith("bench_button.c")]
        write_cc(self.build_dir, entries)
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing source bench_button.c",
                      proc.stderr)

    def test_19_completeness_realistic_tickless_enforced(self):
        entries = [e for e in full_app_set()
                   if not e["file"].endswith("main.c")]
        write_cc(self.build_dir, entries)
        proc = run_audit(self.build_dir, "realistic_tickless")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing source main.c", proc.stderr)

    def test_20_completeness_debug_dev_skipped(self):
        # debug_dev has no CFLAGS contract; an incomplete set
        # must still produce the "audit skipped" output.
        write_cc(self.build_dir, [app_entry("main.c")])
        proc = run_audit(self.build_dir, "debug_dev")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("audit skipped", proc.stdout)

    def test_21_bare_O_fails(self):
        # Bare '-O' is valid GCC syntax but is NOT -O2 for
        # the publishable contract (Codex MINOR 1).
        entries = full_app_set()
        entries[0]["command"] = entries[0]["command"].replace(
            " -O2 ", " -O ")
        write_cc(self.build_dir, entries)
        proc = run_audit(self.build_dir, "fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("wrong effective optimization",
                      proc.stderr)
        # The reported effective opt token must be '-O' bare.
        self.assertIn("-O (expected -O2)", proc.stderr)

    def test_16_makefile_exports_compile_commands(self):
        # Sanity: the Zephyr Makefile wrapper must explicitly
        # enable compile_commands.json export (Codex round-3
        # item 3 BLOCKER 3).
        mk = (REPO_ROOT / "zephyr" / "benchmark_zephyr"
              / "Makefile").read_text(encoding="utf-8")
        self.assertIn("-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", mk,
                      "Zephyr wrapper must explicitly enable "
                      "compile_commands.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
