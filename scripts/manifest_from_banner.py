#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
Build a per-run manifest.json from the firmware boot banner + lab
metadata.

Required by ADR-013 ("minimum publication standard"). Every published
run carries a manifest with the firmware-state register dump, git
commit, toolchain string, LA configuration, and a reference to the
CAL-1 calibration file used to evaluate DWT-vs-LA agreement.

The script is tightly coupled to the banner format emitted by
common/benchmark_stats.c::bench_print_banner. If the banner is
changed, this parser must be updated in tandem.

Usage:
    python manifest_from_banner.py \\
        --banner    path/to/banner.txt \\
        --git-commit <sha> \\
        --toolchain "arm-none-eabi-gcc 14.2.Rel1" \\
        --la-sample-rate 200000000 \\
        --la-model "Zeroplus LAP-C-16128" \\
        --calibration path/to/<date>_calibration.json \\
        --operator <name> \\
        --out path/to/<rtos>_<profile>_<test>_<run>_manifest.json
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


# Banner field regexes. Tied to bench_print_banner() output (the
# banner format changed in round-5: "Warmup" -> "T1/T2/T3 wm",
# "Valid" -> "T1/T2/T3 valid", new "T4 runs" line, optional
# "SCB->CCR pre" line, TIM2 register block).
# Each entry maps a JSON path (dotted) to a regex capturing one group.
BANNER_FIELDS = {
    "rtos":                   r"^\s*RTOS\s*:\s*(\S+)",
    "profile":                r"^\s*Profile\s*:\s*(\S+)",
    "board":                  r"^\s*Board\s*:\s*(\S.+?)\s*$",
    "silicon.idcode":         r"^\s*DBGMCU IDCODE\s*:\s*(0x[0-9a-fA-F]+)",
    "clock.sysclk_hz":        r"^\s*SystemClock\s*:\s*(\d+)\s*Hz",
    "scb_ccr":                r"^\s*SCB->CCR\s*:\s*(0x[0-9a-fA-F]+)",
    "icache":                 r"^\s*ICache\s*:\s*(ON|OFF)",
    "dcache":                 r"^\s*DCache\s*:\s*(ON|OFF)",
    "clock.rcc_pllckselr":    r"^\s*RCC_PLLCKSELR\s*:\s*(0x[0-9a-fA-F]+)",
    "clock.rcc_pllcfgr":      r"^\s*RCC_PLLCFGR\s*:\s*(0x[0-9a-fA-F]+)",
    "clock.rcc_pll1divr":     r"^\s*RCC_PLL1DIVR\s*:\s*(0x[0-9a-fA-F]+)",
    "clock.rcc_d1cfgr":       r"^\s*RCC_D1CFGR\s*:\s*(0x[0-9a-fA-F]+)",
    "clock.rcc_d2cfgr":       r"^\s*RCC_D2CFGR\s*:\s*(0x[0-9a-fA-F]+)",
    "clock.rcc_d3cfgr":       r"^\s*RCC_D3CFGR\s*:\s*(0x[0-9a-fA-F]+)",
    "power.pwr_d3cr":         r"^\s*PWR_D3CR\s*:\s*(0x[0-9a-fA-F]+)",
    "power.syscfg_pwrcr":     r"^\s*SYSCFG_PWRCR\s*:\s*(0x[0-9a-fA-F]+)",
    "power.vos_level":        r"^\s*VOS level\s*:\s*(\S+)",
    "power.vosrdy":           r"^\s*VOSRDY\s*:\s*(\S+)",
    "flash_acr":              r"^\s*FLASH_ACR\s*:\s*(0x[0-9a-fA-F]+)",
    # boot-time TIM2 dump (zeros in practice; the after_t1_setup dump
    # is the one that proves the live PWM mode 2 + CC1 IRQ config).
    "tim2_boot.cr1":          r"^\s*TIM2_CR1\s*:\s*(0x[0-9a-fA-F]+)",
    "tim2_boot.dier":         r"^\s*TIM2_DIER\s*:\s*(0x[0-9a-fA-F]+)",
    "tim2_boot.ccmr1":        r"^\s*TIM2_CCMR1\s*:\s*(0x[0-9a-fA-F]+)",
    "tim2_boot.ccer":         r"^\s*TIM2_CCER\s*:\s*(0x[0-9a-fA-F]+)",
    "tim2_boot.psc":          r"^\s*TIM2_PSC\s*:\s*(0x[0-9a-fA-F]+)",
    "tim2_boot.arr":          r"^\s*TIM2_ARR\s*:\s*(0x[0-9a-fA-F]+)",
    "tim2_boot.ccr1":         r"^\s*TIM2_CCR1\s*:\s*(0x[0-9a-fA-F]+)",
    "tickless":               r"^\s*Tickless\s*:\s*(ON|OFF)",
    "wfi_in_idle":            r"^\s*WFI in idle\s*:\s*(ON|OFF)",
    "tick_rate_hz":           r"^\s*Tick rate\s*:\s*(\d+)\s*Hz",
    "optimization":           r"^\s*Optimization\s*:\s*(.+?)\s*$",
    "warmup_iterations":      r"^\s*T1/T2/T3 wm\s*:\s*(\d+)",
    "valid_iterations":       r"^\s*T1/T2/T3 valid:\s*(\d+)",
    "t4_runs":                r"^\s*T4 runs\s*:\s*(\d+)",
    "dwt_overhead_cycles":    r"^\s*DWT overhead\s*:\s*(\d+)\s*cycles",
}

