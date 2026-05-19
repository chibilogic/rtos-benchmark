#!/usr/bin/env python3
"""
collect_results.py - fail-stop benchmark log collector.

Reads the benchmark output stream from the board's ST-Link VCP
(USART3) - or from a captured raw log file via --from-log - and
produces:

    <output_prefix>.csv          DWT CSV rows (T1..T4)
    <output_prefix>.t4_pi.csv    TEST 4 PI per-run pass/fail
    <output_prefix>.banner.txt   boot banner + TIM2 state dumps
    <output_prefix>.stdout.txt   complete raw log (always written,
                                 even on validation failure, for
                                 diagnostics)

Acceptance criteria (round-8 reviewer roadmap, discuss.txt v2):
  - exactly one boot banner block (== divider lines = 2)
  - CSV header (8 columns) present
  - BENCHMARK COMPLETE present
  - SystemClock line present in banner; matches expected 480 MHz
  - all DWT / T4-PI rows have rtos / profile matching the CLI args
  - if profile is fair_perf or realistic_tickless: NO debug_dev row
  - T1, T2, T3:    1000 warmup rows + 10000 valid rows each
  - T4_mtx_pi:     100 valid rows + 100 PI rows
  - cycles > 0
  - microseconds == cycles * 1_000_000 / system_clock_hz (tolerance
    US_TOLERANCE = 1e-3, accounts for firmware printf rounding)

ANY failure -> exit with non-zero status. The .csv / .t4_pi.csv /
.banner.txt outputs are NOT written on failure (the .stdout.txt
raw log IS still written for post-mortem).

CLI:
    python collect_results.py \
        --port COM6 --rtos chibios --profile fair_perf \
        --run-id 01 --output results/raw/chibios_fair_perf_run01

    python collect_results.py \
        --from-log results/raw/run.txt --rtos chibios \
        --profile fair_perf --run-id 99 \
        --output results/raw/replay_run01

The --output is a *prefix*; the script appends the suffixes above.
If --output is omitted the prefix defaults to
"results/raw/<rtos>_<profile>_run<run-id>".
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Iterator, Optional


# === Acceptance constants =============================================

EXPECTED_SYSTEM_CLOCK_HZ = 480_000_000
EXPECTED_WARMUP_PER_TEST = 1000        # T1, T2, T3 only
EXPECTED_VALID_PER_TEST  = 10000       # T1, T2, T3 only
EXPECTED_T4_VALID        = 100         # T4 has no warmup
EXPECTED_T4_PI           = 100         # PI summary rows

# AXI SRAM range on STM32H750. Round-11 item 1: the collector recomputes
# the range against the printed address; trusting only the firmware's
# status string would let through a bug where a benchmark-owned object
# accidentally lands outside AXI SRAM but the firmware mislabels it.
AXI_SRAM_START = 0x24000000
AXI_SRAM_END   = 0x24080000

# Names that MUST appear in the memory placement table for the run
# to be acceptable (round-11 sec. 1).
REQUIRED_ADDR_NAMES = {
    "samples_t1", "samples_t2", "samples_t3", "samples_t4",
}

# Round-12 item 3 - beyond the four sample buffers, we also require that
# at least N benchmark-owned objects per test are audited (test
# private stacks / sync objects / mutexes). Naming differs per RTOS
# (e.g. `t1_wa_target` on ChibiOS, `t1_thread_stack` on Zephyr,
# `t1_target_tcb` on FreeRTOS), so the contract is on the **prefix**
# `tN_` and a minimum count rather than on specific names.
#
# These minima are the strict lower bounds derived from the per-RTOS
# `bench_t<N>_print_addresses` implementations in the 3 ports:
#   T1: stack/wa  + at least one sync object   -> 2
#   T2: stack/wa  + at least one sync object   -> 2
#   T3: just the mutex object                  -> 1
#   T4: 3 thread stacks/data + the contended mutex
#       + at least one go-sem + the pi_ok array -> 6
#
# `samples_tN` is NOT counted here (it has its own check above).
REQUIRED_TEST_PREFIX_MIN = {
    "t1": 2,
    "t2": 2,
    "t3": 1,
    "t4": 6,
}

# Expected metric label per test_name in the DWT CSV (Codex
# round-2 sec. I2 + ADR-015 patched 2026-05-12). The firmware always
# emits DWT measurements; the LA metric (la_a4_minus_a0_hw) is
# never present in the CSV stream - it is carried by a separate
# logic-analyzer capture. A mismatch here means the firmware
# build is incompatible with ADR-014/ADR-015.
EXPECTED_METRIC_BY_TEST = {
    "t1_irq":        "dwt_a4_minus_a1",
    "t2_handoff":    "dwt_thread_to_thread",
    "t3_mtx_uncont": "dwt_lock_unlock_pair",
    "t4_mtx_pi":     "dwt_low_unlock_to_high_acquire",
}

# Publication modes (ADR-015 patched 2026-05-12).
PUBLICATION_MODES = ("la", "dwt_only")

# Profiles that require an explicit --publication-mode at CLI
# time (ADR-016 patched 2026-05-12). debug_dev defaults to
# "dwt_only".
PUBLISHABLE_PROFILES = {"fair_perf", "realistic_tickless"}

# Firmware prints us with 6 decimal digits via integer math
# (cycles * 1e6 / 480e6); 1e-3 absolutely covers that rounding.
US_TOLERANCE = 1e-3


# === Stream tokens ====================================================

DONE_MARKER       = "BENCHMARK COMPLETE"
BANNER_DIVIDER_RE = re.compile(r"^={10,}$")        # >=10 '=' = banner

# Generic banner field "  KEY ...  : VALUE". The KEY can contain
# spaces / arrows ("WFI in idle", "T1/T2/T3 wm"); the value can be
# anything. We trim whitespace later. Used during the first banner
# block to populate banner_fields.
BANNER_FIELD_RE = re.compile(r"^\s+(\S[^:]*?)\s*:\s*(.+?)\s*$")

# TIM2 state-dump bracketing.
TIM2_BLOCK_BEGIN_RE = re.compile(r"^---\s*TIM2 state \((\w+)\)\s*---\s*$")
TIM2_BLOCK_END_RE   = re.compile(r"^---\s*end TIM2 state\s*---\s*$")

# ADR-017 memory placement bracketing.
ADDR_BLOCK_BEGIN    = "--- Benchmark memory placement (ADR-017) ---"
ADDR_BLOCK_END      = "--- end memory placement ---"
# "  bench_addr  <name>           : 0x<hex>  <STATUS-with-spaces>"
ADDR_ROW_RE = re.compile(
    r"^\s*bench_addr\s+(\S+)\s*:\s*0x([0-9a-fA-F]+)\s+(.+?)\s*$"
)

DWT_HEADER = ("rtos,profile,test_name,metric,phase,iteration,"
              "cycles,microseconds")
DWT_ROW_RE = re.compile(
    r"^(chibios|freertos|zephyr),"
    r"(fair_perf|realistic_tickless|debug_dev),"
    r"(\w+),"
    r"(\w+),"
    r"(warmup|valid),"
    r"(\d+),"
    r"(\d+),"
    r"([\d.]+)$"
)
T4_PI_ROW_RE = re.compile(
    r"^(chibios|freertos|zephyr),"
    r"(fair_perf|realistic_tickless|debug_dev),"
    r"(t4_mtx_pi),"
    r"(\d+),"
    r"([01])$"
)

READY_RE   = re.compile(r"^=== READY (\w+) ===$")
START_RE   = re.compile(r"^=== START (\w+) ===$")
AUTORUN_RE = re.compile(r"^=== AUTORUN (\w+) ===$")


# === Helpers ==========================================================

def _sha256_and_size(path: Path) -> tuple[str, int]:
    """Return (sha256_hex_lowercase, size_bytes) of the file at
    @p path. Reads the file in 64 KiB chunks so even a 100 MB ELF
    does not blow up the process. Raises OSError on read failure."""
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def fail(msg: str) -> None:
    """Print a FAIL line and exit non-zero. Caller should not return."""
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def iter_serial(port: str, baud: int, idle_timeout_s: float,
                done_grace_s: float = 5.0) -> Iterator[str]:
    """Yield decoded lines from the board UART. Closes when no data
    has arrived for idle_timeout_s, or done_grace_s seconds after
    the BENCHMARK COMPLETE marker has been seen."""
    try:
        import serial
    except ImportError:
        fail("pyserial not installed. Run: pip install pyserial")

    last = time.time()
    saw_done = False
    with serial.Serial(port, baud, timeout=1) as ser:
        # Lab-session bug fix 2026-05-14 (P48): drain any
        # bytes that were already in the ST-Link VCP receive
        # buffer when the port was opened. Without this, a
        # truncated line from a previous firmware run (e.g.
        # the operator manually reset the board between
        # campaigns, or a previous collector died mid-line)
        # is read as part of the new run and fails the
        # us-vs-cycles consistency check. A small sleep
        # lets any in-flight USB packets land before we
        # flush.
        time.sleep(0.05)
        ser.reset_input_buffer()
        while True:
            raw = ser.readline()
            if not raw:
                budget = done_grace_s if saw_done else idle_timeout_s
                if (time.time() - last) > budget:
                    return
                continue
            line = raw.decode("utf-8", errors="ignore").rstrip("\r\n")
            last = time.time()
            if DONE_MARKER in line:
                saw_done = True
            yield line


def iter_log_file(path: Path) -> Iterator[str]:
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            yield raw.rstrip("\r\n")


def echo(it: Iterator[str]) -> Iterator[str]:
    """Mirror lines to stdout (line-buffered) as we consume them."""
    for line in it:
        print(line, flush=True)
        yield line


def passthrough(it: Iterator[str]) -> Iterator[str]:
    """No-op consumer used in --quiet mode (no live mirror)."""
    for line in it:
        yield line


# === Pipeline =========================================================

def collect(lines: Iterator[str]) -> dict:
    """Consume the line stream once, classify into raw / banner /
    dwt / t4pi / TIM2 state / address table. Does NOT validate;
    that is validate()'s job."""
    raw          : list[str]              = []
    banner       : list[str]              = []
    dwt_rows     : list[tuple]            = []
    t4pi_rows    : list[tuple]            = []
    test_markers : list[tuple[str, str]]  = []
    banner_fields: dict[str, str]         = {}
    tim2_blocks  : dict[str, dict[str, str]] = {}   # tag -> {reg: hex}
    addr_rows    : list[tuple[str, str, str]] = [] # (name, hex, status)
    in_banner          = False
    banner_dividers    = 0    # count of ==...== divider lines
    saw_done           = False
    saw_header         = False
    in_tim2_tag        : Optional[str] = None
    in_addr_block      = False

    for line in lines:
        raw.append(line)

        # Banner block: divider toggles in_banner state
        if BANNER_DIVIDER_RE.match(line):
            banner_dividers += 1
            in_banner = not in_banner
            banner.append(line)
            continue

        if in_banner:
            banner.append(line)
            m = BANNER_FIELD_RE.match(line)
            if m:
                key, val = m.group(1).strip(), m.group(2).strip()
                banner_fields[key] = val
            continue

        # TIM2 state dump bracketing.
        m = TIM2_BLOCK_BEGIN_RE.match(line)
        if m:
            in_tim2_tag = m.group(1)
            tim2_blocks.setdefault(in_tim2_tag, {})
            banner.append(line)
            continue
        if TIM2_BLOCK_END_RE.match(line):
            in_tim2_tag = None
            banner.append(line)
            continue
        if in_tim2_tag is not None:
            banner.append(line)
            m = BANNER_FIELD_RE.match(line)
            if m:
                key, val = m.group(1).strip(), m.group(2).strip()
                tim2_blocks[in_tim2_tag][key] = val
            continue

        # Memory placement table bracketing.
        if line == ADDR_BLOCK_BEGIN:
            in_addr_block = True
            banner.append(line)
            continue
        if line == ADDR_BLOCK_END:
            in_addr_block = False
            banner.append(line)
            continue
        if in_addr_block:
            banner.append(line)
            m = ADDR_ROW_RE.match(line)
            if m:
                addr_rows.append((m.group(1), m.group(2), m.group(3)))
            continue

        # T4 PI passed summary line is part of the run manifest.
        if line.startswith("  PI passed"):
            banner.append(line)
            continue

        if line == DWT_HEADER:
            saw_header = True
            continue

        if DONE_MARKER in line:
            saw_done = True
            continue

        m = READY_RE.match(line)
        if m:
            test_markers.append(("READY", m.group(1)))
            continue
        m = START_RE.match(line)
        if m:
            test_markers.append(("START", m.group(1)))
            continue
        m = AUTORUN_RE.match(line)
        if m:
            test_markers.append(("AUTORUN", m.group(1)))
            continue

        m = DWT_ROW_RE.match(line)
        if m:
            dwt_rows.append(m.groups())
            continue

        m = T4_PI_ROW_RE.match(line)
        if m:
            t4pi_rows.append(m.groups())
            continue

    # Convenience: extract SystemClock as int if present.
    system_clock_hz: Optional[int] = None
    sc = banner_fields.get("SystemClock")
    if sc:
        m = re.match(r"^(\d+)\s*Hz?\s*$", sc)
        if m:
            system_clock_hz = int(m.group(1))

    return {
        "raw":             raw,
        "banner":          banner,
        "dwt_rows":        dwt_rows,
        "t4pi_rows":       t4pi_rows,
        "banner_dividers": banner_dividers,
        "saw_done":        saw_done,
        "saw_header":      saw_header,
        "test_markers":    test_markers,
        "system_clock_hz": system_clock_hz,
        "banner_fields":   banner_fields,
        "tim2_blocks":     tim2_blocks,
        "addr_rows":       addr_rows,
    }


