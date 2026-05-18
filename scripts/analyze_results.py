#!/usr/bin/env python3
"""
analyze_results.py — offline cross-check of firmware-emitted stats
against a re-computation from the captured CSV samples.

Round-8 Item 6 (discuss.txt v2 §5).

Reads:
    <prefix>.csv         the validated DWT samples (8-col CSV)
    <prefix>.stdout.txt  the raw log, which contains the firmware
                         "=== Stats for <test> (<rtos>, <profile>) ==="
                         blocks, one per test

For each test (t1_irq, t2_handoff, t3_mtx_uncont, t4_mtx_pi):

    1. Extract the firmware's reported stats from the log block.
    2. Re-compute stats offline from the CSV samples (phase=valid)
       using the EXACT same formula the firmware uses (sorted-index
       percentile, no interpolation; integer-truncated mean and
       stddev to match the firmware's `(uint32_t)` casts; see
       ADR-013).
    3. Compare. Mismatch on n / min / max / jitter / median /
       p95 / p99  =>  FAIL (script exits non-zero).
       Mismatch on mean / stddev within +/-1 cycle is tolerated
       (different rounding paths between qsort + integer divisions
       on target vs CPython on host can produce a 1-cycle
       difference; round-8 §5 explicitly allows this).

Exit codes:
    0  all stats match within tolerance
    1  one or more mismatches (FAIL)
    2  bad inputs / missing files

Usage:
    python analyze_results.py results/raw/chibios_fair_perf_run01

The argument is the same prefix used by collect_results.py.
The script appends `.csv` and `.stdout.txt` to it.
"""

import argparse
import math
import re
import sys
from pathlib import Path
from typing import Optional


# === Constants ========================================================

EXPECTED_TESTS = ("t1_irq", "t2_handoff", "t3_mtx_uncont", "t4_mtx_pi")
MEAN_TOLERANCE_CYCLES   = 1   # firmware integer truncation
STDDEV_TOLERANCE_CYCLES = 1   # firmware sqrt -> uint32 cast


# === Log parsing ======================================================

# Header of a stats block:
#   === Stats for <test> (<rtos>, <profile>) ===
STATS_HEADER_RE = re.compile(
    r"^=== Stats for (\w+) \((chibios|freertos|zephyr), "
    r"(fair_perf|realistic_tickless|debug_dev)\) ===$"
)

# Body lines, e.g. "  min       : 282 cycles (0.588 us)"
# stddev line has no us part: "  stddev    : 8 cycles"
STATS_FIELD_RE = re.compile(
    r"^\s*(\w+)\s*:\s*(\d+)\s+cycles(?:\s*\([\d.]+\s*us\))?\s*$"
)
STATS_N_RE = re.compile(r"^\s*n\s*:\s*(\d+)\s*$")


def parse_firmware_stats(log_path: Path) -> dict:
    """Return {test_name: {field: int}} for every stats block in the log."""
    blocks: dict[str, dict[str, int]] = {}
    current: Optional[str] = None
    expected_fields = {"n", "min", "median", "mean", "p95", "p99",
                       "max", "jitter", "stddev"}

    with log_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = STATS_HEADER_RE.match(line)
            if m:
                current = m.group(1)
                blocks[current] = {}
                continue
            if current is None:
                continue
            m = STATS_N_RE.match(line)
            if m:
                blocks[current]["n"] = int(m.group(1))
                continue
            m = STATS_FIELD_RE.match(line)
            if m:
                field = m.group(1)
                if field == "n":
                    continue   # already handled
                blocks[current][field] = int(m.group(2))
                # End of a block when we have all 9 fields
                if expected_fields.issubset(blocks[current].keys()):
                    current = None

    return blocks


# === CSV loading ======================================================

CSV_VALID_RE = re.compile(
    r"^(chibios|freertos|zephyr),"
    r"(fair_perf|realistic_tickless|debug_dev),"
    r"(\w+),"
    r"\w+,"                # metric (ignored here)
    r"valid,"              # only valid rows
    r"\d+,"                # iteration
    r"(\d+),"              # cycles
    r"[\d.]+$"             # us (ignored, validated by collect_results)
)


def load_valid_samples(csv_path: Path) -> dict[str, list[int]]:
    """{test_name: [cycles, ...]} for phase=valid rows only."""
    out: dict[str, list[int]] = {}
    with csv_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = CSV_VALID_RE.match(line)
            if not m:
                continue
            test_name = m.group(3)
            cycles    = int(m.group(4))
            out.setdefault(test_name, []).append(cycles)
    return out


# === Recompute (firmware-equivalent) ==================================