# Optional fields: missing in banner is OK, will be set to null.
OPTIONAL_BANNER_FIELDS = {
    "scb_ccr_before":         r"^\s*SCB->CCR pre\s*:\s*(0x[0-9a-fA-F]+)",
}

# Per-test TIM2 state dumps: appear AFTER bench_t1_setup and AFTER
# bench_t1_run. Each forms its own block "--- TIM2 state (<tag>) ---"
# followed by 7 register lines. We slurp them as a list of {tag:..., regs:{...}}.
TIM2_STATE_BLOCK_RE = re.compile(
    r"---\s*TIM2 state \((?P<tag>[^)]+)\)\s*---\s*\n"
    r"(?P<body>(?:.+\n)+?)"
    r"---\s*end TIM2 state\s*---",
    re.MULTILINE,
)
TIM2_STATE_REG_RE = re.compile(
    r"^\s*TIM2_(\w+)\s*:\s*(0x[0-9a-fA-F]+)", re.MULTILINE)


def parse_banner(banner_text: str) -> dict[str, Any]:
    """Extract structured fields from the banner text."""
    result: dict[str, Any] = {}
    for path, pattern in BANNER_FIELDS.items():
        match = re.search(pattern, banner_text, re.MULTILINE)
        if match is None:
            sys.exit(f"ERROR: banner missing field '{path}' "
                     f"(regex: {pattern})")
        value = match.group(1)
        if path in ("clock.sysclk_hz", "tick_rate_hz",
                    "warmup_iterations", "valid_iterations",
                    "t4_runs", "dwt_overhead_cycles"):
            value = int(value)
        elif path in ("icache", "dcache", "tickless", "wfi_in_idle"):
            value = (value == "ON")
        _set_dotted(result, path, value)

    # Optional fields.
    for path, pattern in OPTIONAL_BANNER_FIELDS.items():
        match = re.search(pattern, banner_text, re.MULTILINE)
        if match is None:
            _set_dotted(result, path, None)
        else:
            _set_dotted(result, path, match.group(1))

    # Per-test TIM2 state dumps (after_t1_setup, after_t1_run, ...).
    tim2_states: dict[str, dict[str, str]] = {}
    for block in TIM2_STATE_BLOCK_RE.finditer(banner_text):
        tag  = block.group("tag")
        body = block.group("body")
        regs = {name.lower(): val
                for name, val in TIM2_STATE_REG_RE.findall(body)}
        tim2_states[tag] = regs
    if tim2_states:
        result["tim2_states"] = tim2_states

    # Derive rev_id from idcode (high 16 bits).
    idcode_str = result["silicon"]["idcode"]
    idcode_int = int(idcode_str, 16)
    result["silicon"]["rev_id"] = f"0x{idcode_int >> 16:04x}"
    result["silicon"]["device_id"] = f"0x{idcode_int & 0xFFF:03x}"

    return result


