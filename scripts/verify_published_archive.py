#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Reproduce and verify a published raw-log archive end-to-end, with no board,
# no firmware rebuild, and no NumPy. This is the external-reviewer counterpart
# of README.md -> "Reproducibility & verification": it lets anyone confirm that
# the published medians are exactly what the shipped raw CSVs yield and that the
# shipped firmware images are the ones that were measured.
#
# Checks, in order (stops at the first failure):
#   1. ARCHIVE   - the .zip SHA-256 matches its .sha256 sidecar.
#   2. MANIFEST  - every payload file matches the in-archive MANIFEST.sha256
#                  (sha256 + byte size); none missing.
#   3. FIRMWARE  - each shipped run01 ELF matches the elf_sha256 pinned in its
#                  results/manifest/<profile>_campaign.lock.json.
#   4. MEDIANS   - re-derive the median aggregate from the raw CSVs with
#                  report_results.py and confirm it equals the
#                  results/summary/<profile>_aggregate.csv shipped in the archive.
#
# Portable: Python standard library only (no sha256sum/awk/unzip). Step 4 shells
# out to the sibling report_results.py with the same interpreter.
#
# Usage:
#   python scripts/verify_published_archive.py phase1-raw-logs-<digest>.zip
#   python scripts/verify_published_archive.py <already-extracted-dir>
#
# Exit code 0 == all checks passed; non-zero == first failing check.
#
# Author: Edoardo Lombardi - Chibilogic s.r.l.

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PUB_PROFILES = ("fair_perf", "realistic_tickless")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_root(base: Path):
    """Locate the payload root (the directory that holds MANIFEST.sha256)."""
    if (base / "MANIFEST.sha256").is_file():
        return base
    hits = sorted(base.rglob("MANIFEST.sha256"), key=lambda p: len(p.parts))
    return hits[0].parent if hits else None


def check_archive(zip_path: Path, sidecar: Path) -> bool:
    if not sidecar.is_file():
        print(f"  [1 archive ] SKIP no sidecar {sidecar.name} alongside the zip")
        return True
    calc = sha256_file(zip_path)
    want = sidecar.read_text().split()[0].strip().lower()
    if calc != want:
        print(f"  [1 archive ] FAIL zip sha256 {calc} != sidecar {want}")
        return False
    print(f"  [1 archive ] OK   zip sha256 == sidecar ({calc[:12]}...)")
    return True


def check_manifest(root: Path) -> bool:
    mani = root / "MANIFEST.sha256"
    if not mani.is_file():
        print("  [2 manifest] FAIL MANIFEST.sha256 not found")
        return False
    ok = miss = bad = 0
    for line in mani.read_text().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, rel = parts[0], parts[1]
        size = int(parts[2]) if len(parts) > 2 else None
        f = root / rel
        if not f.is_file():
            print(f"      MISSING  {rel}")
            miss += 1
            continue
        data = f.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest or (
                size is not None and len(data) != size):
            print(f"      MISMATCH {rel}")
            bad += 1
            continue
        ok += 1
    if miss or bad:
        print(f"  [2 manifest] FAIL {miss} missing, {bad} mismatched, {ok} ok")
        return False
    print(f"  [2 manifest] OK   {ok} payload files verified")
    return True


def check_firmware(root: Path) -> bool:
    locks = sorted((root / "results" / "manifest").glob("*_campaign.lock.json"))
    if not locks:
        print("  [3 firmware] FAIL no campaign lock files in archive")
        return False
    checked = bad = 0
    for lock in locks:
        data = json.loads(lock.read_text())
        profile = data.get("profile", lock.stem.replace("_campaign.lock", ""))
        for rtos, block in sorted(data.get("rtoses", {}).items()):
            want = block.get("elf_sha256")
            elf = root / "results" / "raw" / f"{rtos}_{profile}_run01.elf"
            if not elf.is_file():
                print(f"      MISSING  {elf.name}")
                bad += 1
                continue
            got = sha256_file(elf)
            if got != want:
                print(f"      MISMATCH {elf.name}: {got[:12]} != lock {str(want)[:12]}")
                bad += 1
                continue
            checked += 1
    if bad:
        print(f"  [3 firmware] FAIL {bad} ELF(s) do not match the campaign lock")
        return False
    print(f"  [3 firmware] OK   {checked} run01 ELF(s) match elf_sha256 in the lock")
    return True


