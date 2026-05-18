#!/usr/bin/env python3
"""
Cross-RTOS CFLAGS audit (ADR-009, Codex round publish-facing).

Reads `compile_commands.json` from an RTOS build directory and
verifies that every application-side translation unit was built
with the ADR-009 flag set. Three RTOSes are supported:

  - `--rtos zephyr`  audits the Zephyr build dir (cmake-generated
                     compile_commands.json). Application sources:
                     `zephyr/benchmark_zephyr/src/*.c` and
                     `common/*.c`.
  - `--rtos freertos`audits the FreeRTOS CMake build dir.
                     Application sources: `freertos/benchmark_freertos/
                     {main.c, test_*.c}` and `common/*.c`. The
                     vendor `system/*.c` files and the startup ASM
                     are explicitly out of scope (analogous to
                     the Zephyr-kernel-out-of-scope rule).
  - `--rtos chibios` audits the ChibiOS Make build dir, where
                     `compile_commands.json` is synthesised from
                     `make -B -n` by
                     `scripts/chibios_synth_compile_commands.py`
                     (delivered in C3-step2; callable via
                     `make compile-commands PROFILE=<p>`).
                     Application sources: `chibios/benchmark_chibios/
                     {main.c, test_*.c}` and `common/*.c`. The
                     ChibiOS port code, HAL, OSAL, and `cfg/*.c`
                     port-glue are out of scope.

HAL / FreeRTOS-kernel / Zephyr-kernel / ChibiOS-RT sources stay
out of scope (ADR-009 §"GCC flag set" governs the application
side, not the kernel internals).

Required flags (publishable profiles):

  architecture / ABI:
    -mcpu=cortex-m7  -mthumb
    -mfpu=fpv5-d16   -mfloat-abi=hard
  codegen:
    -fomit-frame-pointer  -falign-functions=16
    -ffunction-sections   -fdata-sections
    -fno-common           -fno-strict-aliasing

Effective optimization (last `-O<token>` on the command line,
per GCC semantics) must be `-O2`. Any other token in last
position -- `-O0`, `-O1`, `-Os`, `-O3`, `-Og`, `-Ofast`, `-Oz`,
or a stray `-O2` followed by one of these -- fails the gate.

Forbidden: `-flto`, `-flto=<variant>`.

`-Wall`, `-Wextra`, `-DSTM32H750xx`: out of scope (warning
flags / per-RTOS board macro). See ADR-009 §"Enforcement" for
rationale.

The build is "proven" rather than "forced": we do not patch
the per-RTOS Kconfig / Make rules; we read back the compile
commands that the build system actually emitted (with
`-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` for the CMake-based
ports, with a synthesised JSON for the Make-based ChibiOS
port) and gate the campaign on a positive result.

Exit codes:
  0  every checked entry passes
  2  audit failed (missing flag, forbidden flag, wrong
     effective optimization, or input missing); details on
     stderr

Usage:
    python scripts/cflags_audit.py --rtos zephyr \
        --build-dir zephyr/build/fair_perf --profile fair_perf

    python scripts/cflags_audit.py --rtos freertos \
        --build-dir freertos/benchmark_freertos/build/fair_perf \
        --profile fair_perf

    python scripts/cflags_audit.py --rtos chibios \
        --build-dir chibios/benchmark_chibios/build/fair_perf \
        --profile fair_perf
"""

import argparse
import json
import re
import shlex
import sys
from pathlib import Path


REQUIRED_BY_PROFILE = {
    "fair_perf": (
        # Architecture / ABI: derived from board/toolchain; the
        # audit proves they actually reached the app/common
        # objects.
        "-mcpu=cortex-m7",
        "-mthumb",
        "-mfpu=fpv5-d16",
        "-mfloat-abi=hard",
        # ADR-009 codegen contract:
        "-fomit-frame-pointer",
        "-falign-functions=16",
        "-ffunction-sections",
        "-fdata-sections",
        "-fno-common",
        "-fno-strict-aliasing",
        # -O2 is enforced via the effective-opt check below
        # (rejecting '-O2 ... -Og' which a 'flag in tokens' test
        # would silently allow).
    ),
    "realistic_tickless": (
        "-mcpu=cortex-m7",
        "-mthumb",
        "-mfpu=fpv5-d16",
        "-mfloat-abi=hard",
        "-fomit-frame-pointer",
        "-falign-functions=16",
        "-ffunction-sections",
        "-fdata-sections",
        "-fno-common",
        "-fno-strict-aliasing",
    ),
    "debug_dev": (),  # not publishable; no CFLAGS contract
}

