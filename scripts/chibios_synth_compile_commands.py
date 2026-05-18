#!/usr/bin/env python3
"""
ChibiOS make-dry-run -> compile_commands.json synth (C3-step2).

ChibiOS uses GNU Make, not CMake, so it does not emit a
`compile_commands.json` natively. This script parses the
output of `make -B -n` (a dry-run that prints every recipe
line without executing) and synthesises an equivalent
`compile_commands.json` so that `scripts/cflags_audit.py
--rtos chibios` can audit the effective compile commands
exactly the way it audits the CMake-generated JSON for
Zephyr and FreeRTOS.

Usage:
    # From the chibios Makefile (recommended):
    make compile-commands PROFILE=fair_perf

    # Manual two-step:
    make -B -n all PROFILE=fair_perf > dry.log
    python scripts/chibios_synth_compile_commands.py \\
        --make-log dry.log \\
        --build-dir build/fair_perf \\
        --workdir .

    # Pipe via stdin:
    make -B -n all PROFILE=fair_perf | \\
      python scripts/chibios_synth_compile_commands.py \\
        --make-log - --build-dir build/fair_perf --workdir .

Parsing rules:
  - Each line is stripped of leading whitespace and an
    optional leading `@` (ChibiOS rules.mk silences recipe
    echo with `@`; `make -n` still prints the line with the
    `@` intact, which we strip).
  - Only lines that contain `arm-none-eabi-gcc` are
    considered. (FreeRTOS / Zephyr paths emit different
    compilers; they are out of scope here.)
  - Among those, only lines that include `-c` are compile
    invocations (the link step is not what we audit).
  - The input source is the last token ending in
    `.c` / `.cpp` / `.s` / `.S` that is NOT immediately
    preceded by a flag that takes a path argument (-o, -MF,
    -MT, -x, -include).
  - Each surviving line produces one compile_commands.json
    entry with three fields: `directory` (the workdir
    passed on the CLI), `command` (the line verbatim), and
    `file` (the parsed source path).

Exit codes:
  0  one or more compile commands were parsed and written.
  2  no compile commands could be parsed, or I/O error.
"""

import argparse
import json
import re
import shlex
import sys
from pathlib import Path


GCC_RE = re.compile(r"\barm-none-eabi-gcc\b")
TAKES_PATH_ARG = {"-o", "-MF", "-MT", "-MQ", "-x", "-include",
                  "-isystem", "-I"}
SOURCE_SUFFIXES = (".c", ".cpp", ".cc", ".cxx", ".s", ".S")


def _extract_source(tokens: list[str]) -> str | None:
    """Find the source file in a tokenised compile command.

    Walks the tokens left-to-right, skipping the argument of
    any flag that consumes a path; returns the last
    .c/.cpp/.s/.S token that is not such an argument."""
    last_source = None
    skip_next = False
    for t in tokens:
        if skip_next:
            skip_next = False
            continue
        if t in TAKES_PATH_ARG:
            skip_next = True
            continue
        # Flags of the form -I/path are self-contained.
        if t.startswith("-"):
            continue
        if t.endswith(SOURCE_SUFFIXES):
            last_source = t
    return last_source


def parse_make_log(log: str, workdir: Path) -> list[dict]:
    entries: list[dict] = []
    seen_files: set[str] = set()
    for raw in log.splitlines():
        line = raw.lstrip()
        if line.startswith("@"):
            line = line[1:].lstrip()
        if not GCC_RE.search(line):
            continue
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError:
            # Unbalanced quotes etc -- skip.
            continue
        if "-c" not in tokens:
            continue
        source = _extract_source(tokens)
        if not source:
            continue
        # Resolve the source path against the make
        # working directory so the audit regex (which
        # expects paths like
        # `benchmark_chibios/main.c` or
        # `common/foo.c`) matches. ChibiOS rules.mk
        # prints recipes with bare basenames or
        # `../../foo/bar.c` relative to the make CWD;
        # without this resolve step the audit's
        # in-scope filter misses every app source.
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = (workdir / source).resolve()
            try:
                # Use forward-slashes for cross-platform
                # regex stability (`compile_commands.json`
                # is meant to be tool-portable).
                source = source_path.as_posix()
            except (OSError, ValueError):
                source = str(source_path)
        # Deduplicate: ChibiOS rules.mk may print the same
        # recipe line twice if invoked with `-B` plus a
        # dependent target. Keep only the first occurrence.
        if source in seen_files:
            continue
        seen_files.add(source)
        entries.append({
            "directory": str(workdir),
            "command":   line,
            "file":      source,
        })
    return entries


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--make-log", required=True,
                   help="Path to `make -B -n` output, or `-` "
                        "to read from stdin.")
    p.add_argument("--build-dir", required=True, type=Path,
                   help="Directory in which to write "
                        "compile_commands.json.")
    p.add_argument("--workdir", required=True, type=Path,
                   help="The directory the make invocation "
                        "ran in (used as each entry's "
                        "'directory' field).")
    args = p.parse_args(argv)

    try:
        if args.make_log == "-":
            log = sys.stdin.read()
        else:
            log = Path(args.make_log).read_text(
                encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"FAIL: cannot read make log: {exc}",
              file=sys.stderr)
        return 2

    entries = parse_make_log(log, args.workdir.resolve())
    if not entries:
        print("FAIL: no `arm-none-eabi-gcc -c ...` lines "
              "parsed from the make log; verify the dry-run "
              "produced compile recipes (e.g. `make -B -n "
              "PROFILE=fair_perf all`)",
              file=sys.stderr)
        return 2

    try:
        args.build_dir.mkdir(parents=True, exist_ok=True)
        out = args.build_dir / "compile_commands.json"
        out.write_text(json.dumps(entries, indent=2),
                       encoding="utf-8")
    except OSError as exc:
        print(f"FAIL: cannot write {out}: {exc}",
              file=sys.stderr)
        return 2

    print(f"OK: {len(entries)} compile command(s) written to "
          f"{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