def check_medians(root: Path, report_script: Path, profiles) -> bool:
    if not report_script.is_file():
        print(f"  [4 medians ] FAIL report script not found: {report_script}")
        return False
    raw = root / "results" / "raw"
    all_ok = True
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        for prof in profiles:
            shipped = root / "results" / "summary" / f"{prof}_aggregate.csv"
            if not shipped.is_file():
                print(f"      {prof}: no shipped aggregate in archive")
                all_ok = False
                continue
            cmd = [sys.executable, str(report_script),
                   "--input-dir", str(raw),
                   "--output-dir", str(out),
                   "--profile", prof]
            r = subprocess.run(cmd, capture_output=True, text=True)
            recomputed = out / f"{prof}_aggregate.csv"
            if r.returncode != 0 or not recomputed.is_file():
                print(f"      {prof}: recompute failed (rc={r.returncode})")
                if r.stderr.strip():
                    print("        " + r.stderr.strip().splitlines()[-1])
                all_ok = False
                continue
            a, b = shipped.read_bytes(), recomputed.read_bytes()
            if a == b:
                print(f"      {prof}: OK byte-identical median table")
            elif a.splitlines() == b.splitlines():
                print(f"      {prof}: OK content-identical (newline-only diff)")
            else:
                print(f"      {prof}: FAIL recomputed medians differ from published")
                all_ok = False
    print("  [4 medians ] " + ("OK   published medians reproduced from raw CSVs"
                                if all_ok else "FAIL see above"))
    return all_ok


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Verify a published raw-log archive (no board, no rebuild).")
    p.add_argument("archive",
                   help="path to phase1-raw-logs-<digest>.zip or an "
                        "already-extracted directory")
    p.add_argument("--sha256", default=None,
                   help="checksum sidecar (default: <archive>.sha256)")
    p.add_argument("--report-script",
                   default=str(SCRIPT_DIR / "report_results.py"),
                   help="path to report_results.py (default: sibling)")
    p.add_argument("--profiles", nargs="+", default=list(PUB_PROFILES),
                   help="profiles to recompute (default: both publishable)")
    p.add_argument("--keep", action="store_true",
                   help="keep the temporary extraction directory")
    args = p.parse_args(argv)

    archive = Path(args.archive).resolve()
    if not archive.exists():
        print(f"error: not found: {archive}")
        return 2

    print(f"Verifying {archive.name}")
    results = []
    tmp = None
    try:
        if archive.is_dir():
            root = find_root(archive)
            print("  [1 archive ] SKIP input is a directory (no zip to checksum)")
            results.append(True)
        else:
            sidecar = (Path(args.sha256) if args.sha256
                       else Path(str(archive) + ".sha256"))
            results.append(check_archive(archive, sidecar))
            tmp = tempfile.mkdtemp(prefix="verify_raw_logs_")
            try:
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(tmp)
            except (zipfile.BadZipFile, zlib.error, EOFError, OSError) as exc:
                print(f"  [extract  ] FAIL cannot read the archive: {exc}")
                print("RESULT: VERIFICATION FAILED")
                return 1
            root = find_root(Path(tmp))
        if root is None:
            print("error: MANIFEST.sha256 not found in archive")
            return 2

        results.append(check_manifest(root))
        results.append(check_firmware(root))
        results.append(check_medians(root, Path(args.report_script),
                                     args.profiles))
    finally:
        if tmp and not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)

    passed = all(results)
    print("RESULT: " + ("ALL CHECKS PASSED" if passed
                        else "VERIFICATION FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
