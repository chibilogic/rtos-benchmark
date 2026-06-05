#!/usr/bin/env python3
"""
Snapshot latency-relevant resolved Zephyr Kconfig values.

Reads the generated `.config` for each publishable profile
(`zephyr/build/<profile>/zephyr/.config`) and writes a small JSON of the
latency-relevant symbols to `results/summary/zephyr_config/<profile>.json`,
so the report renders RESOLVED Kconfig (not raw `prj.conf` fragments).

A symbol absent from `.config` is reported as "not set" (Kconfig omits
unset bool symbols). Run after a Zephyr build (campaign / build-only).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("fair_perf", "realistic_tickless")
NOT_SET = "not set"

# Latency-relevant symbols surfaced in the report. Order is preserved.
SYMBOLS = [
    "CONFIG_MULTITHREADING",
    "CONFIG_SCHED_SIMPLE",
    "CONFIG_SCHED_SCALABLE",
    "CONFIG_SCHED_MULTIQ",
    "CONFIG_PREEMPT_ENABLED",
    "CONFIG_NUM_PREEMPT_PRIORITIES",
    "CONFIG_TIMESLICING",
    "CONFIG_SYS_CLOCK_TICKS_PER_SEC",
    "CONFIG_TICKLESS_KERNEL",
    "CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK",
    "CONFIG_PM",
    "CONFIG_ASSERT",
    "CONFIG_LOG",
    "CONFIG_DEBUG",
    "CONFIG_TRACING",
    "CONFIG_THREAD_RUNTIME_STATS",
    "CONFIG_THREAD_MONITOR",
    "CONFIG_USERSPACE",
    "CONFIG_HEAP_MEM_POOL_SIZE",
    "CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE",
]


def dotconfig_path(profile: str) -> Path:
    return REPO_ROOT / "zephyr" / "build" / profile / "zephyr" / ".config"


def parse_dotconfig(text: str) -> dict:
    """Return {symbol: value} for SYMBOLS; absent symbol -> 'not set'."""
    values = {s: NOT_SET for s in SYMBOLS}
    wanted = set(SYMBOLS)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key in wanted:
            v = val.strip()
            if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                v = v[1:-1]
            values[key] = v
    return values


def snapshot(profile: str) -> dict:
    cfg = dotconfig_path(profile)
    if not cfg.is_file():
        raise FileNotFoundError(
            f"Zephyr .config not found for {profile}: {cfg}. "
            "Build the Zephyr target first (campaign / build-only).")
    try:
        src = str(cfg.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        src = cfg.as_posix()
    return {
        "schema": "rtos-benchmark/zephyr-config/v1",
        "profile": profile,
        "source": src,
        "symbols": parse_dotconfig(cfg.read_text(encoding="utf-8")),
    }


def write_snapshot(profile: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{profile}.json"
    out.write_text(json.dumps(snapshot(profile), indent=2) + "\n",
                   encoding="utf-8")
    return out


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Snapshot resolved Zephyr Kconfig for the report.")
    ap.add_argument("--profiles", nargs="+", default=list(PROFILES),
                    choices=PROFILES)
    ap.add_argument("--out-dir", default=str(
        REPO_ROOT / "results" / "summary" / "zephyr_config"))
    args = ap.parse_args(argv)
    for p in args.profiles:
        print(f"OK: {write_snapshot(p, Path(args.out_dir))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
