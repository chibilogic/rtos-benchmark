#!/usr/bin/env python3
"""
Cross-RTOS configuration alignment gate (pre-flight for the lab
harness, scaffold).

Verifies that the three RTOS configuration files honour the
binding contracts of ADR-009 (baseline configuration),
ADR-011 (publishable profiles), and ADR-022 (kernel feature
equivalence). Fail-stops with exit code 2 on ANY drift so the
lab harness never runs a benchmark on a regressed kernel
configuration.

Two layers of checking:

  1. Source layer (always run).
     Parses chconf.h, FreeRTOSConfig.h, prj.conf +
     conf/<profile>.conf. Each option in the project contract is
     looked up against an authoritative value (or value set).

  2. Build-layer artefact scans (run if the artefact exists).
     Two artefact families today:
       (a) ChibiOS ELF symbol scan via `arm-none-eabi-nm`:
           required kernel symbols (chSem*, chMtx*, chThdWait)
           must be present; ADR-022-forbidden OSLIB / Factory /
           TM / event subsystem symbols must be absent.
       (b) Zephyr generated `.config` scan: every contracted
           CONFIG_* (ZEPHYR_PRJ_CONTRACT + per-profile contracts
           + Kconfig-selected entries from ZEPHYR_PROFILE_
           GENERATED_CONTRACT) must match the effective build
           output. Catches Kconfig defaults that bypass the
           source-fragment merge AND ADR-024 negative-contract
           regressions (e.g. CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK
           accidentally selected for realistic_tickless).
     Together the two artefact scans detect "I edited the
     config but forgot to rebuild", "I rebuilt but the chconf.h
     on disk is old", and "a Kconfig select crept in that
     violates the WFI parity contract".

This gate is invoked from `scripts/lab_runner.py` (the
cross-platform orchestrator) in three places:
  - cmd_build_only / cmd_smoke / cmd_campaign call
    do_config_alignment_check(profile, source_only=True) BEFORE
    the build (Codex round 2 BLOCKER 1: stale build-layer
    artefacts must not block a corrective rebuild);
  - the same dispatchers call it again with source_only=False AFTER
    the build, so the build-layer artefact scans (ChibiOS ELF
    symbol scan + Zephyr generated `.config` scan) run on the
    freshly-built artefacts.
The lab_smoke.ps1 / lab_campaign.ps1 wrappers exec lab_runner.py
unchanged. Two-phase gate semantics: a source-only failure stops
the pipeline BEFORE any build happens; a full-mode failure stops
the pipeline BEFORE any flash or measurement happens (the build
itself sits between the two checks).

Status: SCAFFOLD. The contract data below mirrors ADR-022 +
ADR-009 + ADR-011 as of 2026-05-21. Future ADRs that revise the
configuration must keep this script in sync; the contract is
flagged as a single CONTRACT block to keep the diff visible to
Codex and future reviewers.

Exit codes:
  0  every checked option matches the contract; ELFs (if any)
     are symbol-consistent.
  2  at least one option drifted, or a forbidden/required symbol
     is in the wrong state; details printed to stderr in
     fail-stop fashion (every failure listed, NOT just the first).

Usage:
    python scripts/config_alignment_check.py --profile fair_perf

    # source-only (skip the ELF symbol scan even if ELFs exist):
    python scripts/config_alignment_check.py --profile fair_perf --source-only

    # check both publishable profiles in one go (common CI use):
    python scripts/config_alignment_check.py --all-profiles

ADR references: ADR-009 (baseline), ADR-011 (profiles),
ADR-014 (test specs that rely on these primitives),
ADR-022 (kernel feature equivalence; primary source of the
contract).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT_DEFAULT = Path(__file__).resolve().parent.parent

PUBLISHABLE_PROFILES = ("fair_perf", "realistic_tickless")

# ----------------------------------------------------------------------
# CONTRACT: mirrors ADR-022 / ADR-009 / ADR-011 (2026-05-21).
# Any change here MUST be matched by an ADR update + Codex review.
# ----------------------------------------------------------------------

# ChibiOS chconf.h: option_name -> expected_value (TRUE / FALSE)
# or a tuple of acceptable values. The expected_value column is the
# textual literal exactly as it appears in chconf.h.
CHIBIOS_CHCONF_CONTRACT: dict[str, str] = {
    # Required ON (ADR-022): used by the 4 tests.
    "CH_CFG_USE_SEMAPHORES":         "TRUE",
    "CH_CFG_USE_MUTEXES":            "TRUE",
    "CH_CFG_USE_WAITEXIT":           "TRUE",   # T2 cleanup
    "CH_CFG_OPTIMIZE_SPEED":         "TRUE",   # ADR-009 baseline
    # Required OFF (ADR-022): not used by any of the 4 tests.
    "CH_CFG_USE_TM":                 "FALSE",
    "CH_CFG_USE_TIMESTAMP":          "FALSE",
    "CH_CFG_USE_REGISTRY":           "FALSE",
    "CH_CFG_USE_CONDVARS":           "FALSE",
    "CH_CFG_USE_CONDVARS_TIMEOUT":   "FALSE",
    "CH_CFG_USE_EVENTS":             "FALSE",
    "CH_CFG_USE_EVENTS_TIMEOUT":     "FALSE",
    "CH_CFG_USE_MESSAGES":           "FALSE",
    "CH_CFG_USE_DYNAMIC":            "FALSE",
    "CH_CFG_USE_MAILBOXES":          "FALSE",
    "CH_CFG_USE_MEMCORE":            "FALSE",
    "CH_CFG_USE_HEAP":               "FALSE",
    "CH_CFG_USE_MEMPOOLS":           "FALSE",
    "CH_CFG_USE_OBJ_FIFOS":          "FALSE",
    "CH_CFG_USE_PIPES":              "FALSE",
    "CH_CFG_USE_OBJ_CACHES":         "FALSE",
    "CH_CFG_USE_DELEGATES":          "FALSE",
    "CH_CFG_USE_JOBS":               "FALSE",
    "CH_CFG_USE_FACTORY":            "FALSE",
    # Sub-flags that ChibiOS gates under USE_FACTORY (hygiene per
    # ADR-022 Codex MIN-1).
    "CH_CFG_FACTORY_OBJECTS_REGISTRY": "FALSE",
    "CH_CFG_FACTORY_GENERIC_BUFFERS":  "FALSE",
    "CH_CFG_FACTORY_SEMAPHORES":       "FALSE",
    "CH_CFG_FACTORY_MAILBOXES":        "FALSE",
    "CH_CFG_FACTORY_OBJ_FIFOS":        "FALSE",
    "CH_CFG_FACTORY_PIPES":            "FALSE",
    # Other parameters that affect benchmark semantics.
    "CH_CFG_USE_MUTEXES_RECURSIVE":    "FALSE",
    "CH_CFG_USE_SEMAPHORES_PRIORITY":  "FALSE",
    "CH_CFG_USE_MESSAGES_PRIORITY":    "FALSE",
    "CH_CFG_NO_IDLE_THREAD":           "FALSE",
    "CH_CFG_SMP_MODE":                 "FALSE",
    "CH_CFG_TIME_QUANTUM":             "0",      # round-robin OFF (ADR-009)
    "CH_CFG_ST_FREQUENCY":             "1000",   # ADR-009 / ADR-013
    "CH_CFG_ST_RESOLUTION":            "32",
    # ADR-009 hard rule: no asserts / checks / debug / trace.
    "CH_DBG_STATISTICS":               "FALSE",
    "CH_DBG_SYSTEM_STATE_CHECK":       "FALSE",
    "CH_DBG_ENABLE_CHECKS":            "FALSE",
    "CH_DBG_ENABLE_ASSERTS":           "FALSE",
    "CH_DBG_ENABLE_STACK_CHECK":       "FALSE",
    "CH_DBG_FILL_THREADS":             "FALSE",
    "CH_DBG_THREADS_PROFILING":        "FALSE",
}

# FreeRTOSConfig.h: option_name -> expected_value as the literal
# token, after stripping parentheses, whitespace, and `( TickType_t )`
# / `( size_t )` style casts. Values are parsed as Python ints
# when comparable; expected_value here is a string but
# `_check_freertos` does smart-numeric compare.
FREERTOS_CONFIG_CONTRACT: dict[str, str] = {
    # Scheduler (ADR-009).
    "configUSE_PREEMPTION":                    "1",
    "configUSE_TIME_SLICING":                  "0",
    "configTICK_RATE_HZ":                      "1000",
    # Primitives (ADR-022).
    "configUSE_MUTEXES":                       "1",
    "configUSE_RECURSIVE_MUTEXES":             "0",
    "configUSE_COUNTING_SEMAPHORES":           "1",
    "configUSE_TASK_NOTIFICATIONS":            "1",
    "configTASK_NOTIFICATION_ARRAY_ENTRIES":   "1",
    # Hard rule (ADR-009): no asserts / checks / debug / trace / hooks.
    "configUSE_IDLE_HOOK":                     "0",
    "configUSE_TICK_HOOK":                     "0",
    "configUSE_MALLOC_FAILED_HOOK":            "0",
    "configCHECK_FOR_STACK_OVERFLOW":          "0",
    "configUSE_TRACE_FACILITY":                "0",
    "configGENERATE_RUN_TIME_STATS":           "0",
    "configRECORD_STACK_HIGH_ADDRESS":         "0",
    "configUSE_STATS_FORMATTING_FUNCTIONS":    "0",
    "configUSE_DAEMON_TASK_STARTUP_HOOK":      "0",
    # Static-only allocation (ADR-022 + project hard rule).
    "configSUPPORT_DYNAMIC_ALLOCATION":        "0",
    "configSUPPORT_STATIC_ALLOCATION":         "1",
    # No timer task, no co-routines.
    "configUSE_TIMERS":                        "0",
    "configUSE_CO_ROUTINES":                   "0",
    "configQUEUE_REGISTRY_SIZE":               "0",
    # Thread names off (ADR-022).
    "configMAX_TASK_NAME_LEN":                 "1",
}

# Zephyr prj.conf: option -> expected token (`y`, `n`, or numeric).
ZEPHYR_PRJ_CONTRACT: dict[str, str] = {
    # ADR-009 hard rule.
    "CONFIG_ASSERT":                       "n",
    "CONFIG_LOG":                          "n",
    "CONFIG_TRACING":                      "n",
    "CONFIG_DEBUG":                        "n",
    "CONFIG_STACK_SENTINEL":               "n",
    "CONFIG_THREAD_NAME":                  "n",
    "CONFIG_THREAD_MONITOR":               "n",
    "CONFIG_THREAD_RUNTIME_STATS":         "n",
    # Scheduler (ADR-009).
    "CONFIG_TIMESLICING":                  "n",
    "CONFIG_SYS_CLOCK_TICKS_PER_SEC":      "1000",
    # ADR-009 / ADR-011: -O2, no LTO, no -Os.
    "CONFIG_SPEED_OPTIMIZATIONS":          "y",
    "CONFIG_SIZE_OPTIMIZATIONS":           "n",
    "CONFIG_LTO":                          "n",
    # ADR-022 Codex round 1 IMP-2 fix.
    "CONFIG_HEAP_MEM_POOL_SIZE":           "0",
    "CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE":  "512",
}

# ChibiOS chconf.h profile-conditional contract (ADR-024).
# These macros live inside `#if defined(BENCH_PROFILE_<UPPER>)` /
# `#else` / `#endif` blocks. parse_c_defines() with last-wins
# semantics cannot distinguish the branches; the helper
# `_extract_chibios_profile_conditional()` below parses the
# preprocessor structure directly.
CHIBIOS_CHCONF_PROFILE_CONTRACT: dict[str, dict[str, str]] = {
    "fair_perf": {
        "CORTEX_ENABLE_WFI_IDLE": "FALSE",
    },
    "realistic_tickless": {
        "CORTEX_ENABLE_WFI_IDLE": "TRUE",
    },
}

# Zephyr per-profile conf/<profile>.conf: profile -> option -> expected.
# These symbols MUST appear in the source `.conf` files (and will
# also appear in the generated `.config`).
#   realistic_tickless: CONFIG_PM removed by ADR-024 (PM has no
#     ChibiOS/FreeRTOS analog; was also silently dropped by Kconfig
#     for unmet deps).
ZEPHYR_PROFILE_CONTRACT: dict[str, dict[str, str]] = {
    "fair_perf": {
        "CONFIG_BENCH_PROFILE_FAIR_PERF":           "y",
        "CONFIG_TICKLESS_KERNEL":                   "n",
        "CONFIG_PM":                                "n",
    },
    "realistic_tickless": {
        "CONFIG_BENCH_PROFILE_REALISTIC_TICKLESS":  "y",
        "CONFIG_TICKLESS_KERNEL":                   "y",
    },
}

# Zephyr Kconfig-selected (per ADR-024): symbols that the project
# Kconfig `select`s from the profile bool, so they appear in the
# generated `.config` but NOT in the source `.conf` files. Checked
# ONLY against the generated `.config` (build-layer), NEVER against
# the source merge. The upstream Kconfig symbol
# `CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK` is declared as a non-visible
# `bool` (no string label) in `arch/arm/Kconfig` and is only settable
# via `select`/`imply`; the project Kconfig selects it from
# `BENCH_PROFILE_FAIR_PERF` and `BENCH_PROFILE_DEBUG_DEV`.
ZEPHYR_PROFILE_GENERATED_CONTRACT: dict[str, dict[str, str]] = {
    "fair_perf": {
        "CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK":        "y",
    },
    "realistic_tickless": {
        # Codex round 7 IMP-1: explicit negative contract.
        # The hook MUST NOT be selected for realistic_tickless
        # so arch_cpu_idle keeps its native WFI behaviour. A
        # future project-Kconfig regression that adds
        # `select ARM_ON_ENTER_CPU_IDLE_HOOK` to BENCH_PROFILE_
        # REALISTIC_TICKLESS would silently break ADR-024
        # without this entry. The .config scan tolerates the
        # symbol being absent (Kconfig omits unset `bool`
        # symbols entirely) per the existing `n`-default
        # tolerance, so this entry catches the regression
        # without false positives on the legitimate "absent"
        # case.
        "CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK":        "n",
    },
}

# ELF symbol expectations (ChibiOS only; FreeRTOS / Zephyr do not
# expose comparable forbidden/required symbol pairs in their .map
# because their feature switches do not leave dead symbols behind).
#
# Note on chBSem*: binary-semaphore APIs (`chBSemObjectInit`,
# `chBSemWait`, `chBSemSignal`) are static inline wrappers over the
# counting `chSem*` family in `chbsem.h`. They are inlined at every
# call site and NEVER emit linker symbols, so they cannot appear in
# this list. The presence of the chSem* family is the actual proof
# that semaphore support is linked.
CHIBIOS_ELF_REQUIRED_SYMBOLS = (
    "chSemObjectInit", "chSemWait", "chSemSignal",
    "chMtxObjectInit", "chMtxLock", "chMtxUnlock",
    "chThdWait",
)

# Forbidden ChibiOS kernel symbols: if present in the ELF, the build
# is linking an OSLIB / factory / TM / event subsystem that was
# supposed to be disabled by chconf.h. Substring match: any symbol
# starting with these tokens triggers a failure.
CHIBIOS_ELF_FORBIDDEN_PREFIXES = (
    "chFactory",
    "chMBPost", "chMBFetch", "chMBObjectInit",
    "chHeapAlloc", "chHeapFree",
    "chTMObjectInit", "chTMStartMeasurement", "chTMStopMeasurement",
    "chPipeWrite", "chPipeRead", "chPipeObjectInit",
    "chEvtSignal", "chEvtBroadcast", "chEvtRegister",
    "chPoolAlloc", "chPoolFree",
    "chCondWait", "chCondSignal",
    "chMsgSend", "chMsgWait", "chMsgRelease",
    "chTimeStamp",
)

# Cross-port T1 timer IRQ priority (ADR-014): the TIM2 interrupt MUST be
# configured at the same logical NVIC priority in all three ports, else the
# IRQ -> thread latency comparison (T1) is unfair. Source-layer check.
TIM2_IRQ_PRIORITY = "7"


# ----------------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------------

# Captures `#define NAME VALUE` with optional parentheses around VALUE.
# The value is whatever follows NAME on the same line, with leading
# whitespace stripped and trailing comments / line continuations
# removed.
_C_DEFINE_RE = re.compile(
    r"^\s*#\s*define\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<value>.+?)\s*$"
)


def _normalize_c_value(raw: str) -> str:
    """Strip trailing comments, parentheses, casts, and whitespace.

    Cases (project-real):
      `TRUE`                          -> `TRUE`
      `( 16 )`                        -> `16`
      `( ( uint16_t ) 256 )`          -> `256`
      `( ( size_t ) ( 1 * 1024 ) )`   -> `1 * 1024`
      `FALSE  // dead code`           -> `FALSE`
      `1   /* note */`                -> `1`

    Strategy: strip comments, then iterate
    (strip-casts -> strip-outer-parens) until stable. Stripping
    casts FIRST (before the outer-paren loop) is required for the
    nested-typecast case where the paren-loop alone would not
    recognise `( ( size_t ) ( 1 * 1024 ) )` as balanced (the two
    inner parens belong to different blocks, not nested). Finally,
    strip C integer-literal suffixes `[UuLl]+` (`1U`, `0x10UL`,
    `2ULL`) so numeric-aware comparison treats them as equal to
    their unsuffixed forms (Codex round 3 IMP-4)."""
    # Trailing C and C++ comments.
    raw = re.sub(r"/\*.*?\*/", "", raw)
    raw = re.sub(r"//.*$", "", raw)
    s = raw.strip()
    cast_re = re.compile(r"\(\s*[A-Za-z_][A-Za-z0-9_]*\s*\)\s*")
    for _ in range(8):   # bounded loop; 8 iterations cover any
                         # realistic nesting in our headers.
        new_s = cast_re.sub("", s).strip()
        # Strip a single balanced outer-paren pair, if present.
        while new_s.startswith("(") and new_s.endswith(")"):
            inner = new_s[1:-1].strip()
            if inner.count("(") != inner.count(")"):
                break
            new_s = inner
        if new_s == s:
            break
        s = new_s
    # Strip C integer-literal suffix (U, UL, ULL, L, LL, in any case).
    # Apply only when the rest of the token parses as an int so we do
    # not eat letters from non-numeric values like "TRUE".
    suffix_match = re.fullmatch(
        r"\s*(?P<num>[+-]?(?:0[xX][0-9a-fA-F]+|\d+))[UuLl]+\s*", s,
    )
    if suffix_match:
        s = suffix_match.group("num")
    return s.strip()


def parse_c_defines(path: Path) -> dict[str, str]:
    """Parse a C header for last-wins `#define NAME VALUE` lines.
    Returns the normalized value as a string. Wins-last semantics
    mirror the C preprocessor: a later `#define` overrides earlier
    ones (we ignore `#undef` for the moment; the contract macros
    are never `#undef`-ed in this project)."""
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = _C_DEFINE_RE.match(line)
        if not m:
            continue
        out[m.group("name")] = _normalize_c_value(m.group("value"))
    return out


_KCONF_LINE_RE = re.compile(
    r"^\s*(?P<name>CONFIG_[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+?)\s*$"
)


def parse_zephyr_conf(path: Path) -> dict[str, str]:
    """Parse a Zephyr Kconfig fragment. Trailing inline comments
    starting with `#` are stripped; `n` / `y` and unquoted integers
    are returned as-is; quoted strings have surrounding quotes
    stripped."""
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "#" in line:
            line = line.split("#", 1)[0]
        m = _KCONF_LINE_RE.match(line)
        if not m:
            continue
        v = m.group("value").strip()
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        out[m.group("name")] = v
    return out


# ----------------------------------------------------------------------
# Numeric-aware comparison
# ----------------------------------------------------------------------

def _eq(actual: str, expected: str) -> bool:
    """True if `actual` matches `expected` as integers (handling
    hex / decimal) or as case-sensitive strings."""
    if actual == expected:
        return True
    try:
        a = int(actual, 0)
        e = int(expected, 0)
        return a == e
    except ValueError:
        return False


# ----------------------------------------------------------------------
# Source-layer checks
# ----------------------------------------------------------------------

@dataclass
class FailureBag:
    failures: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.failures.append(msg)

    def ok(self) -> bool:
        return not self.failures


def _extract_chibios_profile_conditional(text: str, name: str,
                                          profile: str) -> str | None:
    """Find the value of a profile-conditional `#define NAME VALUE`
    in chconf.h text.

    Supports the project-standard pattern (ADR-024):

        #if defined(BENCH_PROFILE_REALISTIC_TICKLESS)
        #define NAME VALUE_TICKLESS
        #else
        #define NAME VALUE_NON_TICKLESS
        #endif

    Returns the value that applies for the requested profile, OR
    None if the pattern is not found.

    For profile == "realistic_tickless" -> returns VALUE_TICKLESS.
    For any other profile (fair_perf / debug_dev) -> returns
    VALUE_NON_TICKLESS.
    """
    # Match the canonical block with whitespace tolerance.
    pattern = (
        r"#\s*if\s+defined\(\s*BENCH_PROFILE_REALISTIC_TICKLESS\s*\)\s*\n"
        r"\s*#\s*define\s+" + re.escape(name) + r"\s+(?P<v_tickless>\S+).*?\n"
        r"\s*#\s*else\s*\n"
        r"\s*#\s*define\s+" + re.escape(name) + r"\s+(?P<v_default>\S+).*?\n"
        r"\s*#\s*endif"
    )
    m = re.search(pattern, text, re.DOTALL)
    if m is None:
        return None
    if profile == "realistic_tickless":
        return _normalize_c_value(m.group("v_tickless"))
    return _normalize_c_value(m.group("v_default"))


def check_chibios(project_root: Path, bag: FailureBag,
                  profile: str | None = None) -> None:
    """Verify chconf.h matches the ADR-022 + ADR-024 contract.

    The unconditional contract (`CHIBIOS_CHCONF_CONTRACT`) is
    always applied. The profile-conditional contract
    (`CHIBIOS_CHCONF_PROFILE_CONTRACT`) is applied only when
    `profile` is provided (typical call from run_one_profile).
    """
    path = project_root / "chibios" / "benchmark_chibios" / "cfg" / "chconf.h"
    if not path.exists():
        bag.add(f"chibios: chconf.h not found at {path}")
        return
    defs = parse_c_defines(path)
    for name, expected in CHIBIOS_CHCONF_CONTRACT.items():
        actual = defs.get(name)
        if actual is None:
            bag.add(f"chibios: {name} not defined (expected {expected!r})")
            continue
        if not _eq(actual, expected):
            bag.add(
                f"chibios: {name} = {actual!r} (expected {expected!r}). "
                f"Source: {path.relative_to(project_root)}"
            )

    # Profile-conditional contract (ADR-024 WFI parity).
    if profile is None:
        return
    profile_contract = CHIBIOS_CHCONF_PROFILE_CONTRACT.get(profile, {})
    if not profile_contract:
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    for name, expected in profile_contract.items():
        actual = _extract_chibios_profile_conditional(text, name, profile)
        if actual is None:
            bag.add(
                f"chibios ({profile}): profile-conditional define "
                f"{name!r} not found in chconf.h. Expected the "
                f"canonical ADR-024 pattern `#if defined(BENCH_"
                f"PROFILE_REALISTIC_TICKLESS) / #define {name} / "
                f"#else / #define {name} / #endif`."
            )
            continue
        if not _eq(actual, expected):
            bag.add(
                f"chibios ({profile}): {name} = {actual!r} (expected "
                f"{expected!r}). Source: "
                f"{path.relative_to(project_root)}"
            )


def check_freertos(project_root: Path, bag: FailureBag) -> None:
    path = (project_root / "freertos" / "benchmark_freertos" / "cfg"
            / "FreeRTOSConfig.h")
    if not path.exists():
        bag.add(f"freertos: FreeRTOSConfig.h not found at {path}")
        return
    defs = parse_c_defines(path)
    for name, expected in FREERTOS_CONFIG_CONTRACT.items():
        actual = defs.get(name)
        if actual is None:
            bag.add(f"freertos: {name} not defined (expected {expected!r})")
            continue
        if not _eq(actual, expected):
            bag.add(
                f"freertos: {name} = {actual!r} (expected {expected!r}). "
                f"Source: {path.relative_to(project_root)}"
            )


def _strip_c_comments(text: str) -> str:
    """Remove C block and line comments so commented-out code is not
    matched by source-pattern checks."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _check_tim2_call(path: Path, pattern: str, label: str,
                     want: str, bag: FailureBag) -> None:
    """Require EXACTLY ONE effective (comment-stripped) match of `pattern`
    capturing a priority literal equal to `want`; flag missing, duplicate,
    conflicting or wrong-value declarations."""
    if not path.exists():
        bag.add(f"tim2: {label} source not found: {path.name}")
        return
    hits = re.findall(pattern, _strip_c_comments(
        path.read_text(encoding="utf-8", errors="replace")))
    if len(hits) == 0:
        bag.add(f"tim2: {label} not found (expected exactly one, = {want!r})")
    elif len(hits) > 1:
        bag.add(f"tim2: {label} found {len(hits)} times {hits!r} "
                f"(expected exactly one)")
    elif not _eq(hits[0], want):
        bag.add(f"tim2: {label} = {hits[0]!r} (expected {want!r})")