# Effective optimization: the last -O<token> wins per GCC docs.
# Publishable profiles must end up at -O2; any other token in
# last position (or no -O at all) fails the gate.
REQUIRED_EFFECTIVE_OPT_BY_PROFILE = {
    "fair_perf":          "-O2",
    "realistic_tickless": "-O2",
    "debug_dev":          None,  # no constraint
}

# Forbidden in publishable profiles. -flto matches the bare
# token; -flto=auto / -flto=thin etc must also be rejected.
# Other -O* tokens (-Os, -O3, -O0, -O1, -Og, -Ofast, -Oz) are
# rejected by the effective-opt check above, not listed here.
FORBIDDEN_BY_PROFILE = {
    "fair_perf":          ("-flto",),
    "realistic_tickless": ("-flto",),
    "debug_dev":          (),
}

# Sources audited per RTOS. Each tuple is OR-ed: a translation
# unit is in scope if its file path matches any of the regexes.
# Kernel / HAL / vendor / port-glue sources are out of scope
# (ADR-009 §"GCC flag set" governs the application side).
APP_FILE_RES_BY_RTOS = {
    "zephyr": (
        re.compile(r"benchmark_zephyr[\\/]src[\\/][^\\/]+\.c$"),
        re.compile(r"(?:^|[\\/])common[\\/][^\\/]+\.c$"),
    ),
    "freertos": (
        # main.c + test_*.c at the top of benchmark_freertos/.
        # Explicitly excludes system/*.c (CubeH7 vendor:
        # system_stm32h7xx.c, stm32h7xx_it.c, syscalls_stubs.c)
        # and startup/*.s, by anchoring at the directory level.
        re.compile(r"benchmark_freertos[\\/]"
                   r"(?:main|test_[^\\/]+)\.c$"),
        re.compile(r"(?:^|[\\/])common[\\/][^\\/]+\.c$"),
    ),
    "chibios": (
        # main.c + test_*.c at the top of benchmark_chibios/.
        # Excludes cfg/*.c (port-glue, e.g. portab.c) and any
        # ChibiOS upstream object.
        re.compile(r"benchmark_chibios[\\/]"
                   r"(?:main|test_[^\\/]+)\.c$"),
        re.compile(r"(?:^|[\\/])common[\\/][^\\/]+\.c$"),
    ),
}

# Lab-session bug fix 2026-05-14: the `common` regex above
# matches the project-root `common/` dir AND any `common/`
# subdirectory in an RTOS upstream tree (e.g.
# `zephyr/zephyr/soc/st/stm32/common/stm32cube_hal.c`,
# `zephyr/zephyr/arch/common/isr_tables.c`). Those kernel /
# HAL files have ADR-009-incompatible flags by design and
# must NOT be audited. Per-RTOS deny patterns reject every
# path that crosses a kernel-tree marker BEFORE the
# in-scope regex match.
DENY_FILE_RES_BY_RTOS = {
    "zephyr": (
        # Upstream Zephyr tree.
        re.compile(r"[\\/]zephyr[\\/]zephyr[\\/]"),
        # Zephyr west modules (newlib / picolibc / hal_stm32 /
        # etc.). Path like `zephyr/modules/lib/picolibc/...`.
        re.compile(r"[\\/]zephyr[\\/]modules[\\/]"),
        # CMake-generated artefacts under build/<profile>/
        # (isr_tables.c, autoconf.h, etc.) live under
        # zephyr/build/<profile>/zephyr/...
        re.compile(r"[\\/]zephyr[\\/]build[\\/]"),
        # Zephyr venv stashed under zephyr/.venv/.
        re.compile(r"[\\/]zephyr[\\/]\.venv[\\/]"),
    ),
    "freertos": (
        # Upstream FreeRTOS kernel submodule.
        re.compile(r"[\\/]freertos[\\/]FreeRTOS-Kernel[\\/]"),
        # STM32CubeH7 HAL submodule.
        re.compile(r"[\\/]freertos[\\/]stm32_hal[\\/]"),
    ),
    "chibios": (
        # Upstream ChibiOS submodule.
        re.compile(r"[\\/]chibios[\\/]ChibiOS[\\/]"),
    ),
}