def percentile_by_index(sorted_values: list[int], pct: int) -> int:
    """sorted-index percentile, no interpolation. ADR-013."""
    n = len(sorted_values)
    return sorted_values[(n * pct) // 100]


def recompute_stats(values: list[int]) -> dict[str, int]:
    """Replicate bench_compute_stats() exactly: integer mean (truncated),
    integer stddev (sqrt then truncate), sorted-index percentiles."""
    n = len(values)
    if n == 0:
        return {}
    sv     = sorted(values)
    min_v  = sv[0]
    max_v  = sv[-1]
    jitter = max_v - min_v
    sum_v  = sum(values)
    mean   = sum_v // n                        # firmware: (uint32_t)(sum/n)
    sq_sum = sum((v - mean) ** 2 for v in values)
    variance = sq_sum // n                     # firmware: sq_sum / n (int)
    stddev = int(math.sqrt(variance))          # firmware: (uint32_t)sqrtf(...)
    median = sv[n // 2]
    p95    = percentile_by_index(sv, 95)
    p99    = percentile_by_index(sv, 99)
    return {
        "n":      n,
        "min":    min_v,
        "max":    max_v,
        "jitter": jitter,
        "mean":   mean,
        "stddev": stddev,
        "median": median,
        "p95":    p95,
        "p99":    p99,
    }


# === Comparison =======================================================

# Hard-match fields: any cycle delta is a FAIL.
HARD_FIELDS = ("n", "min", "max", "jitter", "median", "p95", "p99")
# Soft-match fields: integer rounding may diverge by 1 cycle.
SOFT_FIELDS = ("mean", "stddev")
SOFT_TOL    = {"mean": MEAN_TOLERANCE_CYCLES,
               "stddev": STDDEV_TOLERANCE_CYCLES}


def compare(test_name: str, fw: dict[str, int],
            host: dict[str, int]) -> int:
    """Return number of mismatches; print one line per field."""
    mismatches = 0
    print(f"\n--- {test_name} ---")
    print(f"{'field':10s}  {'firmware':>10s}  {'recomputed':>10s}  "
          f"{'delta':>7s}  result")

    fields = HARD_FIELDS + SOFT_FIELDS
    for field in fields:
        if field not in fw:
            print(f"{field:10s}  {'(missing)':>10s}  "
                  f"{host.get(field, 0):>10d}  "
                  f"{'-':>7s}  FAIL (firmware did not emit)")
            mismatches += 1
            continue
        fw_v   = fw[field]
        host_v = host[field]
        delta  = host_v - fw_v
        if field in HARD_FIELDS:
            ok = (delta == 0)
            tag = "OK" if ok else "FAIL"
        else:
            tol = SOFT_TOL[field]
            ok  = (abs(delta) <= tol)
            tag = "OK" if ok else f"FAIL (tol +/- {tol})"
        if not ok:
            mismatches += 1
        print(f"{field:10s}  {fw_v:>10d}  {host_v:>10d}  "
              f"{delta:>+7d}  {tag}")

    return mismatches


# === Main =============================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Cross-check firmware stats vs Python re-compute "
                    "(round-8 Item 6)."
    )
    p.add_argument("prefix",
                   help="Output prefix used by collect_results.py "
                        "(the script appends .csv and .stdout.txt).")
    args = p.parse_args(argv)

    prefix    = Path(args.prefix)
    csv_path  = prefix.parent / (prefix.name + ".csv")
    log_path  = prefix.parent / (prefix.name + ".stdout.txt")

    if not csv_path.is_file():
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 2
    if not log_path.is_file():
        print(f"ERROR: stdout log not found: {log_path}", file=sys.stderr)
        return 2

    print(f"CSV  : {csv_path}")
    print(f"Log  : {log_path}")

    fw_blocks = parse_firmware_stats(log_path)
    samples   = load_valid_samples(csv_path)

    missing_in_log = [t for t in EXPECTED_TESTS if t not in fw_blocks]
    missing_in_csv = [t for t in EXPECTED_TESTS if t not in samples]
    if missing_in_log:
        print(f"FAIL: tests missing from log block: {missing_in_log}",
              file=sys.stderr)
    if missing_in_csv:
        print(f"FAIL: tests missing from CSV       : {missing_in_csv}",
              file=sys.stderr)
    if missing_in_log or missing_in_csv:
        return 1

    total_mismatches = 0
    for test_name in EXPECTED_TESTS:
        host_stats = recompute_stats(samples[test_name])
        total_mismatches += compare(test_name,
                                    fw_blocks[test_name],
                                    host_stats)

    print()
    if total_mismatches == 0:
        print(f"OK: firmware stats match recomputed stats on all "
              f"{len(EXPECTED_TESTS)} tests "
              f"(hard-match for {','.join(HARD_FIELDS)}, "
              f"+/-{MEAN_TOLERANCE_CYCLES} cycle for "
              f"{','.join(SOFT_FIELDS)}).")
        return 0
    else:
        print(f"FAIL: {total_mismatches} mismatch(es) — see lines above.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
