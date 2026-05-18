#!/usr/bin/env python3
"""
Validation suite for scripts/analyze_results.py (round-8 §5/§6 +
round-9 §A7).

Self-contained: every fixture (CSV + stdout.txt with synthetic
"=== Stats for ... ===" blocks) is generated programmatically inside
a temp directory. No dependency on real captured `results/raw/*`
files, so the suite is CI-friendly.

Cases:
    1. Synthetic dataset with consistent firmware/Python stats
       -> exit 0, "OK: firmware stats match"
    2. Stats-block tampered (median bumped by +5 cycles)
       -> exit != 0, FAIL on hard-match field
    3. CSV tampered (one valid sample doubled)
       -> exit != 0
    4. Stats block missing for one test
       -> exit != 0

Run:
    python -m unittest tests.test_analyze_results -v
or:
    python tests/test_analyze_results.py
"""

import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT    = REPO_ROOT / "scripts" / "analyze_results.py"
SYS_CLOCK = 480_000_000


# === Synthetic dataset generators =====================================

# Map test_name -> (metric, valid count, value generator(i))
# Iteration index is 1-based to match firmware behaviour.
DATASETS = {
    "t1_irq":        ("dwt_a4_minus_a1",
                      10000, lambda i: 200 + (i % 10)),
    "t2_handoff":    ("dwt_thread_to_thread",
                      10000, lambda i: 200 + (i % 10)),
    "t3_mtx_uncont": ("dwt_lock_unlock_pair",
                      10000, lambda i: 200 + (i % 10)),
    "t4_mtx_pi":     ("dwt_low_unlock_to_high_acquire",
                      100,   lambda i: 250 + i),
}
WARMUP_DATASETS = {
    # Warmup is 1000 rows for T1/T2/T3, none for T4.
    "t1_irq":        1000,
    "t2_handoff":    1000,
    "t3_mtx_uncont": 1000,
}


def _us(cycles: int) -> str:
    return f"{cycles * 1_000_000.0 / SYS_CLOCK:.6f}"