# Canonical display names used in OK / FAIL messages. The CLI
# accepts lowercase only (matches argparse choices), but the
# stdout output preserves the project's preferred capitalization.
RTOS_DISPLAY_NAME = {
    "chibios":  "ChibiOS",
    "freertos": "FreeRTOS",
    "zephyr":   "Zephyr",
}

# Publishable-profile completeness gate (Codex round
# 2026-05-14-bucket-c-track-001 IMPORTANT 1). A truncated or
# partially-synthesised compile_commands.json must NOT pass
# the gate just because its remaining entries have correct
# flags. The audit requires every source basename below to
# appear at least once in the in-scope (matched) entries for
# any publishable profile.
EXPECTED_APP_SOURCES_BY_RTOS = {
    "zephyr": (
        "main.c",
        "test_ctxsw_irq.c",
        "test_thread_handoff.c",
        "test_mutex_uncontended.c",
        "test_mutex_pi.c",
        "dwt_cycle_counter.c",
        "benchmark_stats.c",
        "bench_button.c",
    ),
    "freertos": (
        "main.c",
        "test_ctxsw_irq.c",
        "test_thread_handoff.c",
        "test_mutex_uncontended.c",
        "test_mutex_pi.c",
        "dwt_cycle_counter.c",
        "benchmark_stats.c",
        "bench_button.c",
    ),
    "chibios": (
        "main.c",
        "test_ctxsw_irq.c",
        "test_thread_handoff.c",
        "test_mutex_uncontended.c",
        "test_mutex_pi.c",
        "dwt_cycle_counter.c",
        "benchmark_stats.c",
        "bench_button.c",
    ),
}
# Profiles that require the completeness check. debug_dev
# stays exempt (it has no CFLAGS contract either).
REQUIRES_COMPLETE_SET = frozenset(
    ("fair_perf", "realistic_tickless"))


def _is_app_source(file_path: str, rtos: str) -> bool:
    # Reject anything in an RTOS kernel / HAL tree first.
    # See DENY_FILE_RES_BY_RTOS for the per-RTOS markers.
    for deny in DENY_FILE_RES_BY_RTOS.get(rtos, ()):
        if deny.search(file_path):
            return False
    res = APP_FILE_RES_BY_RTOS[rtos]
    return any(r.search(file_path) for r in res)


def _tokens(entry: dict) -> list[str]:
    """Return the tokenised compile command for @p entry.
    cmake emits either 'command' (single string) or 'arguments'
    (list); handle both."""
    if "arguments" in entry and entry["arguments"]:
        return list(entry["arguments"])
    cmd = entry.get("command", "")
    return shlex.split(cmd, posix=True)


def _has_flag(tokens: list[str], flag: str) -> bool:
    return flag in tokens


def _has_lto(tokens: list[str]) -> bool:
    """True if any token is -flto or -flto=<variant>."""
    return any(t == "-flto" or t.startswith("-flto=")
               for t in tokens)


# GCC accepts bare '-O' (historically '-O1'); it is NOT
# equivalent to the required '-O2' for publishable profiles.
# Match both bare '-O' and '-O<token>' so the effective-opt
# check can flag bare '-O' as a wrong-optimization failure
# (Codex round 2026-05-14-bucket-c-track-001 MINOR 1).
_OPT_RE = re.compile(r"-O(?:\w+)?")


def _effective_opt(tokens: list[str]) -> str | None:
    """Return the last -O<token> in @p tokens, or None if no
    optimization token is present. GCC uses the last -O on the
    command line, so this is what actually drives codegen."""
    last = None
    for t in tokens:
        if _OPT_RE.fullmatch(t):
            last = t
    return last