def check_tim2_priority(project_root: Path, bag: FailureBag) -> None:
    """All three ports must configure the T1 TIM2 IRQ at the same logical
    NVIC priority (ADR-014). Source-layer, profile-independent: ChibiOS via
    the STM32_IRQ_TIM2_PRIORITY define (comment-safe via parse_c_defines),
    FreeRTOS via HAL_NVIC_SetPriority, Zephyr via IRQ_CONNECT (both matched on
    comment-stripped source, requiring exactly one declaration)."""
    want = TIM2_IRQ_PRIORITY
    ch = (project_root / "chibios" / "benchmark_chibios" / "cfg"
          / "mcuconf.h")
    if not ch.exists():
        bag.add("tim2: chibios mcuconf.h not found")
    else:
        chv = parse_c_defines(ch).get("STM32_IRQ_TIM2_PRIORITY")
        if chv is None or not _eq(chv, want):
            bag.add(
                f"tim2: chibios STM32_IRQ_TIM2_PRIORITY = {chv!r} "
                f"(expected {want!r}). Source: "
                f"chibios/benchmark_chibios/cfg/mcuconf.h"
            )
    _check_tim2_call(
        project_root / "freertos" / "benchmark_freertos"
        / "test_ctxsw_irq.c",
        r"HAL_NVIC_SetPriority\s*\(\s*TIM2_IRQn\s*,\s*(\d+)",
        "freertos HAL_NVIC_SetPriority(TIM2_IRQn, ...)", want, bag)
    _check_tim2_call(
        project_root / "zephyr" / "benchmark_zephyr" / "src"
        / "test_ctxsw_irq.c",
        r"IRQ_CONNECT\s*\(\s*TIM2_IRQn\s*,\s*(\d+)",
        "zephyr IRQ_CONNECT(TIM2_IRQn, ...)", want, bag)


