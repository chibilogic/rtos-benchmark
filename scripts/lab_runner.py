#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
scripts/lab_runner.py - cross-platform benchmark pipeline orchestrator.

Pure-Python replacement for the orchestration logic previously
implemented only in PowerShell (scripts/lab_smoke.ps1,
scripts/lab_campaign.ps1). Owns build invocation, ELF/MAP SHA-256
computation, campaign-lock writing, OpenOCD flash/reset
orchestration with the Round-11 "collector-before-reset" ordering,
collector + analyze + report + plot pipeline, run00 warmup +
run01..05 campaign loop, and publication-gate enforcement.

Subcommands:
    build-only    Build one (rtos, profile); compute ELF/MAP SHA; no flash
    smoke         Build + flash + collect ONE run; optional report/plot
    campaign      Build-once per RTOS + run00 warmup + run01..05 + gate + plots
    only-report   (Re-)run report + plot on existing results/raw (no HW)

PowerShell scripts are kept INTACT and additive in this commit
(Commit 2/3 of the Linux readiness migration, Codex
2026-05-20-cross-platform-linux-readiness-001).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RTOSES = ("chibios", "freertos", "zephyr")
PROFILES = ("fair_perf", "realistic_tickless", "debug_dev")
PUB_MODES = ("la", "dwt_only")

DEFAULT_PORT = "COM5" if os.name == "nt" else "/dev/ttyACM0"


# =========================================================================
# Path helpers
# =========================================================================

def build_workdir(rtos: str) -> Path:
    """Working directory of the per-RTOS Makefile wrapper."""
    return {
        "chibios":  REPO_ROOT / "chibios"  / "benchmark_chibios",
        "freertos": REPO_ROOT / "freertos" / "benchmark_freertos",
        "zephyr":   REPO_ROOT / "zephyr"   / "benchmark_zephyr",
    }[rtos]


def build_outdir(rtos: str, profile: str) -> Path:
    """Per-RTOS build output directory (wiped by --clean)."""
    if rtos == "zephyr":
        return REPO_ROOT / "zephyr" / "build" / profile
    return build_workdir(rtos) / "build" / profile


def elf_map_paths(rtos: str, profile: str) -> tuple[Path, Path]:
    """Canonical ELF / MAP paths per RTOS, profile."""
    if rtos == "chibios":
        bd = build_outdir(rtos, profile)
        return bd / "benchmark_chibios.elf", bd / "benchmark_chibios.map"
    if rtos == "freertos":
        bd = build_outdir(rtos, profile)
        return bd / "benchmark_freertos.elf", bd / "benchmark_freertos.map"
    if rtos == "zephyr":
        bd = build_outdir(rtos, profile) / "zephyr"
        return bd / "zephyr.elf", bd / "zephyr.map"
    raise ValueError(f"unknown rtos: {rtos}")


def cflags_build_dir(rtos: str, profile: str) -> Path:
    """Build dir to pass to scripts/cflags_audit.py."""
    return build_outdir(rtos, profile)


def run_prefix(rtos: str, profile: str, run_id: str) -> Path:
    """Output prefix (no suffix) used by collector for one run."""
    return REPO_ROOT / "results" / "raw" / f"{rtos}_{profile}_run{run_id}"


# =========================================================================
# Generic helpers
# =========================================================================

def step(msg: str) -> None:
    print(f"\n===== {msg} =====", flush=True)


def shell_str(argv: list[str]) -> str:
    return " ".join(str(a) for a in argv)