def audit(build_dir: Path, profile: str, rtos: str) -> int:
    display = RTOS_DISPLAY_NAME[rtos]
    cc_path = build_dir / "compile_commands.json"
    if not cc_path.is_file():
        print(f"FAIL: {cc_path} not found "
              f"(the build system should emit it; verify the "
              f"{display} build completed before running the "
              f"audit)", file=sys.stderr)
        return 2

    try:
        entries = json.loads(cc_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot parse {cc_path}: {exc}",
              file=sys.stderr)
        return 2

    required = REQUIRED_BY_PROFILE.get(profile, ())
    forbidden = FORBIDDEN_BY_PROFILE.get(profile, ())
    if not required and not forbidden:
        print(f"profile {profile!r}: no CFLAGS contract; "
              f"audit skipped")
        return 0

    app_entries = [e for e in entries
                   if _is_app_source(str(e.get("file", "")),
                                     rtos)]
    if not app_entries:
        print(f"FAIL: no application sources matched the "
              f"{display} regex set in {cc_path} "
              f"({len(entries)} total entries)",
              file=sys.stderr)
        return 2

    required_opt = REQUIRED_EFFECTIVE_OPT_BY_PROFILE.get(profile)
    failures: list[tuple[str, str, str]] = []
    for e in app_entries:
        tokens = _tokens(e)
        for flag in required:
            if not _has_flag(tokens, flag):
                failures.append((e["file"], "missing", flag))
        for flag in forbidden:
            if flag == "-flto":
                if _has_lto(tokens):
                    failures.append((e["file"], "forbidden", flag))
            else:
                if _has_flag(tokens, flag):
                    failures.append((e["file"], "forbidden", flag))
        # Effective-opt check: the publishable contract is
        # "unambiguously -O2". Reject -O1 / -Og / -Ofast / -Oz,
        # and reject -O2 followed by any overriding -O<token>.
        if required_opt is not None:
            eff = _effective_opt(tokens)
            if eff != required_opt:
                if eff is None:
                    failures.append((e["file"],
                                     "missing optimization",
                                     f"expected {required_opt}"))
                else:
                    failures.append((e["file"],
                                     "wrong effective optimization",
                                     f"{eff} (expected {required_opt})"))

    # Completeness check (Codex round
    # 2026-05-14-bucket-c-track-001 IMPORTANT 1). For
    # publishable profiles every expected app/common source
    # basename must appear at least once in the in-scope set.
    # A truncated compile_commands.json otherwise passes the
    # per-entry gate trivially.
    if profile in REQUIRES_COMPLETE_SET:
        expected = set(EXPECTED_APP_SOURCES_BY_RTOS[rtos])
        seen = {Path(e["file"]).name for e in app_entries}
        for missing_name in sorted(expected - seen):
            failures.append(("(coverage)",
                             "missing source",
                             missing_name))

    if failures:
        print(f"FAIL: {display} CFLAGS audit failed for profile "
              f"{profile!r} (ADR-009):", file=sys.stderr)
        for f, kind, flag in failures[:50]:
            # The 'missing source' coverage failure is a
            # filename, not a flag token; print it without
            # the bridging word "flag".
            if kind == "missing source":
                line = f"  {Path(f).name}: missing source {flag}"
            else:
                line = f"  {Path(f).name}: {kind} flag {flag}"
            print(line, file=sys.stderr)
        if len(failures) > 50:
            print(f"  ... and {len(failures) - 50} more",
                  file=sys.stderr)
        return 2

    print(f"OK: {len(app_entries)} {display} application "
          f"object(s) pass the ADR-009 CFLAGS contract for "
          f"profile {profile!r}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rtos", required=True,
                   choices=("chibios", "freertos", "zephyr"),
                   help="RTOS port to audit. Selects the "
                        "application-source regex set.")
    p.add_argument("--build-dir", required=True,
                   help="Path to the build directory that "
                        "contains compile_commands.json.")
    p.add_argument("--profile", required=True,
                   choices=("fair_perf", "realistic_tickless",
                            "debug_dev"))
    args = p.parse_args(argv)
    return audit(Path(args.build_dir), args.profile, args.rtos)


if __name__ == "__main__":
    sys.exit(main())
