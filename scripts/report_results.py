#!/usr/bin/env python3
"""
report_results.py — official report generator for the RTOS benchmark
(round-9 C1).

Reads the validated CSVs produced by collect_results.py, recomputes
the firmware-equivalent stats on the valid range, and writes:

    results/summary/<rtos>_<profile>_run<NN>_summary.md
    results/summary/<rtos>_<profile>_run<NN>_summary.csv
    results/summary/<profile>_aggregate.csv
    results/summary/<profile>_aggregate.md
    results/summary/<profile>_compare.md

The aggregate (multi-run) collapses each per-stats field to the
**median across the N runs**, so a single bad run cannot bias the
published number. ADR-013 mandates at least 5 independent runs;
this script scales transparently to whatever subset is present.

Stat formula: identical to the firmware (`bench_compute_stats` in
common/benchmark_stats.c) and to scripts/analyze_results.py:

    sorted = sorted(values)
    median = sorted[n // 2]
    p95    = sorted[(n * 95) // 100]
    p99    = sorted[(n * 99) // 100]
    mean   = sum(values) // n              # integer truncation
    stddev = int(sqrt(sum((v - mean)**2) // n))

NumPy is intentionally NOT used: NumPy's `np.percentile` defaults to
linear interpolation and would diverge from the firmware (see ADR-013).

Inputs the script does NOT read:
    - <prefix>.stdout.txt   (raw log, banner, TIM2 dump — assumed
                             already validated by collect_results.py)
    - <prefix>.banner.txt   (same)

This script's contract: input CSVs must be already valid. It does
NOT re-do the collect_results.py acceptance gates.

CLI:
    python scripts/report_results.py --profile fair_perf
    python scripts/report_results.py             # all profiles
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path
from statistics import median


# Banner field "  KEY ...  : VALUE", same shape as in collect_results.py.
BANNER_FIELD_RE = re.compile(r"^\s+(\S[^:]*?)\s*:\s*(.+?)\s*$")
BANNER_DIVIDER_RE = re.compile(r"^={10,}$")

# Subset of banner fields to surface in the published summaries.
# Both "RTOS kernel" (current banner field, e.g. "ChibiOS RT 7.0.6")
# and the legacy "RTOS version" are accepted: report_results.py is
# expected to read banners produced by older firmware too.
META_FIELDS = ("RTOS", "RTOS kernel", "RTOS version", "Profile",
               "Board", "DBGMCU IDCODE", "SystemClock", "VOS level",
               "VOSRDY", "FLASH_ACR", "Optimization")
# Field that carries the kernel identification (current banner key
# preferred, fall back to the older one).
KERNEL_FIELD_KEYS = ("RTOS kernel", "RTOS version")


def kernel_label(meta: dict) -> str:
    """Pick whichever of the two banner keys is present."""
    for key in KERNEL_FIELD_KEYS:
        if key in meta:
            return meta[key]
    return ""


def load_banner_metadata(banner_path: Path) -> dict[str, str]:
    """Parse the boot banner archived by collect_results.py and
    return a dict of {key: value}. Only the first banner block
    (between the ====...==== dividers) is considered. Empty dict
    if the file is missing or malformed."""
    if not banner_path.is_file():
        return {}
    fields: dict[str, str] = {}
    in_banner = False
    seen_dividers = 0
    with banner_path.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if BANNER_DIVIDER_RE.match(line):
                seen_dividers += 1
                in_banner = (seen_dividers == 1)
                if seen_dividers >= 2:
                    break
                continue
            if not in_banner:
                continue
            m = BANNER_FIELD_RE.match(line)
            if m:
                key, val = m.group(1).strip(), m.group(2).strip()
                fields[key] = val
    return fields


# === Constants ========================================================

REPO_ROOT       = Path(__file__).resolve().parents[1]
DEFAULT_IN_DIR  = REPO_ROOT / "results" / "raw"
DEFAULT_OUT_DIR = REPO_ROOT / "results" / "summary"
SYS_CLOCK_HZ    = 480_000_000

TESTS = ("t1_irq", "t2_handoff", "t3_mtx_uncont", "t4_mtx_pi")

# Round-11 §6 + ADR-015 2026-05-12 — source classification per test
# is conditional on the publication_mode declared in each run's
# validated.json:
#   Mode LA (LA-primary, ADR-015): T1 / T4 headline come from the
#     logic-analyzer capture; DWT figures are software-only
#     validation, labeled "DWT_validation".
#   Mode DWT-only (Phase 1 active per user decision): TEST 1
#     headline IS the DWT figure (`A4 - A1` /
#     `ISR_ENTRY -> THREAD_RUNNING`); TEST 4 latency IS the DWT
#     handoff figure. They are not validation, they are the
#     published source, labeled "DWT".
# T4 PI pass/fail is always the firmware sequence-check ("PI")
# regardless of mode; in Mode LA the LA waveform is consulted
# separately as supporting evidence.
SOURCE_BY_TEST_BY_MODE = {
    "la": {
        "t1_irq":        "DWT_validation",
        "t2_handoff":    "DWT",
        "t3_mtx_uncont": "DWT",
        "t4_mtx_pi":     "DWT_validation",
    },
    "dwt_only": {
        "t1_irq":        "DWT",
        "t2_handoff":    "DWT",
        "t3_mtx_uncont": "DWT",
        "t4_mtx_pi":     "DWT",
    },
}
T4_PI_SOURCE = "PI"   # firmware sequence-check, mode-independent


def source_by_test(test: str, publication_mode: str | None) -> str:
    """Return the report source label for @p test under the run's
    @p publication_mode. Unknown / missing mode defaults to
    'dwt_only' (Phase 1 active default; the EXPLORATORY banner
    already warns the reader)."""
    mode = (publication_mode
            if publication_mode in ("la", "dwt_only")
            else "dwt_only")
    return SOURCE_BY_TEST_BY_MODE[mode][test]


# 2026-05-13 overview-md: shared per-mode source-attribution
# paragraphs. The compare and overview Markdown outputs both
# emit one of these; the wording is the contract between the
# pipeline and the reader, see ADR-015. Codex round-3
# overview-md design review explicitly required the
# "unknown" wording for the executive overview page (the
# compare file relies on the EXPLORATORY banner instead).
SOURCE_ATTRIBUTION_BY_MODE = {
    "dwt_only": (
        "**Source attribution — Phase 1 (DWT-only):** every "
        "latency number in this report is computed via the DWT "
        "cycle counter inside the firmware. TEST 1 corresponds "
        "to `A4 - A1` (`ISR_ENTRY -> THREAD_RUNNING`, metric "
        "`dwt_a4_minus_a1`); the hardware-event-to-ISR-entry "
        "component (timer compare match, NVIC entry, stacking, "
        "vectoring, ISR prologue) is EXCLUDED. These figures "
        "must NOT be quoted as the external IRQ-to-thread "
        "latency or as an LA-equivalent measurement. "
        "See ADR-015."),
    "la": (
        "**Source attribution — Mode LA:** TEST 1 headline "
        "figure corresponds to `A4 - A0_HW` (external hardware "
        "event -> thread running), captured by the logic "
        "analyzer. The DWT figure (`dwt_a4_minus_a1`) is "
        "carried as software validation only. See ADR-015."),
    "unknown": (
        "**Source attribution — unresolved:** this report is "
        "not publication-gated and the runs lack a coherent "
        "`publication_mode` declaration. Numbers MUST NOT be "
        "quoted as official benchmark data."),
}


# Stats fields we report. Order matters: it determines the column
# layout of the CSV / MD outputs.
STAT_FIELDS = ("n", "min", "median", "mean",
               "p95", "p99", "max", "jitter", "stddev")

RUN_FILE_RE = re.compile(
    r"^(chibios|freertos|zephyr)_"
    r"(fair_perf|realistic_tickless|debug_dev)_"
    r"run(\d+)\.csv$"
)

# 2a — SHA256 hex digest: 64 lowercase hex chars.
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Round-11 §4: run_id "00" is reserved as a global warmup capture
# (cache cold, UART buffer settling, first-flash bias) and MUST
# never be aggregated. The collector may produce one (diagnostic);
# the reporter always excludes it.
GLOBAL_WARMUP_RUN_ID = "00"

# Round-11 §5: publication-gate requires that, for every RTOS, at
# least these run_ids are present after run00 is excluded.
PUBLICATION_REQUIRED_RUN_IDS = {"01", "02", "03", "04", "05"}
PUBLICATION_REQUIRED_RTOSES  = {"chibios", "freertos", "zephyr"}


# === Stats (firmware-equivalent) ======================================

def recompute_stats(values: list[int]) -> dict[str, int]:
    n      = len(values)
    if n == 0:
        return {f: 0 for f in STAT_FIELDS}
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


def cycles_to_us(c: int | float) -> float:
    return c * 1_000_000.0 / SYS_CLOCK_HZ


# === CSV loaders ======================================================

def load_csv_valid_per_test(csv_path: Path) -> dict[str, list[int]]:
    """{test_name: [cycles, ...]} — only phase=valid rows."""
    out: dict[str, list[int]] = {}
    with csv_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            fields = line.rstrip().split(",")
            if len(fields) != 8 or fields[4] != "valid":
                continue
            try:
                cycles = int(fields[6])
            except ValueError:
                continue
            out.setdefault(fields[2], []).append(cycles)
    return out


def load_t4_pi(t4pi_path: Path) -> tuple[int, int]:
    """Return (n_passed, n_total). Missing file -> (0, 0)."""
    if not t4pi_path.is_file():
        return 0, 0
    n_total  = 0
    n_passed = 0
    with t4pi_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            fields = line.rstrip().split(",")
            if len(fields) != 5 or fields[2] != "t4_mtx_pi":
                continue
            try:
                pi = int(fields[4])
            except ValueError:
                continue
            n_total  += 1
            n_passed += pi
    return n_passed, n_total


# === Discovery ========================================================

def check_validated_manifest(valid_path: Path,
                             rtos: str, profile: str, run_id: str
                             ) -> list[str]:
    """Open <prefix>.validated.json and verify that the collector's
    own claims still hold (round-12 §4). Returns list of error
    strings, empty if the manifest is sound."""
    errs: list[str] = []
    try:
        manifest = json.loads(valid_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{valid_path.name}: cannot parse JSON ({exc})"]

    expected = {
        "validated":               True,
        "rtos":                    rtos,
        "profile":                 profile,
        "run_id":                  run_id,
        "system_clock_hz":         480_000_000,
        "vos_level":               "VOS0",
        "vosrdy":                  "READY",
        "flash_acr":               "0x00000034",
        "tim2_after_t1_setup_ok":  True,
        "memory_placement_ok":     True,
        "iteration_sequences_ok":  True,
    }
    for key, want in expected.items():
        if key not in manifest:
            errs.append(f"{valid_path.name}: missing key '{key}'")
            continue
        got = manifest[key]
        if got != want:
            errs.append(f"{valid_path.name}: {key}={got!r}, "
                        f"expected {want!r}")
    # 2026-05-12 — publication_mode must be present and one of the
    # two values allowed by ADR-015. We do not pin a specific value
    # here (a run may legitimately be 'la' OR 'dwt_only'); the
    # homogeneity-across-runs check lives in check_publication_gate.
    mode = manifest.get("publication_mode")
    if mode is None:
        errs.append(f"{valid_path.name}: missing key "
                    f"'publication_mode'")
    elif mode not in ("la", "dwt_only"):
        errs.append(f"{valid_path.name}: publication_mode="
                    f"{mode!r}, expected 'la' or 'dwt_only' "
                    f"(ADR-015)")

    # 2a — ELF / MAP hashes must be present, well-formed SHA256 hex
    # digests, with positive size fields. Codex round-3 requires
    # publishable artefacts to be traceable to the firmware build.
    for kind in ("elf", "map"):
        sha_key  = f"{kind}_sha256"
        size_key = f"{kind}_size_bytes"
        if sha_key not in manifest:
            errs.append(f"{valid_path.name}: missing key "
                        f"{sha_key!r}")
        else:
            sha = manifest[sha_key]
            if not isinstance(sha, str) or not SHA256_RE.match(sha):
                errs.append(f"{valid_path.name}: {sha_key}={sha!r} "
                            f"is not a 64-char lowercase SHA256 hex "
                            f"digest")
        if size_key not in manifest:
            errs.append(f"{valid_path.name}: missing key "
                        f"{size_key!r}")
        else:
            sz = manifest[size_key]
            if not isinstance(sz, int) or sz <= 0:
                errs.append(f"{valid_path.name}: {size_key}={sz!r} "
                            f"must be a positive integer")

    # Profile-conditional checks: tickless / WFI flow with the
    # profile name. fair_perf wants both OFF.
    if profile == "fair_perf":
        if manifest.get("tickless") != "OFF":
            errs.append(f"{valid_path.name}: tickless="
                        f"{manifest.get('tickless')!r}, expected 'OFF' "
                        f"in fair_perf profile")
        if manifest.get("wfi_in_idle") != "OFF":
            errs.append(f"{valid_path.name}: wfi_in_idle="
                        f"{manifest.get('wfi_in_idle')!r}, "
                        f"expected 'OFF' in fair_perf profile")
    return errs


def _check_warmup_validated(
        runs: list[tuple[str, str, str, Path, Path]],
        by_profile: dict,
        warmup_dict: dict[tuple[str, str], Path],
) -> list[str]:
    """Codex round 2026-05-14-bucket-c4-...-002
    IMPORTANT 1 — ADR-013 enforcement, strengthened: every
    publishable (rtos, profile) with a run01..05 set MUST
    have a run00 CSV AND a run00 `.validated.json` whose
    manifest passes the standard contract AND whose
    ELF/MAP SHA matches the run01..05 locked SHA. A stale,
    hand-crafted, or failed-collector run00 cannot satisfy
    the gate."""
    errs: list[str] = []

    # Build per-(rtos, profile) ELF / MAP SHA set from
    # run01..05 validated.json files. We deliberately do
    # NOT re-flag malformed SHAs here — that is already
    # caught by check_validated_manifest in the per-entry
    # loop.
    pair_shas: dict[tuple[str, str], dict[str, set[str]]] = {}
    for rtos, profile, run_id, csv_path, t4pi_path in runs:
        if profile == "debug_dev":
            continue
        valid_path = (csv_path.parent
                      / (csv_path.stem + ".validated.json"))
        if not valid_path.is_file():
            continue
        try:
            mf = json.loads(
                valid_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for kind in ("elf", "map"):
            sha = mf.get(f"{kind}_sha256")
            if (isinstance(sha, str)
                    and SHA256_RE.match(sha)):
                pair_shas.setdefault(
                    (rtos, profile), {}).setdefault(
                    kind, set()).add(sha)

    for profile, by_rtos in by_profile.items():
        for rtos in sorted(by_rtos.keys()):
            key = (rtos, profile)
            warmup_csv = warmup_dict.get(key)
            if warmup_csv is None:
                errs.append(
                    f"{rtos}/{profile}: missing run00 "
                    f"global warmup capture (ADR-013) — "
                    f"publishable campaigns must include "
                    f"a discarded run00 before run01..05; "
                    f"re-run lab_campaign.ps1 without "
                    f"-SkipWarmup")
                continue
            valid_path = (warmup_csv.parent
                          / (warmup_csv.stem
                             + ".validated.json"))
            if not valid_path.is_file():
                errs.append(
                    f"{rtos}/{profile}: run00 CSV present "
                    f"but missing companion "
                    f"{valid_path.name} — the run00 warmup "
                    f"must be a validated capture from the "
                    f"same locked firmware (ADR-013)")
                continue
            # Standard manifest contract on the run00
            # validated.json. Catches wrong rtos, wrong
            # profile, wrong run_id, missing fields, etc.
            errs.extend(check_validated_manifest(
                valid_path, rtos, profile,
                GLOBAL_WARMUP_RUN_ID))
            try:
                mf = json.loads(
                    valid_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            # Run00 ELF / MAP SHA must match the run01..05
            # locked SHA for the same (rtos, profile).
            for kind in ("elf", "map"):
                run00_sha = mf.get(f"{kind}_sha256")
                if (not isinstance(run00_sha, str)
                        or not SHA256_RE.match(run00_sha)):
                    continue  # already flagged by manifest
                expected = pair_shas.get(key, {}).get(
                    kind, set())
                if not expected:
                    continue  # no run01..05 SHA to compare
                if run00_sha not in expected:
                    expected_one = sorted(expected)[0]
                    errs.append(
                        f"{rtos}/{profile}: run00 "
                        f"{kind}_sha256 = {run00_sha} does "
                        f"not match run01..05 "
                        f"{kind}_sha256 = {expected_one} "
                        f"— warmup was captured from a "
                        f"different firmware build")
    return errs


def check_publication_gate(
        runs: list[tuple[str, str, str, Path, Path]],
        warmup_dict: dict[tuple[str, str], Path] | None = None
) -> list[str]:
    """Return the list of human-readable reasons why this run set
    is NOT publishable. Empty list = ready to publish.

    Rules (round-11 §5 + round-12 §4 + 2026-05-12 ADR-014/ADR-011/
           ADR-015 + Codex round
           2026-05-14-bucket-c4-lab-scripts-audit-001):
      1. Every (rtos, profile) covered must have run_ids {01..05}.
      2. The 3 expected RTOS ports must all be present.
      3. Each .csv must have a sibling .t4_pi.csv.
      4. Each .csv must have a sibling .validated.json (= the
         collector confirmed all gates passed).
      5. The .validated.json content must match the run filename
         and the expected hardware manifest (round-12 §4) plus a
         valid publication_mode (ADR-015).
      6. debug_dev runs are NOT publishable (ADR-011); their
         presence in the run set is a hard error.
      7. TEST 4 PI must be 100% (every pi_ok == 1) in every run;
         any failure invalidates the PI claim per ADR-014.
      8. Within one profile, all runs must declare the same
         publication_mode (ADR-015): mixing 'la' and 'dwt_only'
         inside a single aggregate would produce a report whose
         headline metric source differs across rows.
      9. Within one (rtos, profile), all runs must share the same
         elf_sha256 and map_sha256 (Codex round-3 2a). A SHA
         drift inside a campaign means a different firmware was
         flashed mid-campaign; publication is refused.
    """
    errs: list[str] = []
    by_profile: dict[str, dict[str, set[str]]] = {}
    for rtos, profile, run_id, csv_path, t4pi_path in runs:
        if profile == "debug_dev":
            errs.append(f"{csv_path.name}: profile 'debug_dev' is "
                        f"non-publishable per ADR-011")
            continue
        by_profile.setdefault(profile, {}).setdefault(rtos, set()).add(run_id)
        if not t4pi_path.is_file():
            errs.append(f"{csv_path.name}: missing companion "
                        f"{t4pi_path.name}")
        else:
            pi_pass, pi_total = load_t4_pi(t4pi_path)
            if pi_total == 0:
                errs.append(f"{t4pi_path.name}: empty T4 PI file")
            elif pi_pass != pi_total:
                errs.append(f"{t4pi_path.name}: T4 PI failure "
                            f"({pi_pass}/{pi_total} passed) -- any "
                            f"PI failure invalidates the PI claim "
                            f"per ADR-014")
        valid_path = (csv_path.parent /
                      (csv_path.stem + ".validated.json"))
        if not valid_path.is_file():
            errs.append(f"{csv_path.name}: missing companion "
                        f"{valid_path.name} — run was not validated "
                        f"by collect_results.py")
        else:
            errs.extend(check_validated_manifest(
                valid_path, rtos, profile, run_id))

    for profile, by_rtos in by_profile.items():
        missing_rtos = PUBLICATION_REQUIRED_RTOSES - set(by_rtos)
        if missing_rtos:
            errs.append(f"profile {profile}: missing RTOS "
                        f"port(s): {sorted(missing_rtos)}")
        for rtos, run_ids in by_rtos.items():
            missing = PUBLICATION_REQUIRED_RUN_IDS - run_ids
            if missing:
                errs.append(f"profile {profile} / rtos {rtos}: "
                            f"missing run_id(s): {sorted(missing)}")

    # Rule 10 (Codex round
    # 2026-05-14-bucket-c4-lab-scripts-audit-002
    # IMPORTANT 1) — ADR-013 run00 warmup must be a
    # VALIDATED capture from the same locked firmware as
    # run01..05. The CSV alone is not enough; the
    # `.validated.json` manifest contract must pass, and
    # the ELF / MAP SHA must match the run01..05 SHA for
    # the same (rtos, profile).
    if warmup_dict is not None:
        errs.extend(_check_warmup_validated(
            runs, by_profile, warmup_dict))

    # Rule 8 — publication_mode homogeneity per profile.
    modes_by_profile: dict[str, dict[str, list[str]]] = {}
    for rtos, profile, run_id, csv_path, t4pi_path in runs:
        if profile == "debug_dev":
            continue
        valid_path = (csv_path.parent /
                      (csv_path.stem + ".validated.json"))
        if not valid_path.is_file():
            continue
        try:
            manifest = json.loads(
                valid_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mode = manifest.get("publication_mode")
        if mode not in ("la", "dwt_only"):
            continue
        modes_by_profile.setdefault(profile, {}).setdefault(
            mode, []).append(csv_path.name)
    for profile, by_mode in modes_by_profile.items():
        if len(by_mode) > 1:
            parts = "; ".join(f"{m}: {sorted(by_mode[m])}"
                              for m in sorted(by_mode))
            errs.append(f"profile {profile}: mixed publication "
                        f"modes in run set ({parts}). All runs of "
                        f"a profile must share the same "
                        f"publication_mode per ADR-015.")

    # Rule 9 — ELF / MAP SHA homogeneity per (rtos, profile).
    shas_by_pair: dict[tuple[str, str], dict[str, list[tuple[str, str]]]] = {}
    # {(rtos, profile): {kind: [(csv_name, sha), ...]}}
    for rtos, profile, run_id, csv_path, t4pi_path in runs:
        if profile == "debug_dev":
            continue
        valid_path = (csv_path.parent /
                      (csv_path.stem + ".validated.json"))
        if not valid_path.is_file():
            continue
        try:
            manifest = json.loads(
                valid_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for kind in ("elf", "map"):
            sha = manifest.get(f"{kind}_sha256")
            if not isinstance(sha, str) or not SHA256_RE.match(sha):
                continue  # already reported by check_validated_manifest
            shas_by_pair.setdefault((rtos, profile), {}).setdefault(
                kind, []).append((csv_path.name, sha))
    for (rtos, profile), by_kind in shas_by_pair.items():
        for kind, pairs in by_kind.items():
            distinct = sorted({sha for _, sha in pairs})
            if len(distinct) > 1:
                detail = "; ".join(
                    f"{name}: {sha}"
                    for name, sha in sorted(pairs))
                errs.append(
                    f"(rtos={rtos}, profile={profile}): "
                    f"{kind}_sha256 mismatch across runs ({detail}). "
                    f"All runs of a (rtos, profile) must reuse the "
                    f"same firmware artefact (Codex round-3 2a).")
    return errs


def load_campaign_lock(profile: str,
                       manifest_dir: Path) -> dict | None:
    """2026-05-13 overview-md: load
    <manifest_dir>/<profile>_campaign.lock.json as audit data
    (timestamp, ELF/MAP hashes per RTOS, declared
    publication_mode). Never raises: a missing or malformed
    file returns None so exploratory reports can still be
    generated. The publication gate has its own per-run
    SHA verification path (rule 9), so this loader is
    advisory only."""
    path = manifest_dir / f"{profile}_campaign.lock.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # Codex round-3 overview-md PASS_WITH_FIXES: syntactically
    # valid JSON that is not an object (e.g. `[]`, `"x"`, `42`)
    # would otherwise reach the caller's `.get()` and crash.
    if not isinstance(data, dict):
        return None
    return data


def discover_warmup_runs(input_dir: Path,
                         profile_filter: str | None
                         ) -> dict[tuple[str, str], Path]:
    """Return a dict mapping (rtos, profile) -> run00 CSV
    path for every warmup capture present in @p input_dir.
    The publication gate uses this to enforce the ADR-013
    contract: every publishable (rtos, profile) MUST have
    flashed-and-discarded a warmup run before run01..run05.
    The CSV itself is excluded from aggregation by
    `discover_runs`; the gate also walks the companion
    `.validated.json` to verify the manifest contract and
    the artifact-SHA match vs run01..run05 (Codex round
    2026-05-14-bucket-c4-...-002 IMPORTANT 1)."""
    out: dict[tuple[str, str], Path] = {}
    for csv_path in input_dir.glob("*.csv"):
        if csv_path.name.endswith(".t4_pi.csv"):
            continue
        m = RUN_FILE_RE.match(csv_path.name)
        if not m:
            continue
        rtos, profile, run_id = (m.group(1), m.group(2),
                                 m.group(3))
        if run_id != GLOBAL_WARMUP_RUN_ID:
            continue
        if profile_filter and profile != profile_filter:
            continue
        out[(rtos, profile)] = csv_path
    return out


def discover_runs(input_dir: Path, profile_filter: str | None
                  ) -> list[tuple[str, str, str, Path, Path]]:
    """Yield (rtos, profile, run_id, csv_path, t4pi_path).
    Round-11 §4: the global warmup run (run_id == "00") is always
    excluded from the report — its purpose is to prime cache /
    UART / boot path, never to contribute to published numbers."""
    runs = []
    for csv_path in sorted(input_dir.glob("*.csv")):
        if csv_path.name.endswith(".t4_pi.csv"):
            continue
        m = RUN_FILE_RE.match(csv_path.name)
        if not m:
            continue
        rtos, profile, run_id = m.group(1), m.group(2), m.group(3)
        if run_id == GLOBAL_WARMUP_RUN_ID:
            print(f"  (skipping {csv_path.name}: run00 is global "
                  f"warmup, never aggregated)")
            continue
        if profile_filter and profile != profile_filter:
            continue
        t4pi = csv_path.parent / f"{csv_path.stem}.t4_pi.csv"
        runs.append((rtos, profile, run_id, csv_path, t4pi))
    return runs


# === Per-run summary ==================================================

def per_run_summary(rtos: str, profile: str, run_id: str,
                    csv_path: Path, t4pi_path: Path
                    ) -> dict:
    by_test  = load_csv_valid_per_test(csv_path)
    pi_pass, pi_total = load_t4_pi(t4pi_path)
    rows: dict[str, dict[str, int]] = {}
    for test in TESTS:
        if test not in by_test:
            continue
        rows[test] = recompute_stats(by_test[test])
    banner_path = (csv_path.parent / (csv_path.stem + ".banner.txt"))
    meta = load_banner_metadata(banner_path)
    # 2a-bis — pick up publication_mode from validated.json so the
    # report can label TEST 1 / TEST 4 sources correctly. May be
    # None in exploratory runs (no validated.json).
    valid_path = csv_path.parent / (csv_path.stem + ".validated.json")
    publication_mode: str | None = None
    if valid_path.is_file():
        try:
            vm = json.loads(valid_path.read_text(encoding="utf-8"))
            pm = vm.get("publication_mode")
            if pm in ("la", "dwt_only"):
                publication_mode = pm
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "rtos":             rtos,
        "profile":          profile,
        "run_id":           run_id,
        "tests":            rows,
        "pi_pass":          pi_pass,
        "pi_total":         pi_total,
        "meta":             meta,
        "publication_mode": publication_mode,
    }


EXPLORATORY_BANNER = (
    "> ⚠️ **EXPLORATORY ONLY — not publication-gated.** This file "
    "was produced without `--publication-gate`. Numbers here may "
    "come from an incomplete or unvalidated run set and must NOT "
    "be quoted as official benchmark results.\n")


def write_per_run_summary_md(s: dict, out_path: Path,
                             publication_gated: bool) -> None:
    L = []
    L.append(f"# Run summary — {s['rtos']} / {s['profile']} / "
             f"run {s['run_id']}")
    L.append("")
    if not publication_gated:
        L.append(EXPLORATORY_BANNER)

    meta = s.get("meta") or {}
    if meta:
        L.append("## Run manifest (from banner)")
        L.append("")
        L.append("| field | value |")
        L.append("|-------|-------|")
        for key in META_FIELDS:
            if key in meta:
                L.append(f"| {key} | `{meta[key]}` |")
        L.append("")
    else:
        L.append(f"CPU clock assumed: {SYS_CLOCK_HZ/1e6:.0f} MHz")
        L.append("")
    L.append("| test          |     n |   min | median |  mean | "
             "  p95 |   p99 |   max | jitter | stddev |  median (us) "
             "|  p99 (us) |")
    L.append("|---------------|------:|------:|-------:|------:|"
             "------:|------:|------:|-------:|-------:|------------:"
             "|----------:|")
    for test in TESTS:
        st = s["tests"].get(test)
        if not st:
            L.append(f"| {test:<13} | (no data) |")
            continue
        L.append(
            f"| {test:<13} "
            f"| {st['n']:>5} | {st['min']:>5} | {st['median']:>6} "
            f"| {st['mean']:>5} | {st['p95']:>5} | {st['p99']:>5} "
            f"| {st['max']:>5} | {st['jitter']:>6} | {st['stddev']:>6} "
            f"| {cycles_to_us(st['median']):>11.3f} "
            f"| {cycles_to_us(st['p99']):>8.3f} |"
        )
    if s["pi_total"] > 0:
        L.append("")
        L.append(f"**T4 priority inheritance**: "
                 f"{s['pi_pass']} / {s['pi_total']} passed.")
    L.append("")
    out_path.write_text("\n".join(L), encoding="utf-8")


def write_per_run_summary_csv(s: dict, out_path: Path) -> None:
    L = ["rtos,rtos_version,profile,run_id,test,source," +
         ",".join(STAT_FIELDS) +
         ",median_us,p99_us,pi_passed,pi_total,pi_source"]
    rtos_version = kernel_label(s.get("meta") or {})
    pm = s.get("publication_mode")
    for test in TESTS:
        st = s["tests"].get(test)
        if not st:
            continue
        source = source_by_test(test, pm)
        row = [s["rtos"], rtos_version, s["profile"], s["run_id"],
               test, source]
        row += [str(st[f]) for f in STAT_FIELDS]
        row.append(f"{cycles_to_us(st['median']):.6f}")
        row.append(f"{cycles_to_us(st['p99']):.6f}")
        # PI columns only meaningful for t4_mtx_pi
        if test == "t4_mtx_pi":
            row += [str(s["pi_pass"]), str(s["pi_total"]),
                    T4_PI_SOURCE]
        else:
            row += ["", "", ""]
        L.append(",".join(row))
    out_path.write_text("\n".join(L) + "\n", encoding="utf-8")


# === Aggregate (multi-run) ============================================

def aggregate(per_run_summaries: list[dict]
              ) -> tuple[dict, dict]:
    """Returns (agg, meta_per_rtos_profile).
    `agg[(rtos, profile, test)]`        : {stat_field: median_across_runs}
    `meta_per_rtos_profile[(rtos, profile)]` :
        {field: value} taken from the first run's banner. Also
        records `version_consistent: bool` if the RTOS version
        string differs between runs of the same RTOS — that would
        be a methodological flag (binaries built from different
        submodule pins)."""
    grouped: dict[tuple[str, str, str], list[dict[str, int]]] = {}
    pi_acc:  dict[tuple[str, str], list[tuple[int, int]]] = {}
    meta_by: dict[tuple[str, str], dict] = {}
    for s in per_run_summaries:
        for test, st in s["tests"].items():
            key = (s["rtos"], s["profile"], test)
            grouped.setdefault(key, []).append(st)
        if s["pi_total"] > 0:
            pi_acc.setdefault((s["rtos"], s["profile"]), []).append(
                (s["pi_pass"], s["pi_total"]))
        rp_key = (s["rtos"], s["profile"])
        run_meta = s.get("meta") or {}
        if rp_key not in meta_by:
            # Snapshot the first run's banner; track per-key version
            # consistency as we ingest more runs.
            meta_by[rp_key] = dict(run_meta)
            meta_by[rp_key]["__version_consistent"] = True
            meta_by[rp_key]["__publication_mode"] = (
                s.get("publication_mode"))
        else:
            base = meta_by[rp_key]
            base_label = kernel_label(base)
            run_label  = kernel_label(run_meta)
            if base_label and run_label and base_label != run_label:
                base["__version_consistent"] = False

    out: dict[tuple[str, str, str], dict[str, int]] = {}
    for key, sts in grouped.items():
        agg = {"n_runs": len(sts)}
        for f in STAT_FIELDS:
            vals = [st[f] for st in sts]
            agg[f] = int(median(vals))
        # Round-11 §7 — stability across the N independent runs.
        # Use the per-run *median* values as the reference: how far
        # apart do the N median samples sit? A small spread means
        # the kernel is reproducible run-to-run; a large spread is
        # a methodological smell that must be investigated, not
        # masked by the median-of-medians.
        run_medians = [st["median"] for st in sts]
        agg["run_min"]    = min(run_medians) if run_medians else 0
        agg["run_max"]    = max(run_medians) if run_medians else 0
        agg["run_spread"] = (agg["run_max"] - agg["run_min"])
        out[key] = agg

    # Stash PI under the t4_mtx_pi entry of each (rtos, profile).
    for (rtos, profile), pi_list in pi_acc.items():
        key = (rtos, profile, "t4_mtx_pi")
        if key in out:
            out[key]["pi_pass_total"]  = sum(p for p, _ in pi_list)
            out[key]["pi_total_total"] = sum(t for _, t in pi_list)
    return out, meta_by


def write_aggregate_csv(agg: dict, meta_by: dict, profile: str,
                        out_path: Path) -> None:
    L = ["rtos,rtos_version,profile,test,source,n_runs," +
         ",".join(STAT_FIELDS) +
         ",run_min,run_max,run_spread," +
         "median_us,p99_us,pi_passed_total,pi_total_total,pi_source"]
    for (rtos, prof, test), st in sorted(agg.items()):
        if prof != profile:
            continue
        meta = meta_by.get((rtos, prof), {})
        version = kernel_label(meta)
        source = source_by_test(test, meta.get("__publication_mode"))
        row = [rtos, version, prof, test, source, str(st["n_runs"])]
        row += [str(st[f]) for f in STAT_FIELDS]
        row += [str(st["run_min"]), str(st["run_max"]),
                str(st["run_spread"])]
        row.append(f"{cycles_to_us(st['median']):.6f}")
        row.append(f"{cycles_to_us(st['p99']):.6f}")
        row.append(str(st.get("pi_pass_total", "")))
        row.append(str(st.get("pi_total_total", "")))
        row.append(T4_PI_SOURCE if test == "t4_mtx_pi" else "")
        L.append(",".join(row))
    out_path.write_text("\n".join(L) + "\n", encoding="utf-8")


def write_aggregate_md(agg: dict, meta_by: dict, profile: str,
                       out_path: Path,
                       publication_gated: bool) -> None:
    L = [f"# Aggregate summary — profile `{profile}`",
         ""]
    if not publication_gated:
        L.append(EXPLORATORY_BANNER)
    L.extend([
        "Each cell is the **median across the N runs** of that "
        "stat field (ADR-013 multi-run rule). A single bad run "
        "cannot bias the published number.",
        "",
        f"CPU clock assumed: {SYS_CLOCK_HZ/1e6:.0f} MHz",
        ""])
    # Kernel label manifest — read at runtime from each RTOS's own
    # version macro (ChibiOS CH_KERNEL_VERSION, FreeRTOS
    # tskKERNEL_VERSION_NUMBER, Zephyr KERNEL_VERSION_STRING) and
    # combined with the product name in benchmark_stats.c.
    kernels = [(rtos, kernel_label(meta_by[(rtos, profile)]) or "?",
                meta_by[(rtos, profile)].get("__version_consistent", True))
               for (rtos, p) in sorted(meta_by) if p == profile]
    if kernels:
        L.append("## RTOS kernels (this profile)")
        L.append("")
        L.append("| rtos | kernel | consistent across runs |")
        L.append("|------|--------|------------------------|")
        for rtos, lbl, ok in kernels:
            L.append(f"| {rtos} | `{lbl}` | "
                     f"{'yes' if ok else '**NO — different kernels seen**'} |")
        L.append("")
    L.extend(["| rtos     | test          | source           | n_runs "
              "| median | p95 | p99 | max | jitter | "
              "run_min | run_max | run_spread "
              "| mean | stddev | median (us) | p99 (us) |",
              "|----------|---------------|------------------|-------:"
              "|-------:|----:|----:|----:|-------:|"
              "--------:|--------:|-----------:"
              "|-----:|-------:|------------:|---------:|"])
    for (rtos, prof, test), st in sorted(agg.items()):
        if prof != profile:
            continue
        pm = meta_by.get((rtos, prof), {}).get("__publication_mode")
        source = source_by_test(test, pm)
        L.append(
            f"| {rtos:<8} | {test:<13} | {source:<16} "
            f"| {st['n_runs']:>6} "
            f"| {st['median']:>6} | {st['p95']:>3} | {st['p99']:>3} "
            f"| {st['max']:>3} | {st['jitter']:>6} "
            f"| {st['run_min']:>7} | {st['run_max']:>7} "
            f"| {st['run_spread']:>10} "
            f"| {st['mean']:>4} | {st['stddev']:>6} "
            f"| {cycles_to_us(st['median']):>11.3f} "
            f"| {cycles_to_us(st['p99']):>8.3f} |"
        )
    # PI summary
    pi_lines = [(rtos, st.get("pi_pass_total", 0),
                 st.get("pi_total_total", 0))
                for (rtos, prof, test), st in sorted(agg.items())
                if prof == profile and test == "t4_mtx_pi"
                and st.get("pi_total_total", 0) > 0]
    if pi_lines:
        L.append("")
        L.append("## T4 priority inheritance — aggregate")
        L.append("")
        L.append("| rtos     | passed / total |")
        L.append("|----------|---------------:|")
        for rtos, p, t in pi_lines:
            L.append(f"| {rtos:<8} | {p} / {t} |")
    L.append("")
    out_path.write_text("\n".join(L), encoding="utf-8")


# === Cross-RTOS compare ==============================================

def write_compare_md(agg: dict, meta_by: dict, profile: str,
                     out_path: Path,
                     publication_gated: bool) -> None:
    rtos_present = sorted({rtos for (rtos, p, _) in agg if p == profile})
    if not rtos_present:
        out_path.write_text(f"# Compare — profile `{profile}`\n\n"
                            "No data.\n", encoding="utf-8")
        return

    L = [f"# Cross-RTOS compare — profile `{profile}`",
         ""]
    if not publication_gated:
        L.append(EXPLORATORY_BANNER)

    # Compare-md source attribution (Codex round-3 2a-bis
    # followup, ADR-015). The compare table is the most likely
    # output to be quoted out of context, so it carries an
    # explicit per-mode declaration of what TEST 1 actually is.
    # Else (unknown / mixed): the exploratory banner above
    # already warns the reader; no further attribution
    # (the executive overview-md emits an explicit "unknown"
    # paragraph instead).
    modes = {meta_by.get((rtos, profile), {}).get("__publication_mode")
             for rtos in rtos_present}
    modes.discard(None)
    if modes == {"dwt_only"}:
        L.append(SOURCE_ATTRIBUTION_BY_MODE["dwt_only"])
        L.append("")
    elif modes == {"la"}:
        L.append(SOURCE_ATTRIBUTION_BY_MODE["la"])
        L.append("")

    L.extend([
        f"Median across runs, in cycles. `(us)` columns at the right "
        f"convert via {SYS_CLOCK_HZ/1e6:.0f} MHz CPU clock.",
        ""])
    # Header table with the kernel actually used per RTOS port.
    L.append("## Kernels")
    L.append("")
    L.append("| rtos | kernel |")
    L.append("|------|--------|")
    for rtos in rtos_present:
        lbl = kernel_label(meta_by.get((rtos, profile), {})) or "?"
        L.append(f"| {rtos} | `{lbl}` |")
    L.append("")

    head = ["test", "metric"] + rtos_present + \
           [f"{r} (us)" for r in rtos_present]
    sep  = ["----", "----"] + ["---:" for _ in rtos_present] * 2
    L.append("| " + " | ".join(head) + " |")
    L.append("|" + "|".join(sep) + "|")

    # Pick a small set of "headline" stat rows per test.
    headline = ("median", "p95", "p99", "max", "jitter")
    for test in TESTS:
        for stat in headline:
            cells_cyc = []
            cells_us  = []
            for rtos in rtos_present:
                st = agg.get((rtos, profile, test))
                if not st:
                    cells_cyc.append("-")
                    cells_us.append("-")
                else:
                    cells_cyc.append(f"{st[stat]}")
                    cells_us.append(f"{cycles_to_us(st[stat]):.3f}")
            row = [test, stat] + cells_cyc + cells_us
            L.append("| " + " | ".join(row) + " |")
    out_path.write_text("\n".join(L) + "\n", encoding="utf-8")


# === Executive overview (2026-05-13) =================================

def _resolve_publication_mode(meta_by: dict, profile: str,
                              rtos_present: list[str]) -> str:
    """Return the unique publication_mode declared by the
    runs of @p profile, or 'unknown' if 0 or >1 distinct
    values are present. Codex round-3 overview-md design:
    validated.json (per-run) wins; the campaign lock is
    audit-only and never silently overrides the runs."""
    modes = {meta_by.get((rtos, profile), {}).get(
                 "__publication_mode")
             for rtos in rtos_present}
    modes.discard(None)
    if modes == {"dwt_only"}:
        return "dwt_only"
    if modes == {"la"}:
        return "la"
    return "unknown"


CONFIG_FIELDS = (
    ("kernel",       lambda m: kernel_label(m) or "?"),
    ("system_clock", lambda m: m.get("SystemClock", "?")),
    ("vos_level",    lambda m: m.get("VOS level", "?")),
    ("vosrdy",       lambda m: m.get("VOSRDY", "?")),
    ("flash_acr",    lambda m: m.get("FLASH_ACR", "?")),
    ("icache",       lambda m: m.get("ICache", "?")),
    ("dcache",       lambda m: m.get("DCache", "?")),
    ("tickless",     lambda m: m.get("Tickless", "?")),
    ("wfi_in_idle",  lambda m: m.get("WFI in idle", "?")),
    ("optimization", lambda m: m.get("Optimization", "?")),
)


def write_overview_md(agg: dict, meta_by: dict, profile: str,
                      out_path: Path,
                      publication_gated: bool,
                      lock_data: dict | None) -> None:
    """Codex round-3 overview-md (PLAN APPROVE_WITH_CHANGES,
    2026-05-13): emit a single executive-level summary that
    consolidates publication state, configuration snapshot,
    headline median-of-medians (with tail p99 and
    run_spread), T4 PI status, and pointers to the detailed
    files. Numbers come exclusively from @p agg / @p meta_by;
    no re-aggregation. @p lock_data is the optional
    campaign-lock JSON (None when missing/malformed)."""
    rtos_present = sorted({rtos for (rtos, p, _) in agg
                           if p == profile})
    if not rtos_present:
        out_path.write_text(
            f"# Overview — profile `{profile}`\n\n"
            "No data.\n", encoding="utf-8")
        return

    resolved_mode = _resolve_publication_mode(
        meta_by, profile, rtos_present)

    L = [f"# Overview — profile `{profile}`", ""]
    if not publication_gated:
        L.append(EXPLORATORY_BANNER)
        L.append("")

    # 1. Header line.
    gated_str = "yes" if publication_gated else "no"
    L.append(f"- publication-gated = {gated_str}")
    L.append(f"- publication mode = {resolved_mode}")
    if lock_data is not None:
        ts = lock_data.get("timestamp_utc", "")
        if ts:
            L.append(f"- Campaign lock timestamp: {ts}")
        lock_mode = lock_data.get("publication_mode")
        if (lock_mode and resolved_mode in ("la", "dwt_only")
                and lock_mode != resolved_mode):
            L.append(
                f"- WARNING: campaign lock mode {lock_mode!r} "
                f"differs from validated run mode "
                f"{resolved_mode!r}; the validated run mode "
                f"wins.")
    L.append("")

    # 2. Source attribution paragraph (shared with compare-md).
    L.append(SOURCE_ATTRIBUTION_BY_MODE[resolved_mode])
    L.append("")

    # 3. Configuration snapshot.
    L.append("## Configuration snapshot")
    L.append("")
    header = ["field"] + rtos_present
    sep    = ["----"] + ["---" for _ in rtos_present]
    L.append("| " + " | ".join(header) + " |")
    L.append("|" + "|".join(sep) + "|")
    for fname, fgetter in CONFIG_FIELDS:
        row = [fname]
        for rtos in rtos_present:
            row.append(str(fgetter(meta_by.get((rtos, profile), {}))))
        L.append("| " + " | ".join(row) + " |")
    # ELF SHA short prefix from the campaign lock (audit-only).
    sha_row = ["elf_sha256"]
    rtoses_map = {}
    if lock_data is not None:
        maybe = lock_data.get("rtoses")
        if isinstance(maybe, dict):
            rtoses_map = maybe
    for rtos in rtos_present:
        sha = ""
        entry = rtoses_map.get(rtos)
        if isinstance(entry, dict):
            cand = entry.get("elf_sha256", "")
            if isinstance(cand, str):
                sha = cand
        if sha:
            sha_row.append(f"`{sha[:8]}...`")
        else:
            sha_row.append("(not recorded)")
    L.append("| " + " | ".join(sha_row) + " |")
    L.append("")

    # 4. Headline table — median + p99 + run_spread + source.
    L.append("## Headline — median-of-medians per (rtos, test)")
    L.append("")
    L.append("| rtos     | test          | median (cyc) | median (us) "
             "| p99 (cyc) | p99 (us) | run_spread (cyc) | source           |")
    L.append("|----------|---------------|-------------:|------------:"
             "|----------:|---------:|-----------------:|------------------|")
    pm_for_source = (resolved_mode
                     if resolved_mode in ("la", "dwt_only")
                     else None)
    for (rtos, prof, test), st in sorted(agg.items()):
        if prof != profile:
            continue
        source = source_by_test(test, pm_for_source)
        L.append(
            f"| {rtos:<8} | {test:<13} "
            f"| {st['median']:>12} "
            f"| {cycles_to_us(st['median']):>11.3f} "
            f"| {st['p99']:>9} "
            f"| {cycles_to_us(st['p99']):>8.3f} "
            f"| {st['run_spread']:>16} "
            f"| {source:<16} |")
    L.append("")

    # 5. T4 PI aggregate (mode-independent: firmware seq check).
    pi_lines = [(rtos, st.get("pi_pass_total", 0),
                 st.get("pi_total_total", 0))
                for (rtos, prof, test), st in sorted(agg.items())
                if prof == profile and test == "t4_mtx_pi"
                and st.get("pi_total_total", 0) > 0]
    if pi_lines:
        L.append("## TEST 4 priority inheritance")
        L.append("")
        L.append("| rtos     | passed / total |")
        L.append("|----------|---------------:|")
        for rtos, p, t in pi_lines:
            L.append(f"| {rtos:<8} | {p} / {t} |")
        L.append("")

    # 6. Pointers to the detailed outputs.
    L.append("## Details")
    L.append("")
    L.append("- Per-run summaries: "
             f"`<rtos>_{profile}_run0[1-5]_summary.md`")
    L.append(f"- Aggregate: `{profile}_aggregate.md` / "
             f"`{profile}_aggregate.csv`")
    L.append(f"- Compare: `{profile}_compare.md`")
    L.append(f"- Charts: `../plots/{profile}_*.png`")
    L.append(f"- Campaign lock: "
             f"`../manifest/{profile}_campaign.lock.json`")
    L.append("")

    out_path.write_text("\n".join(L), encoding="utf-8")


# === Main =============================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Generate official summary tables (round-9 C1)."
    )
    p.add_argument("--profile",
                   choices=["fair_perf", "realistic_tickless",
                            "debug_dev"],
                   help="Restrict to one profile (default: all).")
    p.add_argument("--input-dir",  default=str(DEFAULT_IN_DIR),
                   help="Directory holding the validated <run>.csv "
                        "files (default: results/raw).")
    p.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR),
                   help="Directory for the summary outputs "
                        "(default: results/summary).")
    p.add_argument("--publication-gate", action="store_true",
                   help="Round-11 §5: refuse to write a report if the "
                        "input does not cover all 3 RTOSes with "
                        "run01..run05 present and a companion "
                        "<prefix>.validated.json (= validated by "
                        "collect_results.py). Use this for the "
                        "final publication build only.")
    args = p.parse_args(argv)

    in_dir  = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    # 2026-05-13 overview-md: campaign lock files live in a
    # sibling 'manifest' dir by convention
    # (results/raw -> results/manifest).
    manifest_dir = in_dir.parent / "manifest"
    if not in_dir.is_dir():
        print(f"ERROR: input dir not found: {in_dir}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = discover_runs(in_dir, args.profile)
    if not runs:
        filt = f" (profile={args.profile})" if args.profile else ""
        print(f"WARNING: no run files matched in {in_dir}{filt}",
              file=sys.stderr)
        return 1

    if args.publication_gate:
        warmup_dict = discover_warmup_runs(in_dir,
                                           args.profile)
        gate_errs = check_publication_gate(runs, warmup_dict)
        if gate_errs:
            print("PUBLICATION GATE FAILED:", file=sys.stderr)
            for err in gate_errs:
                print(f"  - {err}", file=sys.stderr)
            return 3

    pub_gated = bool(args.publication_gate)

    # --- per-run summaries ---
    per_run = []
    for rtos, profile, run_id, csv_path, t4pi_path in runs:
        s = per_run_summary(rtos, profile, run_id, csv_path, t4pi_path)
        per_run.append(s)
        stem = f"{rtos}_{profile}_run{run_id}_summary"
        write_per_run_summary_md(s, out_dir / f"{stem}.md",
                                 publication_gated=pub_gated)
        write_per_run_summary_csv(s, out_dir / f"{stem}.csv")

    # --- aggregates and compare per profile ---
    agg, meta_by = aggregate(per_run)
    profiles_seen = sorted({s["profile"] for s in per_run})
    for prof in profiles_seen:
        write_aggregate_csv(agg, meta_by, prof,
                            out_dir / f"{prof}_aggregate.csv")
        write_aggregate_md(agg, meta_by, prof,
                           out_dir / f"{prof}_aggregate.md",
                           publication_gated=pub_gated)
        write_compare_md(agg, meta_by, prof,
                         out_dir / f"{prof}_compare.md",
                         publication_gated=pub_gated)
        # 2026-05-13 overview-md: single executive page that
        # consolidates publication state, configuration,
        # headline numbers, T4 PI, and pointers. Campaign lock
        # is audit-only (may be absent in exploratory runs).
        lock_data = load_campaign_lock(prof, manifest_dir)
        write_overview_md(agg, meta_by, prof,
                          out_dir / f"{prof}_overview.md",
                          publication_gated=pub_gated,
                          lock_data=lock_data)

    # --- console summary ---
    print(f"Generated reports for {len(per_run)} run(s):")
    for s in per_run:
        n_tests = len(s["tests"])
        print(f"  {s['rtos']:<8} {s['profile']:<19} "
              f"run{s['run_id']:<4} ({n_tests} tests"
              + (f", PI {s['pi_pass']}/{s['pi_total']})"
                 if s['pi_total'] else ")"))
    print(f"Aggregate / compare: {len(profiles_seen)} profile(s) -> "
          f"{out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
