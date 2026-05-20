#!/usr/bin/env python3
"""
Backward-compatibility wrapper.

Historically this script audited only the Zephyr build dir.
C3-step1 (2026-05-13) generalised the audit to all three
RTOSes via `scripts/cflags_audit.py`. This wrapper keeps the
old CLI working for callers that still invoke
`zephyr_cflags_audit.py --build-dir ... --profile ...` (e.g.
the lab smoke scripts).

It delegates to `cflags_audit.main()` with `--rtos zephyr`
implicitly prepended.
"""

import sys
from pathlib import Path


def _run() -> int:
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from cflags_audit import main as cflags_main  # noqa: E402

    argv = sys.argv[1:]
    if "--rtos" not in argv:
        argv = ["--rtos", "zephyr"] + argv
    return cflags_main(argv)


if __name__ == "__main__":
    sys.exit(_run())