def check_zephyr(project_root: Path, profile: str, bag: FailureBag,
                 source_only: bool = False,
                 build_layer_rtos: str = "all") -> None:
    """Zephyr Kconfig check with last-wins fragment merge
    (Codex round 2 IMP-2 fix; round 4 BLOCKER phase fix).

    West applies the per-profile conf AFTER prj.conf, so any
    `CONFIG_*` set in `conf/<profile>.conf` overrides prj.conf.
    The previous per-file check could pass even if the profile
    fragment regressed an option (e.g. setting
    `CONFIG_HEAP_MEM_POOL_SIZE=8192` again in the profile conf
    would have been silently accepted because the file-level
    parser only saw `CONFIG_HEAP_MEM_POOL_SIZE=0` in prj.conf).

    Two phases:
      1. Source layer: merge `prj.conf` + `conf/<profile>.conf`
         with last-wins semantics and apply BOTH contracts to the
         effective dict. ALWAYS runs (the source layer is the
         repo-wide ADR-022 contract).
      2. Build layer (opportunistic): if
         `zephyr/build/<profile>/zephyr/.config` exists, inspect
         the actually-generated Kconfig output and re-apply the
         contract. This catches Kconfig defaults that neither
         fragment set explicitly. Gated by
         `source_only=False AND build_layer_rtos in ("all", "zephyr")`
         per Codex round 4 BLOCKER: source-only mode MUST NOT
         read generated artefacts (chicken-and-egg with a stale
         .config that the rebuild would refresh), and single-RTOS
         flows targeting freertos/chibios MUST NOT fail on a
         stale Zephyr .config."""
    prj = (project_root / "zephyr" / "benchmark_zephyr" / "prj.conf")
    if not prj.exists():
        bag.add(f"zephyr: prj.conf not found at {prj}")
        return
    profile_conf = (project_root / "zephyr" / "benchmark_zephyr"
                    / "conf" / f"{profile}.conf")
    if not profile_conf.exists():
        bag.add(f"zephyr: per-profile conf not found at {profile_conf}")
        return

    defs_base = parse_zephyr_conf(prj)
    defs_override = parse_zephyr_conf(profile_conf)
    # Last-wins merge: profile conf overrides prj.conf.
    effective: dict[str, str] = {**defs_base, **defs_override}

    def _origin(name: str) -> Path:
        """Return the source file that last set `name`."""
        if name in defs_override:
            return profile_conf
        return prj

    for name, expected in ZEPHYR_PRJ_CONTRACT.items():
        actual = effective.get(name)
        if actual is None:
            bag.add(
                f"zephyr: {name} not defined in either prj.conf or "
                f"conf/{profile}.conf (expected {expected!r})"
            )
            continue
        if not _eq(actual, expected):
            src = _origin(name).relative_to(project_root)
            bag.add(
                f"zephyr: {name} = {actual!r} (expected {expected!r}). "
                f"Effective source (last-wins): {src}"
            )

    for name, expected in ZEPHYR_PROFILE_CONTRACT[profile].items():
        actual = effective.get(name)
        if actual is None:
            bag.add(
                f"zephyr/{profile}: {name} not defined "
                f"(expected {expected!r})"
            )
            continue
        if not _eq(actual, expected):
            src = _origin(name).relative_to(project_root)
            bag.add(
                f"zephyr/{profile}: {name} = {actual!r} "
                f"(expected {expected!r}). "
                f"Effective source (last-wins): {src}"
            )

    # Build-layer opportunistic check: if a Zephyr build exists,
    # the generated .config is the authoritative effective config
    # (includes Kconfig defaults). Discrepancies between fragments
    # and .config indicate the build is stale vs the source.
    # Codex round 3 IMP-1: apply BOTH the base contract AND the
    # per-profile contract to the generated .config (the previous
    # version only checked PRJ_CONTRACT, missing CONFIG_TICKLESS_
    # KERNEL / CONFIG_PM / CONFIG_BENCH_PROFILE_* drift).
    # Codex round 4 BLOCKER: gated by source_only AND build_layer_rtos.
    # In source-only mode, a stale .config from a previous build
    # must not block the rebuild that would refresh it; in
    # single-RTOS flows targeting freertos or chibios, a stale
    # Zephyr .config from a previous campaign must not fail the
    # current selective build.
    if source_only or build_layer_rtos not in ("all", "zephyr"):
        return
    dot_config = (project_root / "zephyr" / "build" / profile
                  / "zephyr" / ".config")
    if dot_config.exists():
        gen = parse_zephyr_conf(dot_config)
        # ADR-024: include ZEPHYR_PROFILE_GENERATED_CONTRACT here so
        # Kconfig-selected symbols (like CONFIG_ARM_ON_ENTER_CPU_IDLE
        # _HOOK) that never appear in source .conf fragments are still
        # verified in the generated .config build-layer artefact.
        all_contract: dict[str, str] = {
            **ZEPHYR_PRJ_CONTRACT,
            **ZEPHYR_PROFILE_CONTRACT[profile],
            **ZEPHYR_PROFILE_GENERATED_CONTRACT.get(profile, {}),
        }
        for name, expected in all_contract.items():
            actual = gen.get(name)
            if actual is None:
                # Kconfig may legitimately omit a `=n` symbol from
                # .config (it is the default value). Tolerate
                # missing entries only when expected == "n".
                if expected == "n":
                    continue
                bag.add(
                    f"zephyr/.config ({profile}): {name} not present "
                    f"in generated .config (expected {expected!r}). "
                    f"Rebuild Zephyr for this profile."
                )
                continue
            if not _eq(actual, expected):
                bag.add(
                    f"zephyr/.config ({profile}): {name} = {actual!r} "
                    f"(expected {expected!r}). Effective build config "
                    f"differs from contract. Rebuild Zephyr for this "
                    f"profile after fixing the source fragments."
                )