def validate(agg: dict, args) -> None:
    """Run all acceptance checks. Calls fail() on the first violation."""
    if agg["banner_dividers"] != 2:
        fail(f"expected exactly 2 banner divider lines (= 1 boot), "
             f"found {agg['banner_dividers']} (mid-run reset?)")
    if not agg["saw_header"]:
        fail("CSV header line not present in stream")
    if not agg["saw_done"]:
        fail(f"'{DONE_MARKER}' marker never seen - log truncated")
    if agg["system_clock_hz"] is None:
        fail("SystemClock line not present in banner")
    if agg["system_clock_hz"] != EXPECTED_SYSTEM_CLOCK_HZ:
        fail(f"SystemClock={agg['system_clock_hz']} Hz, expected "
             f"{EXPECTED_SYSTEM_CLOCK_HZ} Hz")

    # A2 - banner hardware manifest (round-9 sec. 2).
    bf = agg["banner_fields"]
    def _need(key: str, want: str) -> None:
        got = bf.get(key)
        if got is None:
            fail(f"banner missing required field '{key}'")
        if got != want:
            fail(f"banner '{key}' = {got!r}, expected {want!r}")

    _need("VOS level",  "VOS0")
    _need("VOSRDY",     "READY")
    _need("FLASH_ACR",  "0x00000034")
    _need("ICache",     "ON")
    _need("DCache",     "ON")
    _need("Tick rate",  "1000 Hz")

    # Codex round-2 sec. I4: banner RTOS / Profile must match the CLI
    # args. CSV rows are already cross-checked below, but a banner
    # that disagrees with the CLI args means the firmware build was
    # configured for a different (rtos, profile) tuple than the one
    # the operator is recording. validated.json would otherwise
    # silently record the CLI side.
    _need("RTOS",       args.rtos)
    _need("Profile",    args.profile)

    # Profile-conditional fields.
    if args.profile == "fair_perf":
        _need("Tickless",    "OFF")
        _need("WFI in idle", "OFF")
        _need("Optimization", "-O2  LTO=no")
    elif args.profile == "realistic_tickless":
        _need("Tickless",    "ON")
        _need("WFI in idle", "ON")
        _need("Optimization", "-O2  LTO=no")
    # debug_dev: any optimization is allowed; no banner gate here.

    # A3 - TIM2 after_t1_setup must show TIM2 armed (round-9 sec. 3).
    tim2 = agg["tim2_blocks"].get("after_t1_setup")
    if tim2 is None:
        fail("TIM2 state dump 'after_t1_setup' missing from log")
    # Round-11 item 2: TIM2 must be ARMED but NOT STARTED in the
    # `after_t1_setup` snapshot. The setup phase configures the
    # OC channel, enables CCxE and the CC1 interrupt, but leaves
    # CR1.CEN=0; bench_t1_run is the only place CR1.CEN goes to 1.
    # CCMR1 must encode PWM mode 2 + OC1PE (= 0x78).
    expected_tim2 = {
        "TIM2_DIER":  "0x00000002",   # CC1IE = 1
        "TIM2_CCMR1": "0x00000078",   # OC1M = PWM2, OC1PE = 1
        "TIM2_CCER":  "0x00000001",   # CC1E = 1
        "TIM2_PSC":   "0x000000ef",
        "TIM2_ARR":   "0x000003e7",
        "TIM2_CCR1":  "0x00000001",
    }
    for reg, want in expected_tim2.items():
        got = tim2.get(reg)
        if got is None:
            fail(f"TIM2 after_t1_setup: missing register {reg}")
        if got != want:
            fail(f"TIM2 after_t1_setup: {reg}={got}, expected {want}")

    # CR1 is special: the only invariant is CR1.CEN (bit 0) == 0,
    # i.e. counter armed but not yet running. Other CR1 bits depend
    # on how the per-RTOS HAL initialises the timer:
    #   - ChibiOS / Zephyr register-direct setup leave CR1 = 0x00.
    #   - FreeRTOS HAL_TIM_Base_Init sets ARPE (bit 7) -> CR1 = 0x80.
    # Both are valid as long as CEN is 0; bench_t1_run is the only
    # place CEN should ever be set.
    cr1_str = tim2.get("TIM2_CR1")
    if cr1_str is None:
        fail("TIM2 after_t1_setup: missing register TIM2_CR1")
    try:
        cr1_val = int(cr1_str, 16)
    except ValueError:
        fail(f"TIM2 after_t1_setup: TIM2_CR1={cr1_str!r} is not hex")
    if cr1_val & 0x1:
        fail(f"TIM2 after_t1_setup: TIM2_CR1={cr1_str} has CEN=1 "
             f"(counter already running). The setup snapshot must "
             f"show CEN=0; bench_t1_run is the only place that "
             f"sets CEN.")

    # A4 / round-11 sec. 1 - memory placement audit.
    # Two layers of check:
    #   (a) the firmware's printed status string is "AXI_SRAM OK";
    #   (b) the address that the firmware actually printed falls in
    #       [AXI_SRAM_START, AXI_SRAM_END). This protects against a
    #       firmware bug where the status string is wrong (e.g. a
    #       missed branch in bench_print_addr() classification) but
    #       the address itself is outside AXI SRAM.
    seen_names: set[str] = set()
    for name, addr_hex, status in agg["addr_rows"]:
        if status == "INFO":
            continue
        seen_names.add(name)
        if status != "AXI_SRAM OK":
            fail(f"memory placement: bench_addr {name} @ 0x{addr_hex} "
                 f"is '{status}' (must be 'AXI_SRAM OK' for "
                 f"benchmark-owned objects, ADR-017)")
        try:
            addr_int = int(addr_hex, 16)
        except ValueError:
            fail(f"memory placement: bench_addr {name} has unparsable "
                 f"address 0x{addr_hex}")
        if not (AXI_SRAM_START <= addr_int < AXI_SRAM_END):
            fail(f"memory placement: bench_addr {name} @ 0x{addr_hex} "
                 f"falls outside AXI SRAM "
                 f"[0x{AXI_SRAM_START:08x}, 0x{AXI_SRAM_END:08x}); "
                 f"firmware status '{status}' is therefore wrong")

    # Required objects must all be in the dump.
    missing = REQUIRED_ADDR_NAMES - seen_names
    if missing:
        fail(f"memory placement: required bench_addr rows missing "
             f"from log: {sorted(missing)} "
             f"(every benchmark-owned sample buffer must be audited)")

    # Round-12 item 3 - per-test prefix coverage. Every test must show
    # AT LEAST `min_count` private objects (excluding samples_tN),
    # so the audit truly covers the test's working set, not just
    # the sample buffer.
    for tprefix, min_count in REQUIRED_TEST_PREFIX_MIN.items():
        # Count seen names that start with "tN_" but exclude
        # "samples_tN" (already covered above).
        n = sum(1 for name in seen_names
                if name.startswith(tprefix + "_"))
        if n < min_count:
            fail(f"memory placement: only {n} benchmark-owned "
                 f"objects whose name starts with '{tprefix}_' were "
                 f"audited (expected at least {min_count}). "
                 f"This means at least one test private object "
                 f"(stack/sync/mutex) is no longer being exposed "
                 f"in bench_t{tprefix[1]}_print_addresses(). "
                 f"ADR-017 audit is incomplete.")

    # Codex round-2 sec. B1: AUTORUN policy per profile + publication
    # mode (ADR-016 patched 2026-05-12). In Mode LA the operator
    # must arm the logic analyzer between READY and START, which
    # is incompatible with AUTORUN. In Mode DWT-only, AUTORUN is
    # acceptable (the DWT measurement does not depend on operator
    # timing). debug_dev is non-publishable, so AUTORUN is always
    # allowed there.
    if (args.profile in PUBLISHABLE_PROFILES
            and args.publication_mode == "la"):
        autorun_markers = [t for t in agg["test_markers"]
                           if t[0] == "AUTORUN"]
        if autorun_markers:
            tests_seen = sorted({t[1] for t in autorun_markers})
            fail(f"AUTORUN marker(s) found for tests {tests_seen} "
                 f"in profile {args.profile!r} / publication mode "
                 f"'la'. Mode LA requires B1 gating (ADR-016); "
                 f"rebuild with BENCH_AUTORUN=0 or switch to "
                 f"--publication-mode dwt_only.")

    # rtos / profile match (fail-stop, not warn)
    for row in agg["dwt_rows"]:
        rtos, profile, test_name, *_ = row
        if rtos != args.rtos:
            fail(f"DWT row {test_name}: rtos={rtos!r} != CLI "
                 f"rtos={args.rtos!r}")
        if profile != args.profile:
            fail(f"DWT row {test_name}: profile={profile!r} != CLI "
                 f"profile={args.profile!r}")
    for row in agg["t4pi_rows"]:
        rtos, profile, *_ = row
        if rtos != args.rtos:
            fail(f"T4 PI row: rtos={rtos!r} != CLI "
                 f"rtos={args.rtos!r}")
        if profile != args.profile:
            fail(f"T4 PI row: profile={profile!r} != CLI "
                 f"profile={args.profile!r}")

    # debug_dev gate: not allowed in publishable profiles
    if args.profile in ("fair_perf", "realistic_tickless"):
        for row in agg["dwt_rows"] + agg["t4pi_rows"]:
            if row[1] == "debug_dev":
                fail(f"debug_dev row found in {args.profile} run")

    # Codex round-2 sec. I2: strict metric-name validation. Every DWT
    # CSV row must declare the metric label expected for its test
    # (ADR-015 patched 2026-05-12). A typo or a stale firmware
    # build is otherwise aggregated silently downstream.
    for row in agg["dwt_rows"]:
        _, _, test_name, metric, *_ = row
        expected_metric = EXPECTED_METRIC_BY_TEST.get(test_name)
        if expected_metric is None:
            fail(f"unknown test_name {test_name!r} (allowed: "
                 f"{sorted(EXPECTED_METRIC_BY_TEST)})")
        if metric != expected_metric:
            fail(f"{test_name}: metric={metric!r}, expected "
                 f"{expected_metric!r} (Codex round-2 sec. I2)")

    # cycles > 0 and us = cycles * 1e6 / clock (within tolerance)
    clock = agg["system_clock_hz"]
    for row in agg["dwt_rows"]:
        _, _, test_name, metric, phase, it, cycles_s, us_s = row
        cycles = int(cycles_s)
        us     = float(us_s)
        if cycles <= 0:
            fail(f"row {test_name}/{metric}/{phase}/{it}: cycles "
                 f"non-positive ({cycles})")
        expected_us = cycles * 1_000_000.0 / clock
        if abs(us - expected_us) > US_TOLERANCE:
            fail(f"row {test_name}/{metric}/{phase}/{it}: us={us} "
                 f"vs cycles*1e6/clock={expected_us:.6f} "
                 f"(tol={US_TOLERANCE})")

    # Row counts: T1/T2/T3 fixed warmup+valid; T4 valid only.
    counts: dict[tuple[str, str], int] = {}
    for row in agg["dwt_rows"]:
        _, _, test_name, _, phase, *_ = row
        key = (test_name, phase)
        counts[key] = counts.get(key, 0) + 1

    for tname in ("t1_irq", "t2_handoff", "t3_mtx_uncont"):
        n_w = counts.get((tname, "warmup"), 0)
        n_v = counts.get((tname, "valid"),  0)
        if n_w != EXPECTED_WARMUP_PER_TEST:
            fail(f"{tname}: warmup rows = {n_w}, expected "
                 f"{EXPECTED_WARMUP_PER_TEST}")
        if n_v != EXPECTED_VALID_PER_TEST:
            fail(f"{tname}: valid rows = {n_v}, expected "
                 f"{EXPECTED_VALID_PER_TEST}")

    n_t4_v = counts.get(("t4_mtx_pi", "valid"), 0)
    if n_t4_v != EXPECTED_T4_VALID:
        fail(f"t4_mtx_pi: valid rows = {n_t4_v}, expected "
             f"{EXPECTED_T4_VALID}")

    n_pi = len(agg["t4pi_rows"])
    if n_pi != EXPECTED_T4_PI:
        fail(f"t4_mtx_pi: PI rows = {n_pi}, expected "
             f"{EXPECTED_T4_PI}")

    # Iteration sequence: not just count, but also that the iteration
    # values form a contiguous 1..N range with no gaps and no duplicates
    # (round-9 sec. A1). The firmware emits 1-based iterations per
    # (test_name, metric, phase) group via `i + 1U`.
    iters: dict[tuple[str, str, str], list[int]] = {}
    for row in agg["dwt_rows"]:
        _, _, test_name, metric, phase, it, *_ = row
        key = (test_name, metric, phase)
        iters.setdefault(key, []).append(int(it))

    expected_for = {
        "warmup": EXPECTED_WARMUP_PER_TEST,
        "valid":  EXPECTED_VALID_PER_TEST,
    }
    for (test_name, metric, phase), seq in iters.items():
        if test_name == "t4_mtx_pi" and phase == "valid":
            n_expected = EXPECTED_T4_VALID
        else:
            n_expected = expected_for[phase]
        expected_set = set(range(1, n_expected + 1))
        actual_set   = set(seq)
        if actual_set != expected_set:
            missing = sorted(expected_set - actual_set)[:5]
            extra   = sorted(actual_set - expected_set)[:5]
            fail(f"{test_name}/{metric}/{phase}: iteration sequence "
                 f"is not exactly 1..{n_expected} "
                 f"(missing={missing}, extra={extra}, "
                 f"len_actual={len(seq)})")
        if len(seq) != n_expected:
            fail(f"{test_name}/{metric}/{phase}: duplicate iterations "
                 f"({len(seq)} rows for {n_expected} unique values)")
        if seq != sorted(seq):
            fail(f"{test_name}/{metric}/{phase}: iterations not in "
                 f"monotonic increasing order (firmware always emits "
                 f"in order; out-of-order may indicate UART corruption)")

    # T4 PI rows: same 1..100 contract.
    pi_iters = [int(row[3]) for row in agg["t4pi_rows"]]
    expected_pi_set = set(range(1, EXPECTED_T4_PI + 1))
    if set(pi_iters) != expected_pi_set:
        missing = sorted(expected_pi_set - set(pi_iters))[:5]
        extra   = sorted(set(pi_iters) - expected_pi_set)[:5]
        fail(f"t4_mtx_pi PI rows: iteration sequence not "
             f"1..{EXPECTED_T4_PI} (missing={missing}, extra={extra})")
    if len(pi_iters) != EXPECTED_T4_PI:
        fail(f"t4_mtx_pi PI rows: duplicate iterations "
             f"({len(pi_iters)} for {EXPECTED_T4_PI} unique values)")
    if pi_iters != sorted(pi_iters):
        fail(f"t4_mtx_pi PI rows: iterations not in monotonic order")


