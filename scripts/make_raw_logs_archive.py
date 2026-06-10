#!/usr/bin/env python3
"""
Package the publishable raw-logs subset for external verification (reviewer
item #1: "publish the raw logs ... so the published medians can be
recomputed by anyone").

Selects EXACTLY the publishable matrix (3 RTOSes x 2 publishable profiles x
run01..run05) and FAILS (non-zero) if any expected file is missing or if any
unexpected publishable-surface file (a debug_dev run, an unexpected RTOS, an
out-of-range run id, an unexpected campaign lock) is present -- a public
asset must never silently ship exploratory or stale artifacts.

Included (under results/):
  - raw/<rtos>_<profile>_run0[1-5].{csv,t4_pi.csv,banner.txt,validated.json}
  - raw/<rtos>_<profile>_run01.elf         (firmware SHA / loadable-image
                                            cross-check; .map not shipped)
  - manifest/<profile>_campaign.lock.json  (campaign ELF/MAP SHA locks)
  - summary/**  (published aggregates / footprint / resolved Zephyr config;
                 any debug_dev path is excluded)
  - README.md   (raw-log format reference)

Excludes run00 warmup, *.stdout.txt, *.collector.*, plots, the _archived_*
trees and _campaign_logs. Writes a deterministic tar.gz + zip (top-dir named
by a content digest covering BOTH the file manifest and the generated
README.txt) plus an inner MANIFEST.sha256 and an outer SHA256SUMS into dist/.
The code repository keeps results/ gitignored; this archive is the separate
"raw logs" publication asset whose hosted URL becomes PUBLIC_RAW_LOGS_URL.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import re
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS = REPO_ROOT / "results"
DIST = REPO_ROOT / "dist"
FIXED_MTIME = 0
FIXED_MODE = 0o644
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

RTOSES = ("chibios", "freertos", "zephyr")
PUB_PROFILES = ("fair_perf", "realistic_tickless")
RUNS = ("01", "02", "03", "04", "05")
RAW_SUFFIXES = (".csv", ".t4_pi.csv", ".banner.txt", ".validated.json")
# run00 is the legitimate warmup (excluded from the archive, NOT an error).
VALID_RUN_IDS = ("00",) + RUNS

# Per-run artifact name: <rtos>_<profile>_run<NN>.<suffix>.
_NAME_RE = re.compile(r"^([a-z]+)_([a-z_]+)_run(\d{2})\.(.+)$")


def expected_raw_data() -> set[str]:
    return {f"{r}_{p}_run{run}{suf}"
            for r in RTOSES for p in PUB_PROFILES
            for run in RUNS for suf in RAW_SUFFIXES}


def expected_run01_binaries() -> set[str]:
    # Only the run01 .elf is shipped. The .map files are intentionally not
    # published (avoids committing build artifacts with absolute toolchain
    # paths); their map_sha256 stays in the campaign lock for a reviewer who
    # rebuilds. See ADR-025.
    return {f"{r}_{p}_run01.elf" for r in RTOSES for p in PUB_PROFILES}


def expected_locks() -> set[str]:
    return {f"{p}_campaign.lock.json" for p in PUB_PROFILES}


def collect_files() -> list[Path]:
    """Return the sorted publishable file list, or raise SystemExit.

    Whitelists the exact publishable matrix and refuses to package if a
    required file is missing or an unexpected publishable-surface file is
    present.
    """
    raw = RESULTS / "raw"
    manifest = RESULTS / "manifest"
    summary = RESULTS / "summary"
    selected: set[Path] = set()
    errors: list[str] = []

    # Raw data + run01 binaries: exact whitelist.
    exp_raw = expected_raw_data() | expected_run01_binaries()
    for name in sorted(exp_raw):
        p = raw / name
        if p.is_file():
            selected.add(p)
        else:
            errors.append(f"missing required raw file: {name}")
    # Unexpected publishable-surface files in raw/ (iterdir is non-recursive,
    # so it never descends into the _archived_* subtrees).
    if raw.is_dir():
        for p in sorted(raw.iterdir()):
            if not p.is_file():
                continue
            m = _NAME_RE.match(p.name)
            if not m:
                continue
            rtos, profile, run, _suf = m.groups()
            if rtos not in RTOSES or profile not in PUB_PROFILES:
                errors.append(
                    f"unexpected raw file (non-publishable surface): {p.name}")
            elif run not in VALID_RUN_IDS:
                errors.append(f"unexpected run id in raw file: {p.name}")

    # Campaign locks: exact.
    exp_lock = expected_locks()
    for name in sorted(exp_lock):
        p = manifest / name
        if p.is_file():
            selected.add(p)
        else:
            errors.append(f"missing required lock: {name}")
    if manifest.is_dir():
        for p in sorted(manifest.glob("*.lock.json")):
            if p.name not in exp_lock:
                errors.append(f"unexpected lock file: {p.name}")

    # Summary tree: include everything except debug_dev; require the
    # per-profile footprint + zephyr-config the report depends on.
    if summary.is_dir():
        for p in summary.rglob("*"):
            if p.is_file() and "debug_dev" not in p.relative_to(
                    summary).as_posix():
                selected.add(p)
    for profile in PUB_PROFILES:
        for req in (summary / "footprint" / f"{profile}_footprint.json",
                    summary / "zephyr_config" / f"{profile}.json"):
            if not req.is_file():
                errors.append("missing required summary file: "
                              + req.relative_to(RESULTS).as_posix())

    readme = RESULTS / "README.md"
    if readme.is_file():
        selected.add(readme)
    else:
        errors.append("missing results/README.md")

    if errors:
        raise SystemExit(
            "make_raw_logs_archive: refusing to package (publishable "
            "surface not exactly as expected):\n  - " + "\n  - ".join(errors))
    # Portable, deterministic order: sort by the repo-relative POSIX path
    # (case-sensitive) so Windows and Linux produce the same member order.
    return sorted(selected, key=lambda p: p.relative_to(REPO_ROOT).as_posix())


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(files: list[Path]) -> str:
    lines = [f"{sha256_file(p)}  {p.relative_to(REPO_ROOT).as_posix()}  "
             f"{p.stat().st_size}" for p in files]
    return "\n".join(lines) + "\n"


def build_readme(source_ref: str) -> str:
    if source_ref:
        src = (f"Source tree for reproduction: {source_ref}\n"
               "Pair these raw logs with exactly that source tree.\n")
    else:
        src = ("Source tree for reproduction: attach this archive to the\n"
               "same public release/tag as the code package\n"
               "(rtos-benchmark-<commit>).\n")
    return (
        "RTOS Benchmark - Phase 1 raw logs (publishable subset)\n"
        "======================================================\n\n"
        + src + "\n"
        "Contents (under results/):\n"
        "  raw/<rtos>_<profile>_run0[1-5].csv          per-iteration cycles\n"
        "  raw/<rtos>_<profile>_run0[1-5].t4_pi.csv    T4 priority-inheritance\n"
        "  raw/<rtos>_<profile>_run0[1-5].banner.txt   boot register witness\n"
        "  raw/<rtos>_<profile>_run0[1-5].validated.json  per-run gate result\n"
        "  raw/<rtos>_<profile>_run01.elf              firmware (SHA check)\n"
        "  manifest/<profile>_campaign.lock.json       ELF/MAP/loadable SHA-256\n"
        "  summary/                                    published aggregates\n"
        "  README.md                                   raw-log format reference\n"
        "  LICENSE, LICENSES/, NOTICE.txt              license texts + binary\n"
        "                                              distribution notices\n\n"
        "Excluded: run00 warmup, stdout/collector logs, plots, archived\n"
        "datasets, and the .map files (their map_sha256 stays in the campaign\n"
        "lock for anyone who rebuilds).\n\n"
        "Verify firmware identity (ADR-025): rebuild from the paired source\n"
        "tree with the official toolchain and the publication-mode AUTORUN,\n"
        "then compare the loadable image (arm-none-eabi-objcopy -O binary,\n"
        "sha256) to loadable_image_sha256 in\n"
        "results/manifest/<profile>_campaign.lock.json. The shipped run01 .elf\n"
        "also matches elf_sha256; the full ELF/MAP SHA may differ only in\n"
        "DWARF/debug after source comment edits.\n"
        "Recompute medians: per-run CSVs use the sorted-index percentile\n"
        "(ADR-013); see scripts/analyze_results.py and report_results.py in\n"
        "the code repository. MANIFEST.sha256 lists the sha256 of every file.\n\n"
        "Paths: the textual/JSON path fields are repo-relative. The only\n"
        "absolute paths in this archive are inside the six run01 .elf files\n"
        "(DWARF debug info / toolchain paths) -- benign build provenance, no\n"
        "secrets, intrinsic to the SHA-pinned measured binaries, not rewritten.\n"
    )


def build_notice(source_ref: str) -> str:
    src = source_ref or ("the matching public release/tag "
                         "(rtos-benchmark-<commit>)")
    return (
        "BINARY DISTRIBUTION NOTICES - published firmware images\n"
        "======================================================\n\n"
        "This archive ships six prebuilt firmware images under\n"
        "results/raw/<rtos>_<profile>_run01.elf. Each contains separately\n"
        "licensed components; the applicable terms are:\n\n"
        "  chibios_*_run01.elf  - GPLv3. Links the GPLv3 ChibiOS RT kernel, the\n"
        "    Chibilogic GPL application, and the MIT common layer. The complete\n"
        "    Corresponding Source (GPLv3 section 6) is the source tree at\n"
        "    " + src + " (the same release this archive is paired with).\n\n"
        "  freertos_*_run01.elf - combination of component terms: Chibilogic\n"
        "    application + common (MIT); FreeRTOS kernel (MIT); STM32H7 HAL\n"
        "    (BSD-3-Clause); CMSIS Device (Apache-2.0); ST 'STM32 Projects'\n"
        "    files - stm32h7xx_it.c/.h, stm32h7xx_hal_conf.h - under\n"
        "    STMicroelectronics SLA0044, plus the STM32CubeIDE linker script\n"
        "    (STM32H750XBHX_FLASH.ld; applicable license TBD, conservatively\n"
        "    treated as SLA0044 for release compliance). The SLA0044 portions\n"
        "    may be used and executed ONLY on STMicroelectronics devices; this\n"
        "    image is NOT offered as a single MIT/Apache work.\n\n"
        "  zephyr_*_run01.elf   - Apache-2.0 (Chibilogic application) + the\n"
        "    Zephyr kernel and its modules under their upstream terms + MIT\n"
        "    common.\n\n"
        "Full license texts accompany this archive under LICENSES/ and LICENSE\n"
        "(GPL-3.0, MIT, Apache-2.0, BSD-3-Clause, SLA0044). The per-file SPDX\n"
        "headers in the source tree are authoritative.\n\n"
        "NOTE: the exact notice wording is subject to legal review before any\n"
        "public release.\n"
    )


def _add_bytes_tar(tar: tarfile.TarFile, arc: str, data: bytes) -> None:
    info = tarfile.TarInfo(arc)
    info.size = len(data)
    info.mtime = FIXED_MTIME
    info.mode = FIXED_MODE
    tar.addfile(info, io.BytesIO(data))


def _add_file_tar(tar: tarfile.TarFile, p: Path, arc: str) -> None:
    info = tar.gettarinfo(str(p), arcname=arc)
    info.mtime = FIXED_MTIME
    info.mode = FIXED_MODE
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    with open(p, "rb") as fh:
        tar.addfile(info, fh)


def write_targz(path: Path, top: str, readme: str, notice: str,
                manifest: str, files: list[Path]) -> None:
    with open(path, "wb") as raw_fh:
        with gzip.GzipFile(fileobj=raw_fh, mode="wb", mtime=FIXED_MTIME,
                           compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                _add_bytes_tar(tar, f"{top}/README.txt",
                               readme.encode("utf-8"))
                _add_bytes_tar(tar, f"{top}/NOTICE.txt",
                               notice.encode("utf-8"))
                _add_bytes_tar(tar, f"{top}/MANIFEST.sha256",
                               manifest.encode("utf-8"))
                for p in files:
                    _add_file_tar(tar, p, f"{top}/"
                                  + p.relative_to(REPO_ROOT).as_posix())


def _add_zip(zf: zipfile.ZipFile, arc: str, data: bytes) -> None:
    zi = zipfile.ZipInfo(arc, date_time=ZIP_EPOCH)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = FIXED_MODE << 16
    zf.writestr(zi, data)


def write_zip(path: Path, top: str, readme: str, notice: str,
              manifest: str, files: list[Path]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        _add_zip(zf, f"{top}/README.txt", readme.encode("utf-8"))
        _add_zip(zf, f"{top}/NOTICE.txt", notice.encode("utf-8"))
        _add_zip(zf, f"{top}/MANIFEST.sha256", manifest.encode("utf-8"))
        for p in files:
            _add_zip(zf, f"{top}/" + p.relative_to(REPO_ROOT).as_posix(),
                     p.read_bytes())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Package the publishable raw-logs subset (item #1).")
    ap.add_argument("--out-dir", default=str(DIST))
    ap.add_argument("--source-ref", default="",
                    help="Public repo URL + tag/commit for the source tree; "
                         "embedded in the archive README for pairing.")
    ap.add_argument("--publish-dir", default="",
                    help="Copy ONLY the final .zip + a zip-only .sha256 "
                         "sidecar into this tracked directory (e.g. "
                         "published-logs/phase1).")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)

    files = collect_files()
    # Binary-distribution notices: ship the license texts + a NOTICE so the
    # published ELFs carry their components' terms (GPL source offer, SLA0044
    # ST-device restriction, MIT/Apache/BSD notices).
    licdir = REPO_ROOT / "LICENSES"
    lic = [REPO_ROOT / "LICENSE"] + (
        sorted(p for p in licdir.iterdir() if p.is_file())
        if licdir.is_dir() else [])
    files = sorted(files + [p for p in lic if p.is_file()],
                   key=lambda p: p.relative_to(REPO_ROOT).as_posix())
    manifest = build_manifest(files)
    readme = build_readme(args.source_ref)
    notice = build_notice(args.source_ref)
    digest = hashlib.sha256(
        (manifest + readme + notice).encode("utf-8")).hexdigest()[:12]
    base = f"phase1-raw-logs-{digest}"
    out_dir.mkdir(parents=True, exist_ok=True)
    total = sum(p.stat().st_size for p in files)

    targz = out_dir / f"{base}.tar.gz"
    zippath = out_dir / f"{base}.zip"
    write_targz(targz, base, readme, notice, manifest, files)
    write_zip(zippath, base, readme, notice, manifest, files)

    sums = [f"{sha256_file(a)}  {a.name}" for a in (targz, zippath)]
    (out_dir / f"{base}.SHA256SUMS").write_text(
        "\n".join(sums) + "\n", encoding="utf-8")

    mb = 1048576
    print(f"Raw-logs archive: {base}")
    print(f"  files    : {len(files)}")
    print(f"  raw size : {total / mb:.1f} MB")
    print(f"  tar.gz   : {targz.name}  ({targz.stat().st_size / mb:.1f} MB)")
    print(f"  zip      : {zippath.name}  ({zippath.stat().st_size / mb:.1f} MB)")
    print(f"  sums     : {base}.SHA256SUMS")
    if args.source_ref:
        print(f"  source   : {args.source_ref}")
    if args.publish_dir:
        pub = Path(args.publish_dir)
        pub.mkdir(parents=True, exist_ok=True)
        # Prune any stale published archive so the directory holds exactly
        # one phase1-raw-logs-*.zip + its sidecar (avoids committing stale
        # release assets).
        for old in (list(pub.glob("phase1-raw-logs-*.zip"))
                    + list(pub.glob("phase1-raw-logs-*.zip.sha256"))):
            old.unlink()
        dst = pub / zippath.name
        shutil.copyfile(zippath, dst)
        (pub / f"{zippath.name}.sha256").write_text(
            f"{sha256_file(dst)}  {zippath.name}\n", encoding="utf-8")
        print(f"  published: {dst} (+ .sha256)")
    print(f"  out dir  : {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