# ----------------------------------------------------------------------
# Build-layer check (ChibiOS ELF symbol presence/absence)
# ----------------------------------------------------------------------

def _need(tool: str) -> str | None:
    return shutil.which(tool)


_NM_LINE = re.compile(r"^[0-9a-fA-F]+\s+[A-Za-z?]\s+(?P<name>\S+)\s*$")


def _elf_symbols(elf_path: Path) -> list[str] | None:
    nm = _need("arm-none-eabi-nm")
    if nm is None:
        return None
    out = subprocess.run(
        [nm, str(elf_path)],
        check=False, capture_output=True, text=True,
    )
    if out.returncode != 0:
        return None
    names: list[str] = []
    for line in out.stdout.splitlines():
        m = _NM_LINE.match(line)
        if m:
            names.append(m.group("name"))
    return names


def check_chibios_elf_symbols(project_root: Path, profile: str,
                              bag: FailureBag) -> None:
    elf = (project_root / "chibios" / "benchmark_chibios"
           / "build" / profile / "benchmark_chibios.elf")
    if not elf.exists():
        # Source-layer-only run is acceptable; the build layer is
        # opportunistic.
        return
    syms = _elf_symbols(elf)
    if syms is None:
        # nm not on PATH: downgrade to a printed warning, do NOT
        # fail the gate. The lab harness preflight (ADR-022 / Codex
        # round 2 IMP-5) explicitly requires arm-none-eabi-nm, so
        # the only legitimate path that reaches here is a developer
        # invoking the script standalone without env.bat/env.sh
        # activated. Failing in that case would prevent simple
        # source-side audits.
        sys.stderr.write(
            f"config_alignment_check: WARNING: arm-none-eabi-nm not "
            f"available on PATH; ChibiOS build-layer ELF check on "
            f"profile={profile!r} skipped. The lab harness adds nm "
            f"to required tools (Codex round 2 IMP-5); this warning "
            f"is only expected when running standalone without env."
            f"bat/env.sh, or with --source-only.\n"
        )
        return
    sym_set = set(syms)
    for required in CHIBIOS_ELF_REQUIRED_SYMBOLS:
        if required not in sym_set:
            bag.add(
                f"chibios ({profile}): required ELF symbol {required!r} "
                f"NOT present. Source may be ahead of build; rebuild "
                f"the profile. ELF: {elf.relative_to(project_root)}"
            )
    for prefix in CHIBIOS_ELF_FORBIDDEN_PREFIXES:
        hits = [s for s in syms if s.startswith(prefix)]
        if hits:
            bag.add(
                f"chibios ({profile}): forbidden ELF symbol(s) "
                f"{hits!r} present (prefix {prefix!r}). Build is "
                f"linking a kernel subsystem that ADR-022 disabled. "
                f"Rebuild after confirming chconf.h is current. ELF: "
                f"{elf.relative_to(project_root)}"
            )


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def run_one_profile(project_root: Path, profile: str,
                    source_only: bool,
                    build_layer_rtos: str = "all") -> FailureBag:
    """Run the gate for one profile.

    Source layer ALWAYS checks all three RTOS configs (the
    ADR-022 contract is repo-wide). Build-layer artefact scans
    are target-aware (Codex round 3 IMP-2 + round 4 BLOCKER):
    when `build_layer_rtos` is a specific RTOS, only that RTOS's
    build-layer artefact is inspected. Currently the project
    defines two build-layer artefact scans:

      - ChibiOS ELF symbol scan (`check_chibios_elf_symbols`),
        run when `build_layer_rtos in ("all", "chibios")`.
      - Zephyr generated `.config` scan inside `check_zephyr`,
        run when `build_layer_rtos in ("all", "zephyr")` AND
        `source_only is False`.

    Passing `build_layer_rtos="freertos"` therefore skips both
    artefact scans (FreeRTOS has no build-layer artefact scan
    defined today; only its source-layer config is checked).

    `build_layer_rtos="all"` (default) runs every RTOS's
    build-layer scan, which is the right behaviour for the
    post-build campaign step and for `--all-profiles` CI mode."""
    bag = FailureBag()
    sys.stderr.write(f"config_alignment_check: profile={profile}\n")
    # ADR-024: check_chibios now takes the profile so the
    # CORTEX_ENABLE_WFI_IDLE conditional inside chconf.h can be
    # validated per profile.
    check_chibios(project_root, bag, profile=profile)
    check_freertos(project_root, bag)
    # Cross-port TIM2 IRQ priority (ADR-014); source-layer,
    # profile-independent.
    check_tim2_priority(project_root, bag)
    # Zephyr source-layer always runs (last-wins merge contract).
    # Zephyr build-layer (.config scan) is gated by source_only
    # AND build_layer_rtos per Codex round 4 BLOCKER fix.
    check_zephyr(project_root, profile, bag,
                 source_only=source_only,
                 build_layer_rtos=build_layer_rtos)
    if not source_only:
        if build_layer_rtos in ("all", "chibios"):
            check_chibios_elf_symbols(project_root, profile, bag)
        # No additional build-layer check for FreeRTOS today.
    return bag


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the three RTOS config files honour the ADR-022 / "
            "ADR-009 / ADR-011 contracts. Fail-stops the lab harness "
            "if any drift is detected."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        # Codex round 3 MIN-1: argparse now accepts debug_dev for
        # developer-driven standalone runs. The profile is not
        # publishable (ADR-011) so main() short-circuits with an
        # explicit message mirroring lab_runner.py.
        "--profile", choices=PUBLISHABLE_PROFILES + ("debug_dev",),
        help=(
            "Check one publishable profile, or debug_dev (developer "
            "use only; gate is skipped with an explicit message)."
        ),
    )
    group.add_argument(
        "--all-profiles", action="store_true",
        help="Check every publishable profile (CI use).",
    )
    parser.add_argument(
        "--source-only", action="store_true",
        help=(
            "Skip the build-layer artefact scans (ChibiOS ELF symbol "
            "scan AND Zephyr generated `.config` scan) even if the "
            "artefacts exist. Useful in CI before the toolchain is "
            "bootstrapped, or to debug source-side drift only."
        ),
    )
    # Codex round 3 IMP-2 + round 4 BLOCKER: target-aware build-layer
    # artefact scans so single-RTOS lab flows do not get blocked by
    # stale artefacts from other RTOSes.
    parser.add_argument(
        "--rtos",
        choices=("all", "chibios", "freertos", "zephyr"),
        default="all",
        help=(
            "Limit the build-layer artefact scans to one RTOS. "
            "Affects both the ChibiOS ELF symbol scan and the "
            "Zephyr generated `.config` scan. Source-layer checks "
            "always cover all three RTOSes (the ADR-022 contract is "
            "repo-wide). Default: all."
        ),
    )
    parser.add_argument(
        "--project-root", default=None,
        help="Project root (default: script's grand-parent).",
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve() if args.project_root \
        else PROJECT_ROOT_DEFAULT

    # Codex round 3 MIN-1: debug_dev short-circuit. Skip every check
    # with an explicit message; mirror lab_runner.py wording.
    if args.profile == "debug_dev":
        sys.stderr.write(
            "config_alignment_check: skipped (debug_dev, not "
            "publishable per ADR-011)\n"
        )
        return 0

    profiles = ((args.profile,) if args.profile is not None
                else PUBLISHABLE_PROFILES)

    overall_fail = False
    for profile in profiles:
        bag = run_one_profile(project_root, profile, args.source_only,
                              build_layer_rtos=args.rtos)
        if not bag.ok():
            overall_fail = True
            sys.stderr.write(
                f"\nconfig_alignment_check: FAIL on profile={profile} "
                f"({len(bag.failures)} issue(s)):\n"
            )
            for msg in bag.failures:
                sys.stderr.write(f"  - {msg}\n")
        else:
            sys.stderr.write(
                f"config_alignment_check: PASS on profile={profile}\n"
            )

    if overall_fail:
        sys.stderr.write(
            "\nconfig_alignment_check: lab harness MUST NOT proceed. "
            "Fix the drift and re-run.\n"
        )
        return 2
    sys.stderr.write("config_alignment_check: all profiles GREEN.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