def write_outputs(agg: dict, prefix: Path, args) -> None:
    csv_path    = prefix.parent / (prefix.name + ".csv")
    t4pi_path   = prefix.parent / (prefix.name + ".t4_pi.csv")
    banner_path = prefix.parent / (prefix.name + ".banner.txt")
    valid_path  = prefix.parent / (prefix.name + ".validated.json")

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        f.write(DWT_HEADER + "\n")
        for row in agg["dwt_rows"]:
            f.write(",".join(row) + "\n")
    with t4pi_path.open("w", encoding="utf-8", newline="") as f:
        f.write("rtos,profile,test_name,iteration,pi_ok\n")
        for row in agg["t4pi_rows"]:
            f.write(",".join(row) + "\n")
    banner_path.write_text("\n".join(agg["banner"]) + "\n",
                           encoding="utf-8")

    # 2a - archive ELF and MAP next to the CSV and record their
    # SHA256 + size in the manifest (Codex round-3). For
    # publishable profiles main() has already verified that both
    # files exist; for debug_dev they may be omitted.
    artefact_hashes: dict[str, str | int] = {}
    for kind, src_str in (("elf", args.elf_file),
                          ("map", args.map_file)):
        if src_str is None:
            continue
        src = Path(src_str)
        if not src.is_file():
            print(f"WARNING: --{kind}-file {src} not found, NOT "
                  f"archived.", file=sys.stderr)
            continue
        dst = prefix.parent / (prefix.name + f".{kind}")
        shutil.copyfile(src, dst)
        sha, size = _sha256_and_size(dst)
        artefact_hashes[f"{kind}_sha256"]     = sha
        artefact_hashes[f"{kind}_size_bytes"] = size
        print(f"Archived {kind}: {dst} "
              f"(sha256={sha[:16]}..., {size} bytes)")

    # Round-11 item 3 - validation manifest. Written ONLY if every
    # validate() check passed (we are past validate() at this point).
    # report_results.py with --publication-gate refuses CSVs that do
    # not have a companion `.validated.json`.
    bf = agg["banner_fields"]
    manifest = {
        "schema":           "rtos-benchmark/collect/v1",
        "validated":        True,
        "rtos":             args.rtos,
        "profile":          args.profile,
        "run_id":           args.run_id,
        "publication_mode": args.publication_mode,
        "system_clock_hz":  agg["system_clock_hz"],
        "rtos_kernel":      bf.get("RTOS kernel")
                            or bf.get("RTOS version", ""),
        "vos_level":        bf.get("VOS level", ""),
        "vosrdy":           bf.get("VOSRDY", ""),
        "flash_acr":        bf.get("FLASH_ACR", ""),
        "tickless":         bf.get("Tickless", ""),
        "wfi_in_idle":      bf.get("WFI in idle", ""),
        "tim2_after_t1_setup_ok": True,
        "memory_placement_ok":    True,
        "iteration_sequences_ok": True,
        "n_dwt_rows":       len(agg["dwt_rows"]),
        "n_t4_pi_rows":     len(agg["t4pi_rows"]),
        **artefact_hashes,
    }
    valid_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote validation manifest: {valid_path}")


