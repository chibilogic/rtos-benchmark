#!/usr/bin/env python3
"""
Cross-RTOS firmware footprint extractor (ADR-023 input, scaffold).

Parses the .elf files of the three RTOSes for one publishable
profile and emits:

  - Code size (`.text + .rodata`-like) per ELF.
  - Static RAM used (`.data + .bss + .noinit`-like) per ELF,
    with the ChibiOS `.heap` linker-reservation section
    excluded per ADR-023 Part C decision.
  - Informational "tail reservation" per RTOS:
      ChibiOS  : `__heap_end__ - __heap_base__`  (== `.heap` size)
      FreeRTOS : `_estack - __bss_end__`         (descending main stack)
      Zephyr   : `__kernel_ram_end - _end`       (spare RAM for k_thread_create)

The methodology is grounded in
`notes/AUDIT-2026-05-21-tool-and-ram-equivalence.md` and the
binding user decisions captured in its "Part C - Decisions for
ADR-023" section.

Status: ADR-023 accepted (2026-06-01). Implements the publication
methodology: `--from-raw` resolves the manifest-bound
`results/raw/<rtos>_<profile>_run01.elf` and `--verify-lock`
cross-checks the computed ELF SHA-256 against the campaign lock
`results/manifest/<profile>_campaign.lock.json`. Remaining follow-up:
  - per-archive code-size breakdown (kernel / HAL / libc / app)
    via `arm-none-eabi-nm --print-size` filtered by archive
    (`--by-archive`, deferred per ADR-023).

Outputs:

  - `<out-dir>/<profile>_footprint.json` : machine-readable
    manifest with schema_version, per-ELF sections + computed
    metrics, ranking tables.
  - `<out-dir>/<profile>_footprint.md`   : human-readable
    Markdown summary (the same table the report PDF will use).

Tool dependencies:
  - `arm-none-eabi-readelf` (preferred; provides fixed-format
    section headers via `-S -W`).
  - `arm-none-eabi-nm` for the heap/stack/end symbols.
  Both must be on PATH (typically activated via env.bat / env.sh
  per ADR-021).

Exit codes:
  0  every requested RTOS produced a valid footprint manifest
  2  audit failed (missing ELF, parsing error, tool missing,
     unexpected section layout that would invalidate the
     methodology); details on stderr

Usage:
    python scripts/footprint.py \\
        --profile fair_perf \\
        --chibios-elf chibios/benchmark_chibios/build/fair_perf/benchmark_chibios.elf \\
        --freertos-elf freertos/benchmark_freertos/build/fair_perf/benchmark_freertos.elf \\
        --zephyr-elf zephyr/build/fair_perf/zephyr/zephyr.elf \\
        --out-dir results/summary/footprint/

    # Or auto-detect ELFs from the project layout (build/ tree):
    python scripts/footprint.py --profile fair_perf --auto

    # Publication: read the manifest-bound binary + verify the lock:
    python scripts/footprint.py --profile fair_perf --from-raw \\
        --verify-lock

ADR references: ADR-009 (libc divergence is intentional),
ADR-017 (.map archival), ADR-022 (kernel feature equivalence),
ADR-023 (to be drafted; this script is its execution engine).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# ----------------------------------------------------------------------
# Configuration (ADR-023 Part C, binding)
# ----------------------------------------------------------------------

SCHEMA_VERSION = "1.0"

SUPPORTED_RTOSES = ("chibios", "freertos", "zephyr")
PUBLISHABLE_PROFILES = ("fair_perf", "realistic_tickless")

# Per-RTOS section name that holds an unused-but-linker-reserved
# RAM region. Subtracted from the "static RAM used" metric.
# Future ADRs should keep this list short and well-documented:
# do NOT add a section here just to flatter a ranking.
EXCLUDED_BSS_SECTIONS_BY_RTOS = {
    "chibios":  (".heap",),   # __heap_base__..__heap_end__ when USE_HEAP=FALSE
    "freertos": (),
    "zephyr":   (),
}

# Per-RTOS tail-reservation symbol pair. Used for the informational
# "tail reservation" column (NOT part of the RAM used number).
TAIL_RESERVATION_SYMBOLS_BY_RTOS = {
    "chibios":  ("__heap_base__", "__heap_end__"),
    "freertos": ("__bss_end__",   "_estack"),
    "zephyr":   ("_end",          "__kernel_ram_end"),
}

# Per-RTOS extra committed-stack reservations that are NOT counted
# inside `.bss` / `noinit` and would otherwise create a fairness gap
# (Codex round 2 IMP-1 fix). For each entry, the named symbol is
# resolved via `nm` and its value is read as an absolute size in
# bytes. The size is ADDED to "static RAM used" so all three RTOSes
# account for their main-stack reservation symmetrically.
#
# Methodology rationale:
#   - ChibiOS: the main + process stacks live in DTCM
#     (`0x20000000..0x20000800`), declared as ABSOLUTE symbols
#     (__main_stack_size__ + __process_stack_size__) by the
#     ChibiOS-provided startup linker script. They are NOT a
#     labelled section, so the per-section scan misses them.
#   - FreeRTOS: the project's startup linker script reserves
#     `_Min_Stack_Size` (typically 4 KB) as the main stack at the
#     top of AXI SRAM. The reserved region is the actual main
#     stack; the unused remainder is genuinely spare.
#   - Zephyr: thread stacks live in the `noinit` section which is
#     already counted; nothing extra to add (empty tuple).
EXTRA_STATIC_STACK_SYMBOLS_BY_RTOS: dict[str, tuple[str, ...]] = {
    "chibios":  ("__main_stack_size__", "__process_stack_size__"),
    "freertos": ("_Min_Stack_Size",),
    "zephyr":   (),
}

# STM32H750 memory map. VMAs in these flash ranges are "code/
# rodata"; everything else with ALLOC flag is RAM-side.
FLASH_RANGES = (
    (0x08000000, 0x08020000),   # 128 KB Flash bank 0
    (0x90000000, 0x98000000),   # external QSPI (defined-not-used)
)

# Default project layout: when `--auto` is used, ELFs are
# resolved from PROJECT_ROOT / DEFAULT_ELF_PATHS[rtos][profile].
DEFAULT_ELF_PATHS = {
    "chibios": {
        "fair_perf":
            "chibios/benchmark_chibios/build/fair_perf/benchmark_chibios.elf",
        "realistic_tickless":
            "chibios/benchmark_chibios/build/realistic_tickless/"
            "benchmark_chibios.elf",
    },
    "freertos": {
        "fair_perf":
            "freertos/benchmark_freertos/build/fair_perf/benchmark_freertos.elf",
        "realistic_tickless":
            "freertos/benchmark_freertos/build/realistic_tickless/"
            "benchmark_freertos.elf",
    },
    "zephyr": {
        "fair_perf":
            "zephyr/build/fair_perf/zephyr/zephyr.elf",
        "realistic_tickless":
            "zephyr/build/realistic_tickless/zephyr/zephyr.elf",
    },
}


# ----------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Section:
    """One ELF section header row, as reported by `readelf -S -W`."""
    index: int
    name: str
    type: str          # PROGBITS / NOBITS / NULL / NOTE / ARM_EXIDX / ...
    addr: int          # VMA
    size: int
    flags: str         # e.g. "AX", "AW", "WA"

    @property
    def is_alloc(self) -> bool:
        return "A" in self.flags

    @property
    def is_write(self) -> bool:
        return "W" in self.flags

    @property
    def is_exec(self) -> bool:
        return "X" in self.flags

    @property
    def in_flash(self) -> bool:
        for lo, hi in FLASH_RANGES:
            if lo <= self.addr < hi:
                return True
        return False


@dataclass
class FootprintRecord:
    rtos: str
    profile: str
    elf_path: str
    elf_sha256: str
    elf_size_bytes: int

    code_size_total: int = 0
    code_size_by_section: list[dict] = field(default_factory=list)

    ram_data: int = 0
    ram_bss_raw: int = 0
    ram_bss_excluded: int = 0
    ram_bss_excluded_section: str | None = None
    ram_extra_stacks: int = 0
    ram_extra_stacks_breakdown: list[dict] = field(default_factory=list)
    ram_static_used: int = 0
    ram_by_section: list[dict] = field(default_factory=list)

    tail_reservation_size: int | None = None
    tail_reservation_basis: str | None = None

    # ADR-023 publication provenance.
    elf_source: str = "build"            # "raw" | "build" | "override"
    lock_sha256_match: bool | None = None


# ----------------------------------------------------------------------
# Tool wrappers
# ----------------------------------------------------------------------

def _need(tool: str) -> str:
    """Resolve `tool` on PATH or fail-stop with exit code 2."""
    path = shutil.which(tool)
    if path is None:
        sys.stderr.write(
            f"footprint: required tool '{tool}' not found on PATH. "
            f"Activate the project env (env.bat / env.sh, ADR-021) "
            f"and retry.\n"
        )
        sys.exit(2)
    return path


# readelf -S -W output line for a section, after the "Section Headers:"
# header. readelf emits the name on its own line wrapped in [] when
# `-W` (wide) is set; the row that follows packs the rest.
_READELF_SECTION_RE = re.compile(
    r"^\s*\[\s*(?P<idx>\d+)\]\s+"
    r"(?P<name>\S+|)\s+"
    r"(?P<type>\S+)\s+"
    r"(?P<addr>[0-9a-fA-F]+)\s+"
    r"(?P<off>[0-9a-fA-F]+)\s+"
    r"(?P<size>[0-9a-fA-F]+)\s+"
    r"(?P<es>[0-9a-fA-F]+)\s+"
    r"(?P<flags>[A-Za-z]*)\s"
)


def _parse_readelf_sections(elf_path: Path) -> list[Section]:
    """Run `readelf -S -W` and parse section headers."""
    readelf = _need("arm-none-eabi-readelf")
    out = subprocess.run(
        [readelf, "-S", "-W", str(elf_path)],
        check=False, capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.stderr.write(
            f"footprint: arm-none-eabi-readelf failed on {elf_path}: "
            f"{out.stderr.strip()}\n"
        )
        sys.exit(2)

    sections: list[Section] = []
    for line in out.stdout.splitlines():
        m = _READELF_SECTION_RE.match(line)
        if not m:
            continue
        # Skip the NULL section (index 0, no useful info).
        if int(m.group("idx")) == 0:
            continue
        sections.append(Section(
            index=int(m.group("idx")),
            name=m.group("name"),
            type=m.group("type"),
            addr=int(m.group("addr"), 16),
            size=int(m.group("size"), 16),
            flags=m.group("flags") or "",
        ))
    if not sections:
        sys.stderr.write(
            f"footprint: no sections parsed from {elf_path}; readelf output "
            f"format may have changed. Re-run with --verbose to inspect.\n"
        )
        sys.exit(2)
    return sections


_NM_LINE_RE = re.compile(
    r"^(?P<addr>[0-9a-fA-F]+)\s+(?P<type>[A-Za-z?])\s+(?P<name>\S+)\s*$"
)


def _parse_nm_symbols(elf_path: Path) -> dict[str, int]:
    """Run `nm` and return {symbol_name: address} for absolute and global syms."""
    nm = _need("arm-none-eabi-nm")
    out = subprocess.run(
        [nm, str(elf_path)],
        check=False, capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.stderr.write(
            f"footprint: arm-none-eabi-nm failed on {elf_path}: "
            f"{out.stderr.strip()}\n"
        )
        sys.exit(2)
    syms: dict[str, int] = {}
    for line in out.stdout.splitlines():
        m = _NM_LINE_RE.match(line)
        if not m:
            continue
        syms[m.group("name")] = int(m.group("addr"), 16)
    return syms


# ----------------------------------------------------------------------
# Core analysis
# ----------------------------------------------------------------------

def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_code_or_rodata(s: Section) -> bool:
    """PROGBITS section in flash, ALLOC set, NOT writable."""
    return s.type == "PROGBITS" and s.is_alloc and not s.is_write \
        and s.in_flash


def _is_ram_data(s: Section) -> bool:
    """PROGBITS section with ALLOC+WRITE -> .data-like."""
    return s.type == "PROGBITS" and s.is_alloc and s.is_write


def _is_ram_bss(s: Section) -> bool:
    """NOBITS section with ALLOC+WRITE -> .bss/.noinit/.heap-like."""
    return s.type == "NOBITS" and s.is_alloc and s.is_write


def analyze_elf(rtos: str, profile: str, elf_path: Path) -> FootprintRecord:
    """Compute the FootprintRecord for one ELF."""
    if not elf_path.exists():
        sys.stderr.write(
            f"footprint: ELF not found: {elf_path}\n"
        )
        sys.exit(2)

    sections = _parse_readelf_sections(elf_path)
    syms = _parse_nm_symbols(elf_path)

    rec = FootprintRecord(
        rtos=rtos,
        profile=profile,
        elf_path=str(elf_path),
        elf_sha256=_sha256_of_file(elf_path),
        elf_size_bytes=elf_path.stat().st_size,
    )

    excluded = EXCLUDED_BSS_SECTIONS_BY_RTOS.get(rtos, ())

    for s in sections:
        if _is_code_or_rodata(s):
            rec.code_size_total += s.size
            rec.code_size_by_section.append({
                "name": s.name,
                "size": s.size,
                "vma": f"0x{s.addr:08x}",
            })
        elif _is_ram_data(s):
            rec.ram_data += s.size
            rec.ram_by_section.append({
                "name": s.name,
                "type": "PROGBITS",
                "size": s.size,
                "vma": f"0x{s.addr:08x}",
                "excluded": False,
            })
        elif _is_ram_bss(s):
            rec.ram_bss_raw += s.size
            entry_excluded = s.name in excluded
            if entry_excluded:
                rec.ram_bss_excluded += s.size
                # First excluded section wins for the manifest label;
                # if any RTOS ever lists more than one, surface both.
                if rec.ram_bss_excluded_section is None:
                    rec.ram_bss_excluded_section = s.name
                else:
                    rec.ram_bss_excluded_section += f", {s.name}"
            rec.ram_by_section.append({
                "name": s.name,
                "type": "NOBITS",
                "size": s.size,
                "vma": f"0x{s.addr:08x}",
                "excluded": entry_excluded,
            })

    # Extra committed stack reservations not visible as sections
    # (Codex round 2 IMP-1). These are ABSOLUTE size symbols whose
    # numeric value IS the size in bytes (NOT an address). nm
    # reports them with type 'A' (absolute).
    for sym_name in EXTRA_STATIC_STACK_SYMBOLS_BY_RTOS.get(rtos, ()):
        if sym_name in syms:
            size = syms[sym_name]
            rec.ram_extra_stacks += size
            rec.ram_extra_stacks_breakdown.append({
                "symbol": sym_name,
                "size": size,
            })
        else:
            sys.stderr.write(
                f"footprint: WARNING: extra-stack symbol "
                f"{sym_name!r} not found in {elf_path}; "
                f"the per-RTOS extra-stacks total may be incomplete.\n"
            )

    rec.ram_static_used = (rec.ram_data + rec.ram_bss_raw
                           - rec.ram_bss_excluded
                           + rec.ram_extra_stacks)

    # Tail reservation from symbols.
    sym_lo, sym_hi = TAIL_RESERVATION_SYMBOLS_BY_RTOS[rtos]
    if sym_lo in syms and sym_hi in syms:
        size = syms[sym_hi] - syms[sym_lo]
        # For FreeRTOS the "tail" between __bss_end__ and _estack
        # includes _Min_Stack_Size (now counted as ram_extra_stacks).
        # Subtract it so the informational tail is the truly-spare
        # portion only.
        if rtos == "freertos" and rec.ram_extra_stacks:
            size -= rec.ram_extra_stacks
        if size >= 0:
            rec.tail_reservation_size = size
            rec.tail_reservation_basis = f"{sym_hi} - {sym_lo}"
            if rtos == "freertos" and rec.ram_extra_stacks:
                rec.tail_reservation_basis += " - _Min_Stack_Size"
    if rec.tail_reservation_size is None:
        sys.stderr.write(
            f"footprint: WARNING: tail-reservation symbols "
            f"({sym_lo!r}, {sym_hi!r}) not found in {elf_path}; "
            f"tail column will be omitted for this ELF.\n"
        )

    return rec


# ----------------------------------------------------------------------
# Output rendering
# ----------------------------------------------------------------------

def render_markdown(records: list[FootprintRecord], profile: str) -> str:
    """Human-readable summary, suitable for direct inclusion in
    `report_results.py` compare-profile MDs."""
    lines: list[str] = []
    lines.append(f"# Firmware footprint -- profile `{profile}`\n")
    lines.append(
        "Metric definition per ADR-023 (binding):\n"
        "- **Code size** = `.text + .rodata` (PROGBITS sections in flash, "
        "ALLOC set, not writable). Bundles kernel + HAL + libc; see libc "
        "disclaimer below.\n"
        "- **Static RAM used** = `.data + .bss + noinit` (ALLOC+WRITE "
        "PROGBITS + NOBITS in RAM), with the ChibiOS `.heap` "
        "linker-script reservation excluded "
        "(`CH_CFG_USE_HEAP=FALSE`, the region holds no allocation), "
        "PLUS per-RTOS extra committed-stack reservations not visible "
        "as labelled sections (Codex round 2 IMP-1 fix): ChibiOS DTCM "
        "`__main_stack_size__` + `__process_stack_size__` (2 KB), "
        "FreeRTOS `_Min_Stack_Size` (4 KB main stack reservation in "
        "AXI SRAM). Zephyr already covers all thread stacks via the "
        "`noinit` section, so no extra add is needed.\n"
        "- **Tail reservation** is informational only: spare RAM kept "
        "available for the descending main stack (FreeRTOS), "
        "k_thread_create runtime stacks (Zephyr), or the linker heap "
        "reservation (ChibiOS). For FreeRTOS the reported tail "
        "EXCLUDES `_Min_Stack_Size` (counted in static RAM used).\n"
    )
    lines.append("")
    lines.append("## Headline\n")
    lines.append(
        "| RTOS | code size (B) | static RAM used (B) | "
        "tail reservation (B, info) |"
    )
    lines.append(
        "| --- | ---: | ---: | ---: |"
    )
    for r in records:
        tail = (
            f"{r.tail_reservation_size}"
            if r.tail_reservation_size is not None else "n/a"
        )
        lines.append(
            f"| {r.rtos} | {r.code_size_total} | "
            f"{r.ram_static_used} | {tail} |"
        )
    lines.append("")
    lines.append("## libc disclaimer (ADR-009)\n")
    lines.append(
        "The three RTOSes intentionally link three different libc "
        "implementations (ADR-009 sec. \"Linker flags\"):\n"
        "- ChibiOS  : newlib full (no `--specs=nano.specs`); ChibiOS "
        "supplies its own startup and syscall stubs.\n"
        "- FreeRTOS : newlib-nano via `--specs=nano.specs --specs=nosys.specs`.\n"
        "- Zephyr   : picolibc (Zephyr default at v4.4.0).\n"
        "The code-size number above bundles kernel + HAL + libc and is "
        "NOT a pure kernel-text comparison. A per-archive breakdown is a "
        "follow-up deliverable (`footprint.py --by-archive`).\n"
    )
    lines.append("")
    lines.append("## Per-ELF detail\n")
    for r in records:
        lines.append(f"### {r.rtos} {r.profile}\n")
        lines.append(f"- ELF: `{r.elf_path}`")
        lines.append(f"- ELF source: {r.elf_source}")
        lines.append(f"- SHA-256: `{r.elf_sha256}`")
        if r.lock_sha256_match is not None:
            lines.append(
                f"- Campaign-lock SHA match: "
                f"{'yes' if r.lock_sha256_match else 'NO'}"
            )
        lines.append(f"- ELF on disk: {r.elf_size_bytes} bytes")
        lines.append(f"- Code (text+rodata-like): {r.code_size_total} B")
        lines.append(f"  - sections:")
        for s in r.code_size_by_section:
            lines.append(f"    - {s['name']} @ {s['vma']}: {s['size']} B")
        lines.append(f"- RAM data (PROGBITS+AW): {r.ram_data} B")
        lines.append(f"- RAM bss raw (NOBITS+AW total): {r.ram_bss_raw} B")
        if r.ram_bss_excluded:
            lines.append(
                f"- RAM bss excluded "
                f"({r.ram_bss_excluded_section}): {r.ram_bss_excluded} B"
            )
        if r.ram_extra_stacks:
            parts = ", ".join(
                f"{e['symbol']}={e['size']}"
                for e in r.ram_extra_stacks_breakdown
            )
            lines.append(
                f"- RAM extra committed stacks: "
                f"{r.ram_extra_stacks} B ({parts})"
            )
        lines.append(
            f"- Static RAM used "
            f"(data + bss - excluded + extra-stacks): "
            f"{r.ram_static_used} B"
        )
        if r.tail_reservation_size is not None:
            lines.append(
                f"- Tail reservation "
                f"({r.tail_reservation_basis}): "
                f"{r.tail_reservation_size} B"
            )
        lines.append("")
    return "\n".join(lines)


def render_json(records: list[FootprintRecord], profile: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scripts/footprint.py",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "methodology_adr": "ADR-023",
        "elfs": [asdict(r) for r in records],
    }


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _resolve_elf_path(rtos: str, profile: str,
                      project_root: Path) -> Path | None:
    rel = DEFAULT_ELF_PATHS.get(rtos, {}).get(profile)
    if rel is None:
        return None
    p = project_root / rel
    return p if p.exists() else None


def _resolve_raw_elf_path(rtos: str, profile: str,
                          project_root: Path) -> Path | None:
    """Resolve the manifest-bound publication ELF (ADR-023).

    The lab campaign archives the exact binary that produced the
    published runtime numbers as
    `results/raw/<rtos>_<profile>_run01.elf`; its SHA-256 is locked
    in the campaign manifest. This is the source-of-truth ELF for
    the published footprint.
    """
    p = (project_root / "results" / "raw"
         / f"{rtos}_{profile}_run01.elf")
    return p if p.exists() else None


def _load_campaign_lock(profile: str,
                        project_root: Path) -> dict | None:
    """Load `results/manifest/<profile>_campaign.lock.json` or None."""
    p = (project_root / "results" / "manifest"
         / f"{profile}_campaign.lock.json")
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _verify_lock(records: list[FootprintRecord], profile: str,
                 project_root: Path) -> int:
    """Cross-check each analysed ELF SHA-256 against the campaign lock.

    Sets `rec.lock_sha256_match` on every record. Returns 0 when all
    records match the lock, 2 on any mismatch / missing lock (ADR-023
    publication gate).
    """
    lock = _load_campaign_lock(profile, project_root)
    if lock is None:
        sys.stderr.write(
            f"footprint: --verify-lock requested but campaign lock not "
            f"found: results/manifest/{profile}_campaign.lock.json\n"
        )
        return 2
    lock_rtoses = lock.get("rtoses", {})
    mismatches: list[str] = []
    for rec in records:
        locked = lock_rtoses.get(rec.rtos, {}).get("elf_sha256")
        if locked is None:
            rec.lock_sha256_match = False
            mismatches.append(
                f"{rec.rtos}: no elf_sha256 in campaign lock")
        elif locked.lower() != rec.elf_sha256.lower():
            rec.lock_sha256_match = False
            mismatches.append(
                f"{rec.rtos}: analysed ELF SHA-256 "
                f"{rec.elf_sha256[:16]}... != lock {locked[:16]}...")
        else:
            rec.lock_sha256_match = True
    if mismatches:
        sys.stderr.write(
            "footprint: --verify-lock FAILED; analysed ELF(s) do not "
            "match the campaign lock:\n"
        )
        for m in mismatches:
            sys.stderr.write(f"  - {m}\n")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract firmware footprint per ADR-023 from one or more "
            "RTOS ELFs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profile", required=True, choices=PUBLISHABLE_PROFILES,
        help="Build profile being audited.",
    )
    parser.add_argument(
        "--auto", action="store_true",
        help=(
            "Auto-resolve ELFs from the project layout (build/ tree) "
            "for all 3 RTOSes (default if no --*-elf / --from-raw "
            "option is given)."
        ),
    )
    parser.add_argument(
        "--from-raw", action="store_true",
        help=(
            "Resolve ELFs from the manifest-bound publication copies "
            "results/raw/<rtos>_<profile>_run01.elf instead of the "
            "build/ tree (ADR-023 publication path)."
        ),
    )
    parser.add_argument(
        "--verify-lock", action="store_true",
        help=(
            "Cross-check each analysed ELF SHA-256 against "
            "results/manifest/<profile>_campaign.lock.json; exit 2 on "
            "mismatch or missing lock (ADR-023)."
        ),
    )
    for r in SUPPORTED_RTOSES:
        parser.add_argument(
            f"--{r}-elf", default=None,
            help=f"Override the default {r} ELF path.",
        )
    parser.add_argument(
        "--out-dir", default=None,
        help=(
            "Where to write <profile>_footprint.{json,md}. Default: "
            "<project>/results/summary/footprint/."
        ),
    )
    parser.add_argument(
        "--project-root", default=None,
        help="Project root (default: script's grand-parent).",
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="Print Markdown to stdout in addition to file output.",
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root) if args.project_root \
        else Path(__file__).resolve().parent.parent
    out_dir = Path(args.out_dir) if args.out_dir \
        else project_root / "results" / "summary" / "footprint"

    elf_overrides = {
        "chibios":  args.chibios_elf,
        "freertos": args.freertos_elf,
        "zephyr":   args.zephyr_elf,
    }
    any_override = any(v is not None for v in elf_overrides.values())
    if not args.auto and not args.from_raw and not any_override:
        # Default development behaviour: resolve from the build/ tree.
        args.auto = True

    records: list[FootprintRecord] = []
    missing: list[str] = []
    for rtos in SUPPORTED_RTOSES:
        if elf_overrides[rtos]:
            elf = Path(elf_overrides[rtos]).resolve()
            source = "override"
        elif args.from_raw:
            elf = _resolve_raw_elf_path(rtos, args.profile, project_root)
            source = "raw"
        else:
            elf = _resolve_elf_path(rtos, args.profile, project_root)
            source = "build"
        if elf is None or not elf.exists():
            missing.append(rtos)
            continue
        rec = analyze_elf(rtos, args.profile, elf)
        rec.elf_source = source
        records.append(rec)

    if missing:
        where = ("results/raw/<rtos>_<profile>_run01.elf"
                 if args.from_raw else "the build/<profile>/ tree")
        sys.stderr.write(
            f"footprint: ELFs missing for: {', '.join(missing)} "
            f"(looked in {where}). Build/collect them first or pass "
            f"--<rtos>-elf overrides.\n"
        )
        return 2

    # ADR-023: cross-check the published binary SHA against the
    # campaign lock so the footprint provably comes from the same
    # ELF that produced the published runtime numbers.
    if args.verify_lock:
        rc = _verify_lock(records, args.profile, project_root)
        if rc != 0:
            return rc

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{args.profile}_footprint.json"
    md_path = out_dir / f"{args.profile}_footprint.md"
    json_path.write_text(
        json.dumps(render_json(records, args.profile),
                   indent=2, sort_keys=False),
        encoding="utf-8",
    )
    md_text = render_markdown(records, args.profile)
    md_path.write_text(md_text, encoding="utf-8")

    if args.stdout:
        sys.stdout.write(md_text)

    sys.stderr.write(
        f"footprint: wrote {json_path}\n"
        f"footprint: wrote {md_path}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