def _set_dotted(d: dict[str, Any], path: str, value: Any) -> None:
    """Set d[a][b][c] = value from a dotted path 'a.b.c'."""
    parts = path.split(".")
    cur: Any = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def collect_submodule_shas(repo_root: Path) -> dict[str, str]:
    """Walk `git submodule status --recursive` for SHA pinning."""
    try:
        out = subprocess.check_output(
            ["git", "submodule", "status", "--recursive"],
            cwd=str(repo_root),
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Not in a git repo or git not in PATH. Return empty.
        return {}

    shas: dict[str, str] = {}
    for line in out.splitlines():
        # Lines look like:  " <sha> <path> (<describe>)"
        # or "-<sha> <path>" (uninitialised), or "+<sha> ..." (out of sync).
        parts = line.strip().split()
        if len(parts) >= 2:
            sha = parts[0].lstrip("+-").strip()
            path = parts[1]
            shas[path] = sha
    return shas


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    """Compose the full manifest from banner + CLI inputs + git."""
    banner_text = Path(args.banner).read_text(encoding="utf-8")
    banner_fields = parse_banner(banner_text)

    repo_root = Path(__file__).resolve().parent.parent
    submodules = collect_submodule_shas(repo_root)

    # Round-12 §8 — calibration file traceability. The CAL-1
    # tolerance from ADR-015 lives in this JSON; the manifest
    # records both the path and the SHA256 of the file content,
    # so a downstream reviewer can verify that the calibration
    # used at run-time is exactly the one referenced in the report.
    cal_path = Path(args.calibration)
    if not cal_path.is_file():
        sys.exit(f"ERROR: --calibration file not found: {cal_path}")
    cal_bytes = cal_path.read_bytes()
    cal_sha256 = hashlib.sha256(cal_bytes).hexdigest()

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "operator": args.operator,
        "git_commit": args.git_commit,
        "git_submodules": submodules,
        "toolchain": args.toolchain,
        "la": {
            "sample_rate_hz": args.la_sample_rate,
            "model": args.la_model,
            "calibration_file": str(cal_path),
            "calibration_sha256": cal_sha256,
            "calibration_size_bytes": len(cal_bytes),
        },
    }
    # banner_fields contains rtos, profile, board, silicon, clock,
    # power, scb_ccr, icache, dcache, flash_acr, tickless,
    # wfi_in_idle, tick_rate_hz, optimization, warmup_iterations,
    # valid_iterations, dwt_overhead_cycles. Merge in.
    manifest.update(banner_fields)

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build per-run manifest.json from boot banner.")
    parser.add_argument("--banner", required=True,
                        help="Path to captured banner text file.")
    parser.add_argument("--git-commit", required=True,
                        help="Current git commit SHA "
                             "(`git rev-parse HEAD`).")
    parser.add_argument("--toolchain", required=True,
                        help='Toolchain string, e.g. '
                             '"arm-none-eabi-gcc 14.2.Rel1".')
    parser.add_argument("--la-sample-rate", type=int, required=True,
                        help="LA sample rate in Hz (e.g. 200000000).")
    parser.add_argument("--la-model", required=True,
                        help='LA model string, e.g. "Zeroplus LAP-C-16128".')
    parser.add_argument("--calibration", required=True,
                        help="Path to the CAL-1 calibration JSON used "
                             "for DWT-vs-LA tolerance.")
    parser.add_argument("--operator", required=True,
                        help="Operator name for traceability.")
    parser.add_argument("--out", required=True,
                        help="Output manifest JSON path.")
    args = parser.parse_args()

    manifest = build_manifest(args)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
