#!/usr/bin/env python3
"""
Validation suite for scripts/collect_results.py (round-8 sec. 1).

The reviewer mandates that the collector be tested on:
    1. a good log               -> exit 0, .csv produced
    2. a log without DONE       -> exit != 0, no .csv
    3. a log with rows missing  -> exit != 0, no .csv
    4. a log with profile/rtos  -> exit != 0, no .csv
       mismatch

Fixtures are generated programmatically in a temp directory so the
test suite is self-contained and the repo is not bloated by ~2 MB
of synthetic CSV per case.

Run:
    python -m unittest tests.test_collect_results -v
or:
    python tests/test_collect_results.py
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT  = Path(__file__).resolve().parents[1]
SCRIPT     = REPO_ROOT / "scripts" / "collect_results.py"
SYS_CLOCK  = 480_000_000


# === Fixture generator ================================================

def _us(cycles: int) -> str:
    return f"{cycles * 1_000_000.0 / SYS_CLOCK:.6f}"


def synthesize_good_log(rtos: str = "chibios",
                        profile: str = "fair_perf") -> str:
    """Build a fully-valid raw log identical in shape to what the
    firmware emits, with the exact row counts required by the
    acceptance contract (1000 warmup + 10000 valid for T1/T2/T3,
    100 valid + 100 PI for T4)."""
    L: list[str] = []
    bar = "=" * 42

    tickless = "ON"  if profile == "realistic_tickless" else "OFF"
    wfi      = "ON"  if profile == "realistic_tickless" else "OFF"

    # --- Banner ---
    # The kernel label is product-name + version. The version part
    # is taken from the RTOS itself at firmware build:
    # CH_KERNEL_VERSION / tskKERNEL_VERSION_NUMBER /
    # KERNEL_VERSION_STRING. The values below are synthetic - they
    # exist only to populate the fake banner that this fixture
    # writes; the test verifies that the same string is propagated
    # by the collector / report stack, NOT that they match any
    # particular firmware build.
    kernels = {"chibios":  "ChibiOS RT 7.0.6",
               "freertos": "FreeRTOS V11.3.0",
               "zephyr":   "Zephyr 4.4.0"}
    L.append(bar)
    L.append("  RTOS Benchmark")
    L.append(f"  RTOS         : {rtos}")
    L.append(f"  RTOS kernel  : {kernels[rtos]}")
    L.append(f"  Profile      : {profile}")
    L.append("  Board        : STM32H750B-DK")
    L.append(f"  SystemClock  : {SYS_CLOCK} Hz")
    L.append("  ICache       : ON")
    L.append("  DCache       : ON")
    L.append("  VOS level    : VOS0")
    L.append("  VOSRDY       : READY")
    L.append("  FLASH_ACR    : 0x00000034")
    L.append(f"  Tickless     : {tickless}")
    L.append(f"  WFI in idle  : {wfi}")
    L.append("  Tick rate    : 1000 Hz")
    L.append("  Optimization : -O2  LTO=no")
    L.append("  DWT overhead : 4 cycles (0.008 us)")
    L.append(bar)

    # --- Memory placement table (ADR-017) ---
    L.append("--- Benchmark memory placement (ADR-017) ---")
    L.append("  bench_addr  axi_sram_start    : 0x24000000  INFO")
    L.append("  bench_addr  axi_sram_end      : 0x24080000  INFO")
    L.append("  bench_addr  nocache_start     : 0x30040000  INFO")
    L.append("  bench_addr  nocache_end       : 0x30048000  INFO")
    # 4 sample buffers + a representative slice of every test's
    # private working set (round-12 sec. 3: at least N tN_ objects per
    # test). All in AXI SRAM. Addresses are arbitrary but consistent
    # with the real firmware's [0x24000000..0x24080000) range.
    for name, addr in (
        ("samples_t1",        "0x2402acc8"),
        ("samples_t2",        "0x240200e8"),
        ("samples_t3",        "0x24015508"),
        ("samples_t4",        "0x2400a928"),
        # T1 (>= 2)
        ("t1_target_stack",   "0x240358a8"),
        ("t1_t_isr_entry",    "0x24035c74"),
        # T2 (>= 2)
        ("t2_target_stack",   "0x24035c98"),
        ("t2_handoff_t_send", "0x24036074"),
        # T3 (>= 1)
        ("t3_mtx",            "0x24036078"),
        # T4 (>= 6)
        ("t4_l_stack",        "0x24036c10"),
        ("t4_m_stack",        "0x24036650"),
        ("t4_h_stack",        "0x24036090"),
        ("t4_pi_mtx",         "0x24037278"),
        ("t4_go_l_sem",       "0x2403726c"),
        ("t4_pi_ok_array",    "0x240371d0"),
    ):
        L.append(f"  bench_addr  {name:<18}: {addr}  AXI_SRAM OK")
    L.append("--- end memory placement ---")

    # --- CSV header ---
    L.append("rtos,profile,test_name,metric,phase,iteration,"
             "cycles,microseconds")

    # --- T1 / T2 / T3: 1000 warmup + 10000 valid ---
    # Iterations are 1-based to match firmware bench_print_csv()
    # which emits `i + 1U` (round-9 sec. A5).
    for tname, metric in (
        ("t1_irq",        "dwt_a4_minus_a1"),
        ("t2_handoff",    "dwt_thread_to_thread"),
        ("t3_mtx_uncont", "dwt_lock_unlock_pair"),
    ):
        L.append(f"=== READY {tname} ===")
        L.append(f"=== START {tname} ===")
        # Inject TIM2 manifest dump only after t1_irq setup, exactly
        # like the firmware does.
        if tname == "t1_irq":
            L.append("--- TIM2 state (after_t1_setup) ---")
            L.append("  TIM2_CR1     : 0x00000000")
            L.append("  TIM2_DIER    : 0x00000002")
            L.append("  TIM2_CCMR1   : 0x00000078")
            L.append("  TIM2_CCER    : 0x00000001")
            L.append("  TIM2_PSC     : 0x000000ef")
            L.append("  TIM2_ARR     : 0x000003e7")
            L.append("  TIM2_CCR1    : 0x00000001")
            L.append("--- end TIM2 state ---")
        for i in range(1, 1001):
            c = 100 + (i % 10)
            L.append(f"{rtos},{profile},{tname},{metric},warmup,{i},"
                     f"{c},{_us(c)}")
        for i in range(1, 10001):
            c = 200 + (i % 10)
            L.append(f"{rtos},{profile},{tname},{metric},valid,{i},"
                     f"{c},{_us(c)}")
        # And the after_t1_run dump (just so the banner archive
        # carries the same shape the firmware emits).
        if tname == "t1_irq":
            L.append("--- TIM2 state (after_t1_run) ---")
            L.append("  TIM2_CR1     : 0x00000000")
            L.append("  TIM2_DIER    : 0x00000000")
            L.append("  TIM2_CCMR1   : 0x00000078")
            L.append("  TIM2_CCER    : 0x00000000")
            L.append("  TIM2_PSC     : 0x000000ef")
            L.append("  TIM2_ARR     : 0x000003e7")
            L.append("  TIM2_CCR1    : 0x00000001")
            L.append("--- end TIM2 state ---")

    # --- T4: 100 valid + 100 PI rows, no warmup ---
    L.append("=== READY t4_mtx_pi ===")
    L.append("=== START t4_mtx_pi ===")
    for i in range(1, 101):
        c = 250 + i
        L.append(f"{rtos},{profile},t4_mtx_pi,"
                 f"dwt_low_unlock_to_high_acquire,valid,{i},"
                 f"{c},{_us(c)}")
    for i in range(1, 101):
        L.append(f"{rtos},{profile},t4_mtx_pi,{i},1")

    # --- DONE marker ---
    L.append("")
    L.append("=== BENCHMARK COMPLETE ===")
    return "\n".join(L) + "\n"


# === Test harness =====================================================

class CollectResultsTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp  = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, log_text: str, *,
             rtos: str = "chibios",
             profile: str = "fair_perf",
             run_id: str = "99",
             publication_mode: str | None = "dwt_only",
             elf_file: str | None | bool = True,
             map_file: str | None | bool = True,
             ) -> tuple[subprocess.CompletedProcess, Path]:
        # elf_file / map_file semantics:
        #   True  -> auto-create a fake file in tempdir and pass it
        #   None  -> do not pass the CLI flag at all
        #   str   -> pass this path verbatim (may or may not exist)
        log_path = self.tmp / "raw_in.log"
        log_path.write_text(log_text, encoding="utf-8")
        prefix = self.tmp / "out"
        cmd = [
            sys.executable, str(SCRIPT),
            "--from-log", str(log_path),
            "--rtos",     rtos,
            "--profile",  profile,
            "--run-id",   run_id,
            "--output",   str(prefix),
            "--quiet",
        ]
        if publication_mode is not None:
            cmd += ["--publication-mode", publication_mode]
        if elf_file is True:
            p = self.tmp / "fake.elf"
            p.write_bytes(b"\x7fELF" + b"chibilogic-fake-elf-payload" * 8)
            cmd += ["--elf-file", str(p)]
        elif isinstance(elf_file, str):
            cmd += ["--elf-file", elf_file]
        if map_file is True:
            p = self.tmp / "fake.map"
            p.write_text("fake map file payload\n" * 10,
                         encoding="utf-8")
            cmd += ["--map-file", str(p)]
        elif isinstance(map_file, str):
            cmd += ["--map-file", map_file]
        env = os.environ.copy()
        # PYTHONIOENCODING avoids cp1252 mojibake on Windows when
        # printing unicode, but our fixtures are pure ASCII so this
        # is just defensive.
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        return proc, prefix

    # --- Case 1: good log passes -------------------------------------

    def test_01_good_log_passes(self):
        proc, prefix = self._run(synthesize_good_log())
        self.assertEqual(proc.returncode, 0,
                         f"stdout:\n{proc.stdout}\n"
                         f"stderr:\n{proc.stderr}")
        # Outputs are produced
        self.assertTrue((self.tmp / "out.csv").is_file())
        self.assertTrue((self.tmp / "out.t4_pi.csv").is_file())
        self.assertTrue((self.tmp / "out.banner.txt").is_file())
        self.assertTrue((self.tmp / "out.stdout.txt").is_file())
        # Row counts in csv
        csv_lines = (self.tmp / "out.csv").read_text(
            encoding="utf-8").splitlines()
        # 1 header + 3 tests * (1000+10000) + 100 t4 = 33101
        self.assertEqual(len(csv_lines), 1 + 3 * 11000 + 100)
        t4pi_lines = (self.tmp / "out.t4_pi.csv").read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(len(t4pi_lines), 1 + 100)

    # --- Case 2: missing BENCHMARK COMPLETE ---------------------------

    def test_02_no_done_marker_fails(self):
        log = synthesize_good_log()
        log = log.replace("=== BENCHMARK COMPLETE ===\n", "")
        proc, prefix = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("BENCHMARK COMPLETE", proc.stderr)
        # No .csv emitted on failure (raw log IS written for diagnostics)
        self.assertFalse((self.tmp / "out.csv").is_file())
        self.assertFalse((self.tmp / "out.t4_pi.csv").is_file())
        self.assertTrue((self.tmp / "out.stdout.txt").is_file())

    # --- Case 3: missing DWT rows -------------------------------------

    def test_03_missing_rows_fails(self):
        log = synthesize_good_log()
        # Drop one t2_handoff valid row
        lines = log.splitlines()
        target = "chibios,fair_perf,t2_handoff,dwt_thread_to_thread," \
                 "valid,5000,"
        for i, line in enumerate(lines):
            if line.startswith(target):
                lines.pop(i)
                break
        else:
            self.fail("fixture broken: no matching t2 valid row")
        log = "\n".join(lines) + "\n"
        proc, prefix = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("t2_handoff: valid rows = 9999", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    # --- Case 4: profile mismatch -------------------------------------

    def test_04_profile_mismatch_fails(self):
        # Log generated with profile=fair_perf but invoke collector
        # with --profile realistic_tickless. After A2, the first gate
        # that trips is the banner Tickless/WFI line (expected ON for
        # realistic_tickless, OFF in this log). The DWT-row profile
        # mismatch would also catch it. Either is acceptable.
        log = synthesize_good_log(profile="fair_perf")
        proc, prefix = self._run(log, profile="realistic_tickless")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(
            "profile=" in proc.stderr or "Profile" in proc.stderr
            or "Tickless" in proc.stderr
            or "WFI in idle" in proc.stderr,
            msg=f"stderr was:\n{proc.stderr}",
        )
        self.assertFalse((self.tmp / "out.csv").is_file())

    # --- Bonus: rtos mismatch -----------------------------------------

    def test_05_rtos_mismatch_fails(self):
        log = synthesize_good_log(rtos="chibios")
        proc, prefix = self._run(log, rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue("rtos=" in proc.stderr
                        or "RTOS" in proc.stderr,
                        msg=f"stderr was:\n{proc.stderr}")
        self.assertFalse((self.tmp / "out.csv").is_file())

    # --- Bonus: debug_dev row in fair_perf ----------------------------

    def test_06_debug_dev_in_fair_perf_fails(self):
        log = synthesize_good_log()
        # Inject a debug_dev row right before BENCHMARK COMPLETE
        c = 123
        bad = (f"chibios,debug_dev,t1_irq,dwt_a4_minus_a1,valid,"
               f"99999,{c},{_us(c)}")
        log = log.replace("=== BENCHMARK COMPLETE ===",
                          bad + "\n=== BENCHMARK COMPLETE ===")
        proc, prefix = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        # Either profile-mismatch or debug_dev gate triggers first
        self.assertTrue("debug_dev" in proc.stderr or
                        "profile=" in proc.stderr,
                        proc.stderr)

    # --- Bonus: bad us value ------------------------------------------

    def test_07_microseconds_inconsistent_fails(self):
        log = synthesize_good_log()
        # Replace one us value with something far off
        lines = log.splitlines()
        target_prefix = ("chibios,fair_perf,t3_mtx_uncont,"
                         "dwt_lock_unlock_pair,valid,42,")
        for i, line in enumerate(lines):
            if line.startswith(target_prefix):
                # keep cycles, replace us with garbage
                head, _, _us_field = line.rpartition(",")
                lines[i] = head + ",9999.999999"
                break
        else:
            self.fail("fixture broken: no t3 valid row index 42")
        log = "\n".join(lines) + "\n"
        proc, prefix = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("us=9999.999999", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_07b_cycles_zero_fails(self):
        log = synthesize_good_log()
        # Replace one cycles value with 0; the collector must
        # reject because real DWT measurements always require
        # cycles > 0 (see scripts/collect_results.py cycles <= 0
        # guard).
        lines = log.splitlines()
        target_prefix = ("chibios,fair_perf,t3_mtx_uncont,"
                         "dwt_lock_unlock_pair,valid,42,")
        for i, line in enumerate(lines):
            if line.startswith(target_prefix):
                fields    = line.split(",")
                fields[6] = "0"          # cycles field
                lines[i]  = ",".join(fields)
                break
        else:
            self.fail("fixture broken: no t3 valid row index 42")
        log = "\n".join(lines) + "\n"
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("cycles non-positive", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    # --- Bonus: iteration gap (count OK but set != 1..N) -------------

    def test_09_iteration_gap_fails(self):
        log = synthesize_good_log()
        # Replace iter=42 of t3 valid with iter=99999. Count stays
        # at 10000 but the set is no longer {1..10000}.
        lines = log.splitlines()
        target_42  = "chibios,fair_perf,t3_mtx_uncont," \
                     "dwt_lock_unlock_pair,valid,42,"
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(target_42):
                fields    = line.split(",")
                fields[5] = "99999"     # iteration field
                lines[i]  = ",".join(fields)
                replaced  = True
                break
        self.assertTrue(replaced, "fixture broken: t3 iter=42 not found")
        log = "\n".join(lines) + "\n"
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("iteration sequence", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    # --- Bonus: duplicate iteration ----------------------------------

    def test_10_duplicate_iteration_fails(self):
        log = synthesize_good_log()
        # Make iter=7 appear twice in t1 valid: replace iter=42 with
        # a duplicate of iter=7's row. Count stays 10000, set has
        # 9999 distinct values.
        lines = log.splitlines()
        target_7  = "chibios,fair_perf,t1_irq,dwt_a4_minus_a1,valid,7,"
        target_42 = "chibios,fair_perf,t1_irq,dwt_a4_minus_a1,valid,42,"
        row7 = None
        for line in lines:
            if line.startswith(target_7):
                row7 = line
                break
        self.assertIsNotNone(row7, "fixture broken: t1 iter=7 missing")
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(target_42):
                lines[i] = row7   # duplicate of iter=7
                replaced = True
                break
        self.assertTrue(replaced, "fixture broken: t1 iter=42 missing")
        log = "\n".join(lines) + "\n"
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        # Either "iteration sequence" or "duplicate iterations"
        self.assertTrue("iteration" in proc.stderr,
                        msg=f"stderr was:\n{proc.stderr}")
        self.assertFalse((self.tmp / "out.csv").is_file())

    # --- Bonus: banner missing VOS line (round-9 sec. A2) -----------------

    def test_11_banner_missing_vos_fails(self):
        log = synthesize_good_log()
        log = log.replace("  VOS level    : VOS0\n", "")
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("VOS level", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_12_banner_wrong_flash_acr_fails(self):
        log = synthesize_good_log()
        log = log.replace("  FLASH_ACR    : 0x00000034",
                          "  FLASH_ACR    : 0x00000032")
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("FLASH_ACR", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_13_banner_wrong_tickless_for_fair_perf_fails(self):
        log = synthesize_good_log(profile="fair_perf")
        log = log.replace("  Tickless     : OFF",
                          "  Tickless     : ON")
        proc, _ = self._run(log, profile="fair_perf")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Tickless", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    # --- Bonus: TIM2 not armed in after_t1_setup (round-9 sec. A3) --------

    def test_14_tim2_not_armed_fails(self):
        log = synthesize_good_log()
        # Force the after_t1_setup dump to look like the OLD bug
        # FreeRTOS port had: DIER=0, CCER=0.
        log = log.replace(
            "--- TIM2 state (after_t1_setup) ---\n"
            "  TIM2_CR1     : 0x00000000\n"
            "  TIM2_DIER    : 0x00000002\n"
            "  TIM2_CCMR1   : 0x00000078\n"
            "  TIM2_CCER    : 0x00000001\n",
            "--- TIM2 state (after_t1_setup) ---\n"
            "  TIM2_CR1     : 0x00000000\n"
            "  TIM2_DIER    : 0x00000000\n"
            "  TIM2_CCMR1   : 0x00000078\n"
            "  TIM2_CCER    : 0x00000000\n",
        )
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("TIM2", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_15_tim2_after_setup_block_missing_fails(self):
        log = synthesize_good_log()
        # Strip the entire after_t1_setup dump.
        new_lines = []
        in_block = False
        for line in log.splitlines():
            if line == "--- TIM2 state (after_t1_setup) ---":
                in_block = True
                continue
            if in_block and line == "--- end TIM2 state ---":
                in_block = False
                continue
            if in_block:
                continue
            new_lines.append(line)
        log = "\n".join(new_lines) + "\n"
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("after_t1_setup", proc.stderr)

    # --- Bonus: address placement violation (round-9 sec. A4) -------------

    def test_16_addr_nocache_fail_fails(self):
        log = synthesize_good_log()
        # One of the bench-owned objects lands in the NOCACHE region.
        log = log.replace(
            "samples_t1        : 0x2402acc8  AXI_SRAM OK",
            "samples_t1        : 0x30040100  NOCACHE FAIL",
        )
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("samples_t1", proc.stderr)
        self.assertIn("NOCACHE FAIL", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_17_addr_dtcm_warn_fails(self):
        log = synthesize_good_log()
        log = log.replace(
            "samples_t2        : 0x240200e8  AXI_SRAM OK",
            "samples_t2        : 0x20001000  DTCM WARN",
        )
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("DTCM WARN", proc.stderr)

    def test_18_addr_other_fail_fails(self):
        log = synthesize_good_log()
        log = log.replace(
            "samples_t3        : 0x24015508  AXI_SRAM OK",
            "samples_t3        : 0x70000000  OTHER FAIL",
        )
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("OTHER FAIL", proc.stderr)

    # --- Round-11 item 1 - addr range numeric check + required objects --

    def test_19_addr_status_lies_about_range_fails(self):
        # The status string says "AXI_SRAM OK" but the address is
        # actually outside AXI SRAM. The collector must catch this
        # by recomputing the range, not just trusting the string.
        log = synthesize_good_log()
        log = log.replace(
            "samples_t1        : 0x2402acc8  AXI_SRAM OK",
            "samples_t1        : 0x30040100  AXI_SRAM OK",
        )
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("outside AXI SRAM", proc.stderr)

    def test_20_required_addr_missing_fails(self):
        log = synthesize_good_log()
        # Drop the samples_t2 row entirely.
        log = "\n".join(
            line for line in log.splitlines()
            if "samples_t2 " not in line) + "\n"
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("samples_t2", proc.stderr)

    # --- Round-11 item 2 - TIM2 CR1.CEN must be 0 in setup --------------

    def test_21b_tim2_cr1_arpe_set_passes(self):
        # FreeRTOS's HAL_TIM_Base_Init sets ARPE (bit 7) -> CR1 = 0x80.
        # CEN (bit 0) is still 0, so the run is acceptable.
        log = synthesize_good_log()
        log = log.replace(
            "--- TIM2 state (after_t1_setup) ---\n"
            "  TIM2_CR1     : 0x00000000\n",
            "--- TIM2 state (after_t1_setup) ---\n"
            "  TIM2_CR1     : 0x00000080\n",
        )
        proc, _ = self._run(log)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    def test_21_tim2_cen_already_started_in_setup_fails(self):
        # Counter already running in the after_t1_setup snapshot
        # (CEN=1 means bench_t1_run already executed, which would
        # invalidate the symmetry across the 3 RTOS ports).
        log = synthesize_good_log()
        log = log.replace(
            "--- TIM2 state (after_t1_setup) ---\n"
            "  TIM2_CR1     : 0x00000000\n",
            "--- TIM2 state (after_t1_setup) ---\n"
            "  TIM2_CR1     : 0x00000001\n",
        )
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("TIM2_CR1", proc.stderr)

    # --- Round-11 item 3 - .validated.json manifest emitted on success --

    def test_22_validated_json_emitted_on_success(self):
        proc, _ = self._run(synthesize_good_log())
        self.assertEqual(proc.returncode, 0)
        manifest_path = self.tmp / "out.validated.json"
        self.assertTrue(manifest_path.is_file())
        import json as _json
        m = _json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(m["validated"])
        self.assertEqual(m["rtos"], "chibios")
        self.assertEqual(m["profile"], "fair_perf")
        self.assertEqual(m["system_clock_hz"], 480_000_000)
        self.assertEqual(m["vos_level"], "VOS0")
        self.assertEqual(m["flash_acr"], "0x00000034")
        self.assertEqual(m["n_dwt_rows"], 3 * 11000 + 100)
        self.assertEqual(m["n_t4_pi_rows"], 100)

    def test_23_validated_json_NOT_emitted_on_failure(self):
        # Truncated log (no DONE marker): no .validated.json must be
        # written, but the .stdout.txt is still archived for triage.
        log = synthesize_good_log()
        log = log.replace("=== BENCHMARK COMPLETE ===\n", "")
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(
            (self.tmp / "out.validated.json").is_file())
        self.assertTrue((self.tmp / "out.stdout.txt").is_file())

    # --- Round-12 item 3 - per-test private object coverage --------------

    def test_24_t1_private_objects_too_few_fails(self):
        # Strip t1_target_stack and t1_t_isr_entry: T1 ends up with
        # 0 tN_ private objects, below the min of 2.
        log = synthesize_good_log()
        for name in ("t1_target_stack", "t1_t_isr_entry"):
            log = "\n".join(line for line in log.splitlines()
                            if name not in line) + "\n"
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("t1_", proc.stderr)

    def test_25_t4_private_objects_too_few_fails(self):
        # Drop most t4_ objects, leave only one t4_l_stack -> 1 < min(6).
        log = synthesize_good_log()
        for name in ("t4_m_stack", "t4_h_stack", "t4_pi_mtx",
                     "t4_go_l_sem", "t4_pi_ok_array"):
            log = "\n".join(line for line in log.splitlines()
                            if name not in line) + "\n"
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("t4_", proc.stderr)

    # --- Bonus: mid-run reset (two banner blocks) ---------------------

    def test_08_mid_run_reset_fails(self):
        # Concatenate two good logs to mimic a reset mid-capture
        log = synthesize_good_log() + synthesize_good_log()
        proc, prefix = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("banner divider", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    # --- 2026-05-12 - publication mode + metric strictness ----------

    def test_26_publication_mode_required_for_fair_perf_fails(self):
        proc, _ = self._run(synthesize_good_log(),
                            publication_mode=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("publication-mode", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_27_publication_mode_required_for_realistic_tickless_fails(self):
        proc, _ = self._run(
            synthesize_good_log(profile="realistic_tickless"),
            profile="realistic_tickless",
            publication_mode=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("publication-mode", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_28_publication_mode_optional_for_debug_dev_passes(self):
        proc, _ = self._run(
            synthesize_good_log(profile="debug_dev"),
            profile="debug_dev",
            publication_mode=None)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        import json as _json
        m = _json.loads(
            (self.tmp / "out.validated.json").read_text(
                encoding="utf-8"))
        self.assertEqual(m["publication_mode"], "dwt_only")

    def test_29_autorun_in_mode_la_fair_perf_fails(self):
        log = _to_autorun(synthesize_good_log())
        proc, _ = self._run(log, publication_mode="la")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("AUTORUN", proc.stderr)
        self.assertIn("ADR-016", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_30_autorun_in_mode_dwt_only_fair_perf_passes(self):
        log = _to_autorun(synthesize_good_log())
        proc, _ = self._run(log, publication_mode="dwt_only")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    def test_31_banner_rtos_mismatch_fails(self):
        # Banner says freertos, CSV rows say chibios, CLI says
        # chibios. New banner cross-check (Codex round-2 sec. I4)
        # must catch this before any row check.
        log = synthesize_good_log()
        log = log.replace("  RTOS         : chibios",
                          "  RTOS         : freertos")
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RTOS", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_32_banner_profile_mismatch_fails(self):
        log = synthesize_good_log()
        log = log.replace("  Profile      : fair_perf",
                          "  Profile      : realistic_tickless")
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Profile", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_33_unexpected_metric_name_fails(self):
        log = synthesize_good_log()
        log = log.replace(",dwt_a4_minus_a1,",
                          ",dwt_BOGUS_NAME,")
        proc, _ = self._run(log)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("metric=", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_34_validated_json_carries_publication_mode_la(self):
        proc, _ = self._run(synthesize_good_log(),
                            publication_mode="la")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        import json as _json
        m = _json.loads(
            (self.tmp / "out.validated.json").read_text(
                encoding="utf-8"))
        self.assertEqual(m["publication_mode"], "la")


    # --- 2a (Codex round-3) - ELF / MAP SHA256 in validated.json ---

    def test_35_elf_file_required_for_fair_perf_fails(self):
        proc, _ = self._run(synthesize_good_log(),
                            elf_file=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--elf-file", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_36_map_file_required_for_fair_perf_fails(self):
        proc, _ = self._run(synthesize_good_log(),
                            map_file=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--map-file", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_37_elf_missing_file_fails(self):
        missing = str(self.tmp / "does_not_exist.elf")
        proc, _ = self._run(synthesize_good_log(),
                            elf_file=missing)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not exist", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_37b_map_missing_file_fails(self):
        missing = str(self.tmp / "does_not_exist.map")
        proc, _ = self._run(synthesize_good_log(),
                            map_file=missing)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not exist", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())

    def test_38_elf_sha256_recorded_in_manifest(self):
        proc, _ = self._run(synthesize_good_log())
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        import hashlib as _hl
        import json as _json
        elf_bytes = (self.tmp / "fake.elf").read_bytes()
        expected_elf = _hl.sha256(elf_bytes).hexdigest()
        map_bytes = (self.tmp / "fake.map").read_bytes()
        expected_map = _hl.sha256(map_bytes).hexdigest()
        m = _json.loads(
            (self.tmp / "out.validated.json").read_text(
                encoding="utf-8"))
        self.assertEqual(m["elf_sha256"], expected_elf)
        self.assertEqual(m["elf_size_bytes"], len(elf_bytes))
        self.assertEqual(m["map_sha256"], expected_map)
        self.assertEqual(m["map_size_bytes"], len(map_bytes))
        self.assertTrue((self.tmp / "out.elf").is_file())
        self.assertTrue((self.tmp / "out.map").is_file())

    def test_39_elf_map_optional_for_debug_dev_passes(self):
        proc, _ = self._run(
            synthesize_good_log(profile="debug_dev"),
            profile="debug_dev",
            publication_mode=None,
            elf_file=None,
            map_file=None)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        import json as _json
        m = _json.loads(
            (self.tmp / "out.validated.json").read_text(
                encoding="utf-8"))
        # debug_dev may omit the hashes; if provided they would
        # still be recorded, but with elf_file=None we expect
        # them to be absent.
        self.assertNotIn("elf_sha256", m)
        self.assertNotIn("map_sha256", m)

    def test_40_elf_required_for_realistic_tickless_fails(self):
        proc, _ = self._run(
            synthesize_good_log(profile="realistic_tickless"),
            profile="realistic_tickless",
            elf_file=None)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--elf-file", proc.stderr)
        self.assertFalse((self.tmp / "out.csv").is_file())


def _to_autorun(log: str) -> str:
    """Replace the READY/START marker pairs emitted by the
    synthetic firmware log with AUTORUN markers, as the firmware
    would do under BENCH_AUTORUN=1 (ADR-016)."""
    out: list[str] = []
    for line in log.splitlines():
        if line.startswith("=== READY "):
            continue
        if line.startswith("=== START "):
            out.append(line.replace("=== START ",
                                    "=== AUTORUN "))
            continue
        out.append(line)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    unittest.main(verbosity=2)