def firmware_stats(values: list[int]) -> dict[str, int]:
    """Replicate `bench_compute_stats` exactly. Used to generate
    the firmware-emitted `=== Stats for ... ===` blocks so they
    are guaranteed consistent with the synthetic CSV."""
    n      = len(values)
    sv     = sorted(values)
    sum_v  = sum(values)
    mean   = sum_v // n
    sq_sum = sum((v - mean) ** 2 for v in values)
    var    = sq_sum // n
    return {
        "n":      n,
        "min":    sv[0],
        "max":    sv[-1],
        "mean":   mean,
        "median": sv[n // 2],
        "p95":    sv[(n * 95) // 100],
        "p99":    sv[(n * 99) // 100],
        "jitter": sv[-1] - sv[0],
        "stddev": int(math.sqrt(var)),
    }


def stats_block(test: str, rtos: str, profile: str,
                stats: dict[str, int]) -> str:
    """Format the same way the firmware does (see
    benchmark_stats.c::bench_print_stats)."""
    lines = [f"=== Stats for {test} ({rtos}, {profile}) ==="]
    lines.append(f"  n         : {stats['n']}")
    for label, key in (("min       ", "min"),
                       ("median    ", "median"),
                       ("mean      ", "mean"),
                       ("p95       ", "p95"),
                       ("p99       ", "p99"),
                       ("max       ", "max"),
                       ("jitter    ", "jitter")):
        cycles = stats[key]
        lines.append(f"  {label}: {cycles} cycles ({_us(cycles)} us)")
    lines.append(f"  stddev    : {stats['stddev']} cycles")
    return "\n".join(lines)


def write_fixture(prefix: Path,
                  rtos: str = "chibios",
                  profile: str = "fair_perf",
                  *,
                  tamper_stats: dict[str, dict[str, int]] | None = None,
                  tamper_csv: dict[str, dict[int, int]] | None = None,
                  drop_stats_for: set[str] | None = None) -> None:
    """Write `<prefix>.csv` and `<prefix>.stdout.txt`.

    `tamper_stats[test_name][field] = delta` applies an offset to a
    given stats block before writing it (used to force a hard-match
    failure). `tamper_csv[test_name][iteration] = new_cycles` forces
    a single CSV sample to a different value (used to force the
    Python re-compute to disagree with the unchanged firmware
    block). `drop_stats_for` lists tests whose stats block must be
    omitted from the log (used to test "missing block" path)."""
    drop_stats_for = drop_stats_for or set()

    csv_path  = prefix.parent / (prefix.name + ".csv")
    log_path  = prefix.parent / (prefix.name + ".stdout.txt")

    csv_lines = ["rtos,profile,test_name,metric,phase,iteration,"
                 "cycles,microseconds"]
    log_lines = ["=== synthetic fixture =="]   # any preamble

    for test, (metric, n_valid, gen) in DATASETS.items():
        # -- warmup rows (T1/T2/T3 only) --
        n_warm = WARMUP_DATASETS.get(test, 0)
        for i in range(1, n_warm + 1):
            c = 100 + (i % 10)
            csv_lines.append(f"{rtos},{profile},{test},{metric},"
                             f"warmup,{i},{c},{_us(c)}")

        # -- valid rows --
        valid_cycles: list[int] = []
        for i in range(1, n_valid + 1):
            c = gen(i)
            override = (tamper_csv or {}).get(test, {}).get(i)
            if override is not None:
                c = override
            valid_cycles.append(c)
            csv_lines.append(f"{rtos},{profile},{test},{metric},"
                             f"valid,{i},{c},{_us(c)}")

        # -- stats block (taking the UN-TAMPERED CSV values, so the
        # baseline path is consistent; tamper_csv is meant to make
        # the Python re-compute differ from the firmware block, and
        # tamper_stats is meant to make the firmware block differ
        # from the un-tampered CSV) --
        clean_cycles = [gen(i) for i in range(1, n_valid + 1)]
        st = firmware_stats(clean_cycles)
        if tamper_stats and test in tamper_stats:
            for field, delta in tamper_stats[test].items():
                st[field] += delta
        if test not in drop_stats_for:
            log_lines.append(stats_block(test, rtos, profile, st))

    csv_path.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")


# === Test harness =====================================================

class AnalyzeResultsTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp  = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, prefix: Path) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(prefix)],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )

    def test_01_consistent_fixture_passes(self):
        prefix = self.tmp / "out"
        write_fixture(prefix)
        proc = self._run(prefix)
        self.assertEqual(proc.returncode, 0,
                         f"stdout:\n{proc.stdout}\n"
                         f"stderr:\n{proc.stderr}")
        self.assertIn("OK: firmware stats match", proc.stdout)

    def test_02_stats_block_tampered_fails(self):
        # Bump the firmware-reported median for t1 by +5; the
        # CSV is unchanged so the Python re-compute will disagree.
        prefix = self.tmp / "out"
        write_fixture(prefix,
                      tamper_stats={"t1_irq": {"median": 5}})
        proc = self._run(prefix)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("FAIL", proc.stdout + proc.stderr)
        self.assertIn("median", proc.stdout + proc.stderr)

    def test_03_csv_sample_tampered_fails(self):
        # Replace one t1 valid sample at iter=42 with a huge spike.
        # The firmware stats block was computed on the un-tampered
        # CSV, so the Python re-compute (which sees the spike) will
        # give a different max / jitter / p99.
        prefix = self.tmp / "out"
        write_fixture(prefix,
                      tamper_csv={"t1_irq": {42: 99999}})
        proc = self._run(prefix)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("FAIL", proc.stdout + proc.stderr)

    def test_04_missing_stats_block_fails(self):
        prefix = self.tmp / "out"
        write_fixture(prefix, drop_stats_for={"t3_mtx_uncont"})
        proc = self._run(prefix)
        self.assertNotEqual(proc.returncode, 0)
        # analyze_results.py reports the missing test name on stderr
        self.assertIn("t3_mtx_uncont", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