def sha256_lower(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_checked(argv: list[str], cwd: Path | None = None) -> None:
    """Run argv to completion; exit non-zero if exit code != 0.

    Uses argv array (no shell quoting issues). cwd is set if given.
    """
    print(f"> {shell_str(argv)}", flush=True)
    rc = subprocess.run(argv, cwd=str(cwd) if cwd else None).returncode
    if rc != 0:
        raise SystemExit(f"FAIL: '{argv[0]}' exited {rc}")


def autorun_value(pub_mode: str) -> str:
    """AUTORUN follows publication mode (ADR-015):
       dwt_only -> 1 (B1 gating bypass);  la -> 0 (B1 gating mandatory)."""
    return "1" if pub_mode == "dwt_only" else "0"


def required_build_tools(rtoses: set[str]) -> set[str]:
    """Per-RTOS build-time tool dependencies. Codex
    2026-05-20-linux-readiness-trilogy-applied-001 IMPORTANT 2:
    cmake is needed for FreeRTOS (CMake project) and Zephyr
    (cmake via west); west itself is needed for Zephyr."""
    tools: set[str] = set()
    for r in rtoses:
        tools.add("make")
        tools.add("arm-none-eabi-gcc")
        # ADR-022 build-layer gate + ADR-023 footprint pipeline both
        # use these binutils helpers. They ship with arm-gnu-toolchain
        # next to gcc, so requiring them explicitly only catches a
        # genuinely broken toolchain bootstrap (Codex round 2 IMP-5).
        tools.add("arm-none-eabi-nm")
        tools.add("arm-none-eabi-readelf")
        if r in ("freertos", "zephyr"):
            tools.add("cmake")
        if r == "zephyr":
            tools.add("west")
    return tools


# =========================================================================
# Cross-platform preflight
# =========================================================================

def preflight(need_tools: set[str], need_python_pkgs: set[str] = frozenset()) -> None:
    """Verify tools on PATH + selected Python packages can import.

    Codex requirement: explicit Linux preflight + sys.executable
    visibility (avoid the Zephyr-venv-masking-host trap, memory
    `project_zephyr_build_env.md`).
    """
    print(f"[preflight] python = {sys.executable}")

    missing_tools = sorted(t for t in need_tools if shutil.which(t) is None)
    if missing_tools:
        sys.stderr.write(
            f"[preflight] missing required tools on PATH: "
            f"{', '.join(missing_tools)}\n"
            f"  source env.bat (Windows) or '. ./env.sh' (Linux) first.\n"
        )
        sys.exit(2)
    for t in sorted(need_tools):
        print(f"[preflight] {t} = {shutil.which(t)}")

    missing_pkgs: list[str] = []
    for p in sorted(need_python_pkgs):
        try:
            __import__(p)
        except ImportError:
            missing_pkgs.append(p)
    if missing_pkgs:
        sys.stderr.write(
            f"[preflight] missing Python packages: {', '.join(missing_pkgs)}\n"
            f"  run:  pip install -r requirements.txt\n"
            f"  (and verify `python` does NOT resolve to the Zephyr venv).\n"
        )
        sys.exit(2)


def preflight_serial_port(port: str) -> None:
    """Linux-only check: warn if /dev/ttyACMn missing + hint at
    dialout/plugdev group / ST-Link udev rules."""
    if os.name == "nt":
        return  # Windows COMn cannot be reliably checked without opening
    if not Path(port).exists():
        sys.stderr.write(
            f"[preflight] serial port {port} not found.\n"
            f"  hint: check ST-Link USB enumeration ('lsusb | grep ST-LINK')\n"
            f"  hint: add your user to the dialout (or plugdev) group\n"
            f"  hint: install ST-Link udev rules (stlink-tools package)\n"
        )
        # Non-fatal: the port may appear once openocd connects.


# =========================================================================
# Build
# =========================================================================

def do_build(rtos: str, profile: str, pub_mode: str, clean: bool) -> None:
    """Build one (rtos, profile). Wipe build dir if clean."""
    autorun = autorun_value(pub_mode)
    wd = build_workdir(rtos)
    bd = build_outdir(rtos, profile)
    if clean and bd.exists():
        print(f"  --clean: wiping {bd}")
        shutil.rmtree(bd)
    step(f"Build {rtos} ({profile}, AUTORUN={autorun})")
    run_checked(["make", f"PROFILE={profile}", f"AUTORUN={autorun}", "-j"], cwd=wd)


def do_cflags_audit(rtos: str, profile: str) -> None:
    """ADR-009 effective-CFLAGS audit. ChibiOS needs an explicit
    `make compile-commands PROFILE=...` first (its Makefile does
    not emit compile_commands.json by default); FreeRTOS and Zephyr
    emit it via CMAKE_EXPORT_COMPILE_COMMANDS."""
    step(f"{rtos} CFLAGS audit ({profile})")
    if rtos == "chibios":
        run_checked(["make", "compile-commands", f"PROFILE={profile}"],
                    cwd=build_workdir(rtos))
    run_checked([sys.executable,
                 str(REPO_ROOT / "scripts" / "cflags_audit.py"),
                 "--rtos", rtos,
                 "--build-dir", str(cflags_build_dir(rtos, profile)),
                 "--profile", profile],
                cwd=REPO_ROOT)


def do_config_alignment_check(profile: str,
                              source_only: bool = False,
                              rtos: str | None = None) -> None:
    """ADR-022 kernel-feature-equivalence gate.

    Two-phase contract (Codex round 2 BLOCKER 1 fix):
      - source_only=True : invoked BEFORE the build (catches a
        regressed chconf.h / FreeRTOSConfig.h / prj.conf so no
        compile time is wasted on a drifted config). MUST NOT
        inspect any ELF: an ELF from the pre-fix state might
        legitimately still contain forbidden symbols, and refusing
        to rebuild would create a chicken-and-egg deadlock.
      - source_only=False: invoked AFTER the relevant build (or
        before a `--skip-build` smoke). Runs source + build-layer
        ELF symbol check on the freshly built artefact.

    Target-aware build-layer artefact scans (Codex round 3 IMP-2 +
    round 4 BLOCKER): when `rtos` is a specific value (chibios /
    freertos / zephyr), only the build-layer artefact scans for
    THAT RTOS run. The project defines two such scans today:

      - ChibiOS ELF symbol scan (verifies the post-ADR-022 kernel
        feature set is actually linked / not linked).
      - Zephyr generated `.config` scan (verifies the effective
        Kconfig output honours the merged PRJ + per-profile
        contract).

    Callers in single-RTOS flows (cmd_build_only, _run_smoke)
    pass the selected RTOS so a stale ChibiOS ELF or a stale
    Zephyr `.config` cannot fail e.g. a `build-only --rtos
    freertos` run. Multi-RTOS callers (cmd_campaign) pass
    `rtos=None` so the default "all" coverage is preserved.

    debug_dev is NOT a publishable profile (ADR-011); the gate is
    skipped with an explicit message so `lab_runner.py
    build-only --profile debug_dev` keeps working (Codex round 2
    BLOCKER 2 fix).

    Lab harness contract: if this fails (exit non-zero), the
    campaign MUST NOT proceed. The per-issue stderr output guides
    the operator to the exact drifted option."""
    if profile == "debug_dev":
        step(f"Config alignment check skipped "
             f"(debug_dev, not publishable per ADR-011)")
        return
    mode = "source-only" if source_only else "full"
    rtos_label = rtos if rtos else "all"
    step(f"Config alignment check "
         f"(ADR-022, profile={profile}, mode={mode}, "
         f"build-layer-rtos={rtos_label})")
    argv = [sys.executable,
            str(REPO_ROOT / "scripts" / "config_alignment_check.py"),
            "--profile", profile]
    if source_only:
        argv.append("--source-only")
    if rtos:
        argv.extend(["--rtos", rtos])
    run_checked(argv, cwd=REPO_ROOT)


# =========================================================================
# OpenOCD
# =========================================================================

def openocd_flash_no_reset(elf: Path) -> None:
    """Round-11 ordering: program + verify, but do NOT reset.

    Path passed with forward slashes because OpenOCD's Tcl parser
    treats backslash as an escape inside double-quoted strings."""
    elf_fwd = elf.as_posix()
    step("Flash (program verify, no reset)")
    run_checked(["openocd",
                 "-f", "interface/stlink.cfg",
                 "-f", "target/stm32h7x.cfg",
                 "-c", "reset_config srst_only srst_nogate connect_assert_srst",
                 "-c", f'program "{elf_fwd}" verify exit'],
                cwd=REPO_ROOT)


def openocd_reset_run() -> None:
    """init + reset run; firmware starts. Collector must already
    be listening on the serial port at this point (Round-11)."""
    step("Reset and run")
    run_checked(["openocd",
                 "-f", "interface/stlink.cfg",
                 "-f", "target/stm32h7x.cfg",
                 "-c", "reset_config srst_only srst_nogate connect_assert_srst",
                 "-c", "init; reset run; exit"],
                cwd=REPO_ROOT)


# =========================================================================
# Collector + Analyze
# =========================================================================

def start_collector(*, rtos: str, profile: str, run_id: str,
                    port: str, baud: int, output_prefix: Path,
                    timeout_sec: int, pub_mode: str,
                    elf: Path, map_path: Path,
                    quiet: bool) -> tuple[subprocess.Popen, Path, Path]:
    out_p = Path(str(output_prefix) + ".collector.out.txt")
    err_p = Path(str(output_prefix) + ".collector.err.txt")
    out_p.parent.mkdir(parents=True, exist_ok=True)

    argv = [sys.executable,
            str(REPO_ROOT / "scripts" / "collect_results.py"),
            "--port", port,
            "--baud", str(baud),
            "--rtos", rtos,
            "--profile", profile,
            "--run-id", run_id,
            "--output", str(output_prefix),
            "--timeout", str(timeout_sec),
            "--publication-mode", pub_mode,
            "--elf-file", str(elf),
            "--map-file", str(map_path)]
    if quiet:
        argv.append("--quiet")

    step(f"Start collector ({rtos} / {profile} / run {run_id})")
    print(f"> {shell_str(argv)}", flush=True)
    fout = out_p.open("w", encoding="utf-8")
    ferr = err_p.open("w", encoding="utf-8")
    proc = subprocess.Popen(argv, cwd=str(REPO_ROOT),
                            stdout=fout, stderr=ferr)
    # Keep the file handles alive via attributes on the process so
    # they close cleanly when the process exits.
    proc._lab_runner_stdout = fout  # type: ignore[attr-defined]
    proc._lab_runner_stderr = ferr  # type: ignore[attr-defined]
    return proc, out_p, err_p


def wait_collector(proc: subprocess.Popen, out_p: Path, err_p: Path,
                   max_wait_sec: int, output_prefix: Path) -> None:
    step("Wait collector")
    try:
        rc = proc.wait(timeout=max_wait_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise SystemExit(
            f"Collector did not finish in {max_wait_sec}s; killed. "
            f"See {out_p} / {err_p}"
        )
    for attr in ("_lab_runner_stdout", "_lab_runner_stderr"):
        h = getattr(proc, attr, None)
        if h is not None:
            try:
                h.close()
            except Exception:
                pass

    if out_p.exists():
        sys.stdout.write(out_p.read_text(encoding="utf-8", errors="replace"))
        sys.stdout.flush()
    if rc != 0:
        if err_p.exists():
            sys.stderr.write(err_p.read_text(encoding="utf-8", errors="replace"))
        raise SystemExit(
            f"collect_results.py failed exit {rc}; raw log at "
            f"{output_prefix}.stdout.txt"
        )
    if err_p.exists():
        err_txt = err_p.read_text(encoding="utf-8", errors="replace")
        if err_txt.strip():
            sys.stderr.write(err_txt)


def analyze_run(output_prefix: Path) -> None:
    step("Analyze firmware stats vs Python recompute")
    run_checked([sys.executable,
                 str(REPO_ROOT / "scripts" / "analyze_results.py"),
                 str(output_prefix)],
                cwd=REPO_ROOT)


# =========================================================================
# Internal smoke runner (callable from cmd_smoke OR cmd_campaign)
# =========================================================================

def _run_smoke(*, rtos: str, profile: str, run_id: str,
               port: str, baud: int,
               collector_timeout_sec: int,
               collector_start_delay_sec: int,
               pub_mode: str,
               clean: bool = False,
               skip_build: bool = False,
               skip_report_plot: bool = False,
               quiet_collector: bool = False,
               elf_file: str = "",
               map_file: str = "",
               expected_elf_sha: str = "",
               expected_map_sha: str = "") -> None:

    need_tools = {"openocd"}
    need_pkgs = {"serial"}
    if not skip_build:
        need_tools |= required_build_tools({rtos})
    if not skip_report_plot:
        need_pkgs |= {"matplotlib"}
    preflight(need_tools, need_pkgs)
    preflight_serial_port(port)

    # ADR-022 pre-flight gate (Codex round 2 BLOCKER 1):
    # split into source-only (pre-build, never inspects ELFs) and
    # full check (post-build, inspects the freshly built ELF). The
    # --skip-build branch runs the full check upfront because the
    # operator has explicitly told us the existing ELF is the one
    # to flash. Codex round 3 IMP-2: build-layer scan is target-
    # aware so a stale ChibiOS ELF cannot fail a single-RTOS flow
    # that is rebuilding only FreeRTOS or Zephyr.
    if skip_build:
        do_config_alignment_check(profile, source_only=False, rtos=rtos)
    else:
        do_config_alignment_check(profile, source_only=True)
        do_build(rtos, profile, pub_mode, clean=clean)
        do_config_alignment_check(profile, source_only=False, rtos=rtos)
        do_cflags_audit(rtos, profile)
    # Note: when skip_build is True the cflags audit is also
    # skipped (pre-existing behaviour; the cflags audit needs a
    # fresh compile_commands.json that --skip-build does not
    # regenerate). The alignment check still covers the source-side
    # of the ADR-022 contract, and the build-layer ELF symbol scan
    # catches a stale ELF/source mismatch.

    elf = Path(elf_file) if elf_file else elf_map_paths(rtos, profile)[0]
    map_path = Path(map_file) if map_file else elf_map_paths(rtos, profile)[1]
    if not elf.is_file():
        raise SystemExit(f"ELF not found: {elf}")
    if not map_path.is_file():
        raise SystemExit(f"MAP not found: {map_path}")

    output_prefix = run_prefix(rtos, profile, run_id)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    if clean:
        for f in output_prefix.parent.glob(f"{rtos}_{profile}_run{run_id}.*"):
            f.unlink(missing_ok=True)

    step(f"Artefact hashes ({rtos} / {profile})")
    elf_sha = sha256_lower(elf)
    map_sha = sha256_lower(map_path)
    print(f"  ELF: {elf}")
    print(f"  ELF SHA256: {elf_sha}")
    print(f"  MAP: {map_path}")
    print(f"  MAP SHA256: {map_sha}")
    if expected_elf_sha and elf_sha != expected_elf_sha:
        raise SystemExit(
            f"ELF SHA mismatch: expected {expected_elf_sha} got {elf_sha}"
        )
    if expected_map_sha and map_sha != expected_map_sha:
        raise SystemExit(
            f"MAP SHA mismatch: expected {expected_map_sha} got {map_sha}"
        )

    openocd_flash_no_reset(elf)
    proc, out_p, err_p = start_collector(
        rtos=rtos, profile=profile, run_id=run_id,
        port=port, baud=baud, output_prefix=output_prefix,
        timeout_sec=collector_timeout_sec, pub_mode=pub_mode,
        elf=elf, map_path=map_path, quiet=quiet_collector)
    print(f"\nCollector started (pid={proc.pid}). "
          f"Waiting {collector_start_delay_sec}s before reset...")
    time.sleep(collector_start_delay_sec)

    try:
        openocd_reset_run()
    except SystemExit:
        proc.kill()
        proc.wait()
        raise

    wait_collector(proc, out_p, err_p,
                   collector_timeout_sec + 90, output_prefix)
    analyze_run(output_prefix)

    validated = Path(str(output_prefix) + ".validated.json")
    if not validated.is_file():
        raise SystemExit(
            f"Missing validation manifest after successful collect: {validated}"
        )
    print(f"\nRun {run_id} OK. Validation manifest: {validated}")

    if not skip_report_plot:
        step("Generate exploratory report")
        run_checked([sys.executable,
                     str(REPO_ROOT / "scripts" / "report_results.py"),
                     "--profile", profile],
                    cwd=REPO_ROOT)
        step("Generate plots")
        run_checked([sys.executable,
                     str(REPO_ROOT / "scripts" / "plot_results.py"),
                     "--profile", profile],
                    cwd=REPO_ROOT)
    else:
        step("Report/plot skipped")


# =========================================================================
# Subcommand dispatchers
# =========================================================================

def cmd_build_only(args) -> None:
    preflight(required_build_tools({args.rtos}))
    # ADR-022 gate (Codex round 2 BLOCKER 1): source-only pre-build,
    # full check post-build so a stale ELF cannot block the rebuild
    # that is supposed to fix it. Codex round 3 IMP-2: post-build
    # check is scoped to the RTOS we just built; a stale ChibiOS
    # ELF from a previous run does not fail a freertos/zephyr
    # build-only.
    do_config_alignment_check(args.profile, source_only=True)
    do_build(args.rtos, args.profile, args.publication_mode,
             clean=args.clean)
    do_config_alignment_check(args.profile, source_only=False,
                              rtos=args.rtos)
    do_cflags_audit(args.rtos, args.profile)
    elf, map_path = elf_map_paths(args.rtos, args.profile)
    # Codex IMPORTANT 3: build-only must fail if either canonical
    # artefact is missing, matching the PowerShell hardening.
    if not elf.is_file():
        raise SystemExit(f"build-only: ELF not produced at {elf}")
    if not map_path.is_file():
        raise SystemExit(f"build-only: MAP not produced at {map_path}")
    print(f"\n  {args.rtos} ELF: {elf}")
    print(f"  {args.rtos} ELF SHA256: {sha256_lower(elf)}")
    print(f"  {args.rtos} MAP: {map_path}")
    print(f"  {args.rtos} MAP SHA256: {sha256_lower(map_path)}")


def cmd_smoke(args) -> None:
    run_id = "00" if args.warmup else args.run_id
    _run_smoke(rtos=args.rtos, profile=args.profile, run_id=run_id,
               port=args.port, baud=args.baud,
               collector_timeout_sec=args.collector_timeout_sec,
               collector_start_delay_sec=args.collector_start_delay_sec,
               pub_mode=args.publication_mode,
               clean=args.clean,
               skip_build=args.skip_build,
               skip_report_plot=args.skip_report_plot,
               quiet_collector=args.quiet_collector,
               elf_file=args.elf_file,
               map_file=args.map_file,
               expected_elf_sha=args.expected_elf_sha,
               expected_map_sha=args.expected_map_sha)
    print("\nSmoke completed. Remember: reports are exploratory "
          "unless generated with --publication-gate.")


def cmd_campaign(args) -> None:
    profile = args.profile
    rtoses = args.rtoses
    run_ids = args.run_ids
    pub_mode = args.publication_mode

    # Codex MINOR 1: pkg/tool needs must match the selected
    # operation (only-report is pure host pipeline; skip-report
    # ends after captures and does not need matplotlib).
    if args.only_report:
        need_tools: set[str] = set()
        need_pkgs = {"matplotlib"}
    else:
        need_tools = required_build_tools(set(rtoses)) | {"openocd"}
        need_pkgs = {"serial"}
        if not args.skip_report:
            need_pkgs.add("matplotlib")
    preflight(need_tools, need_pkgs)
    if not args.only_report:
        preflight_serial_port(args.port)

    campaign_start = time.time()
    campaign_hashes: dict[str, dict[str, str]] = {}

    if not args.only_report:
        # ADR-022 gate (Codex round 2 BLOCKER 1 fix):
        # 1. source-only check ONCE before the per-RTOS build loop
        #    (fails fast on a regressed chconf.h/FreeRTOSConfig.h/
        #    prj.conf without inspecting any potentially stale ELF).
        # 2. full check ONCE after the per-RTOS build loop (the
        #    build-layer ELF symbol scan now sees fresh ELFs only).
        do_config_alignment_check(profile, source_only=True)

        for rtos in rtoses:
            step(f"{rtos} / {profile} / build-once (lock artefact hash)")
            do_build(rtos, profile, pub_mode, clean=True)
            do_cflags_audit(rtos, profile)
            elf, map_path = elf_map_paths(rtos, profile)
            elf_sha = sha256_lower(elf)
            map_sha = sha256_lower(map_path)
            print(f"  {rtos} ELF: {elf}")
            print(f"  {rtos} ELF SHA256: {elf_sha}")
            print(f"  {rtos} MAP: {map_path}")
            print(f"  {rtos} MAP SHA256: {map_sha}")
            campaign_hashes[rtos] = {
                "elf": str(elf), "elf_sha256": elf_sha,
                "map": str(map_path), "map_sha256": map_sha,
            }

        # ADR-022 gate post-build: ChibiOS ELF symbol scan +
        # Zephyr generated-.config scan on the freshly built
        # artefacts BEFORE the campaign lock is written. A drift
        # here means the build linked an OSLIB / factory / TM /
        # event subsystem that ADR-022 forbids, or that the
        # Zephyr Kconfig defaults silently regressed a profile
        # option; either way the lock would otherwise immortalise
        # a bad SHA.
        #
        # Codex round 4 MIN-1: when `--rtoses` is a strict subset
        # of {chibios, freertos, zephyr}, run the post-build gate
        # ONCE PER selected RTOS so build-layer scans of artefacts
        # OUTSIDE the subset (e.g. a stale Zephyr .config from a
        # previous campaign) cannot fail this run.
        if set(rtoses) == set(RTOSES):
            do_config_alignment_check(profile, source_only=False)
        else:
            for r in rtoses:
                do_config_alignment_check(profile, source_only=False,
                                          rtos=r)

        manifest_dir = REPO_ROOT / "results" / "manifest"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        lock_path = manifest_dir / f"{profile}_campaign.lock.json"
        lock_obj = {
            "schema": "rtos-benchmark/campaign-lock/v1",
            "profile": profile,
            "publication_mode": pub_mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "rtoses": {r: campaign_hashes[r] for r in rtoses},
        }
        lock_path.write_text(json.dumps(lock_obj, indent=2) + "\n",
                             encoding="utf-8")
        print(f"\nCampaign lock written: {lock_path}")

    if args.only_report:
        step("OnlyReport: skipping all captures")
    else:
        for rtos in rtoses:
            h = campaign_hashes[rtos]
            if not args.skip_warmup:
                step(f"{rtos} / {profile} / run 00 (warmup, excluded)")
                _run_smoke(
                    rtos=rtos, profile=profile, run_id="00",
                    port=args.port, baud=args.baud,
                    collector_timeout_sec=args.collector_timeout_sec,
                    collector_start_delay_sec=2,
                    pub_mode=pub_mode,
                    skip_build=True, skip_report_plot=True,
                    quiet_collector=True,
                    elf_file=h["elf"], map_file=h["map"],
                    expected_elf_sha=h["elf_sha256"],
                    expected_map_sha=h["map_sha256"])
            for n in run_ids:
                rid = f"{n:02d}"
                step(f"{rtos} / {profile} / run {rid}")
                _run_smoke(
                    rtos=rtos, profile=profile, run_id=rid,
                    port=args.port, baud=args.baud,
                    collector_timeout_sec=args.collector_timeout_sec,
                    collector_start_delay_sec=2,
                    pub_mode=pub_mode,
                    skip_build=True, skip_report_plot=True,
                    quiet_collector=True,
                    elf_file=h["elf"], map_file=h["map"],
                    expected_elf_sha=h["elf_sha256"],
                    expected_map_sha=h["map_sha256"])

    elapsed = time.time() - campaign_start
    step(f"Campaign captures done in {elapsed:.0f} s "
         f"({elapsed/60:.1f} min)")

    if args.skip_report:
        print("SkipReport set -- leaving without running publication gate")
        return

    step("report_results.py --publication-gate")
    run_checked([sys.executable,
                 str(REPO_ROOT / "scripts" / "report_results.py"),
                 "--profile", profile, "--publication-gate"],
                cwd=REPO_ROOT)
    step("plot_results.py")
    run_checked([sys.executable,
                 str(REPO_ROOT / "scripts" / "plot_results.py"),
                 "--profile", profile],
                cwd=REPO_ROOT)

    step("Final inventory")
    raw_dir = REPO_ROOT / "results" / "raw"
    for suffix in ("validated.json", "csv", "t4_pi.csv",
                   "banner.txt", "stdout.txt", "map", "elf"):
        cnt = sum(1 for _ in raw_dir.glob(f"*_{profile}_run0[1-5].{suffix}"))
        print(f"  {suffix:<20} {cnt:>3}/15")


def cmd_only_report(args) -> None:
    preflight(set(), {"matplotlib"})
    step("report_results.py --publication-gate")
    run_checked([sys.executable,
                 str(REPO_ROOT / "scripts" / "report_results.py"),
                 "--profile", args.profile, "--publication-gate"],
                cwd=REPO_ROOT)
    step("plot_results.py")
    run_checked([sys.executable,
                 str(REPO_ROOT / "scripts" / "plot_results.py"),
                 "--profile", args.profile],
                cwd=REPO_ROOT)


# =========================================================================
# CLI
# =========================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lab_runner.py",
        description="Cross-platform benchmark pipeline orchestrator "
                    "(build / smoke / campaign / report-only).")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-only",
                       help="Build one (rtos, profile); compute ELF/MAP "
                            "SHA-256; no flash.")
    b.add_argument("--rtos", choices=RTOSES, required=True)
    b.add_argument("--profile", choices=PROFILES, default="fair_perf")
    b.add_argument("--clean", action="store_true",
                   help="Wipe build dir before make (forces fresh AUTORUN).")
    b.add_argument("--publication-mode", choices=PUB_MODES,
                   default="dwt_only")
    b.set_defaults(func=cmd_build_only)

    s = sub.add_parser("smoke",
                       help="Build + flash + collect ONE run; "
                            "optional report/plot.")
    s.add_argument("--rtos", choices=RTOSES, required=True)
    s.add_argument("--profile", choices=PROFILES, default="fair_perf")
    s.add_argument("--run-id", default="01",
                   help='Run id; "00" reserved for warmup (ADR-013).')
    s.add_argument("--port", default=DEFAULT_PORT,
                   help=f"Serial device (default: {DEFAULT_PORT}).")
    s.add_argument("--baud", type=int, default=115200)
    s.add_argument("--collector-timeout-sec", type=int, default=600)
    s.add_argument("--collector-start-delay-sec", type=int, default=2)
    s.add_argument("--publication-mode", choices=PUB_MODES,
                   default="dwt_only")
    s.add_argument("--warmup", action="store_true",
                   help='Force run-id="00".')
    s.add_argument("--clean", action="store_true",
                   help="Wipe build dir + previous run artefacts.")
    s.add_argument("--skip-build", action="store_true")
    s.add_argument("--skip-report-plot", action="store_true")
    s.add_argument("--quiet-collector", action="store_true")
    s.add_argument("--elf-file", default="",
                   help="Override canonical ELF path (campaign lock mode).")
    s.add_argument("--map-file", default="",
                   help="Override canonical MAP path (campaign lock mode).")
    s.add_argument("--expected-elf-sha", default="",
                   help="Abort flash if ELF SHA-256 (lowercase hex) "
                        "differs from this value.")
    s.add_argument("--expected-map-sha", default="",
                   help="Abort flash if MAP SHA-256 differs.")
    s.set_defaults(func=cmd_smoke)

    c = sub.add_parser("campaign",
                       help="Build-once per RTOS + run00 warmup + "
                            "run01..05 + publication-gate + plots.")
    c.add_argument("--profile", choices=PROFILES, default="fair_perf")
    c.add_argument("--rtoses", nargs="+", choices=RTOSES,
                   default=list(RTOSES),
                   help="RTOSes to include (default: all 3).")
    c.add_argument("--run-ids", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    c.add_argument("--port", default=DEFAULT_PORT,
                   help=f"Serial device (default: {DEFAULT_PORT}).")
    c.add_argument("--baud", type=int, default=115200)
    c.add_argument("--collector-timeout-sec", type=int, default=600)
    c.add_argument("--publication-mode", choices=PUB_MODES,
                   default="dwt_only")
    c.add_argument("--skip-warmup", action="store_true",
                   help="Exploratory only; publishable campaigns "
                        "require run00 per ADR-013.")
    c.add_argument("--skip-report", action="store_true",
                   help="Stop after captures (no gate, no plots).")
    c.add_argument("--only-report", action="store_true",
                   help="Skip all build/capture; just gate + plot from "
                        "existing results/raw.")
    c.set_defaults(func=cmd_campaign)

    o = sub.add_parser("only-report",
                       help="(Re-)run report_results.py "
                            "--publication-gate + plot_results.py.")
    o.add_argument("--profile", choices=PROFILES, default="fair_perf")
    o.set_defaults(func=cmd_only_report)

    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