# === Entry point ======================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Fail-stop benchmark log collector "
                    "(round-8 acceptance criteria)."
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--port",
                    help="Serial port (e.g. COM6 or /dev/ttyACM0).")
    src.add_argument("--from-log",
                    help="Read from a captured raw log file (replay).")
    p.add_argument("--baud",    type=int, default=115200)
    p.add_argument("--rtos",    required=True,
                  choices=["chibios", "freertos", "zephyr"])
    p.add_argument("--profile", required=True,
                  choices=["fair_perf", "realistic_tickless",
                           "debug_dev"])
    p.add_argument("--run-id",  default="01")
    p.add_argument("--output",
                  help="Output prefix; default "
                       "results/raw/<rtos>_<profile>_run<run-id>.")
    p.add_argument("--timeout", type=int, default=30,
                  help="Seconds without new data before closing "
                       "(serial mode only).")
    p.add_argument("--map-file",
                  help="Path to the build .map file; mandatory for "
                       "publishable profiles. Copied to <prefix>.map "
                       "(VAL-010) and hashed for the manifest.")
    p.add_argument("--elf-file",
                  help="Path to the build .elf file; mandatory for "
                       "publishable profiles. Copied to <prefix>.elf "
                       "and hashed for the manifest.")
    p.add_argument("--quiet", action="store_true",
                  help="Do not mirror serial lines to stdout in real "
                       "time (recommended for unittest harnesses).")
    p.add_argument("--publication-mode",
                  choices=PUBLICATION_MODES,
                  default=None,
                  help="Required for fair_perf / realistic_tickless: "
                       "'la' (LA-primary, B1 gating, AUTORUN "
                       "forbidden) or 'dwt_only' (DWT-primary, "
                       "AUTORUN allowed). Defaults to 'dwt_only' "
                       "for debug_dev. See ADR-015.")
    args = p.parse_args(argv)

    # Publication-mode enforcement (ADR-015 + ADR-016 patched
    # 2026-05-12). Publishable profiles MUST declare the mode at
    # CLI time; debug_dev defaults to dwt_only.
    if args.profile in PUBLISHABLE_PROFILES:
        if args.publication_mode is None:
            print(f"ERROR: --publication-mode is required for "
                  f"profile {args.profile!r} "
                  f"(choices: la / dwt_only). See ADR-015.",
                  file=sys.stderr)
            return 2
    elif args.publication_mode is None:
        args.publication_mode = "dwt_only"

    # 2a - ELF / MAP are mandatory artefacts for publishable
    # profiles (Codex round-3 2a requirement). validated.json must
    # record their SHA256 + size so the publication gate can prove
    # that all run01..run05 of a (rtos, profile) flashed the same
    # firmware image.
    for argname, value in (("--elf-file", args.elf_file),
                           ("--map-file", args.map_file)):
        if args.profile in PUBLISHABLE_PROFILES:
            if value is None:
                print(f"ERROR: {argname} is required for profile "
                      f"{args.profile!r} (Codex round-3 2a).",
                      file=sys.stderr)
                return 2
            if not Path(value).is_file():
                print(f"ERROR: {argname} {value!r} does not exist.",
                      file=sys.stderr)
                return 2

    if args.output:
        prefix = Path(args.output)
    else:
        prefix = Path(f"results/raw/{args.rtos}_{args.profile}_"
                     f"run{args.run_id}")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    raw_log_path = prefix.parent / (prefix.name + ".stdout.txt")

    if args.from_log:
        lines = iter_log_file(Path(args.from_log))
        print(f"Replay mode: reading from {args.from_log}")
    else:
        print(f"Port    : {args.port} @ {args.baud} baud")
        print(f"RTOS    : {args.rtos} / {args.profile} / "
              f"run {args.run_id}")
        print(f"Press RESET on the board to start the benchmark.\n")
        lines = iter_serial(args.port, args.baud, args.timeout)

    try:
        result = collect(passthrough(lines) if args.quiet
                         else echo(lines))
    except KeyboardInterrupt:
        # Best-effort: persist what we have for diagnostics.
        sys.stderr.write("\nInterrupted by user.\n")
        sys.exit(2)

    # Persist the raw log unconditionally, so a failed run is still
    # diagnosable. The other artefacts are written only on success.
    raw_log_path.write_text("\n".join(result["raw"]) + "\n",
                            encoding="utf-8")

    validate(result, args)              # exits on first violation
    write_outputs(result, prefix, args) # only reached if validate OK

    print()
    print(f"OK: dwt_rows = {len(result['dwt_rows'])}")
    print(f"    t4pi_rows= {len(result['t4pi_rows'])}")
    print(f"    clock    = {result['system_clock_hz']} Hz")
    print(f"    markers  = {len(result['test_markers'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
