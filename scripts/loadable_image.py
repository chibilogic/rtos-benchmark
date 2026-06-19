#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Loadable-image reproducibility helper (ADR-025).

Defines and verifies ``loadable_image_sha256``: the SHA-256 of the flat
loadable firmware image produced by ``arm-none-eabi-objcopy -O binary <elf>``
-- all loadable (SHF_ALLOC / PROGBITS) sections laid out by load address,
inter-section gaps zero-filled, from the lowest LMA. Symbols, relocations and
DWARF ``.debug_*`` sections are excluded. This is the exact byte image
programmed to flash, i.e. the executed firmware.

Why this exists: source comment / notice / license-header edits shift the DWARF
line tables, so the full ELF (and MAP) SHA-256 changes even when the executed
firmware is byte-identical. The campaign ELF/MAP SHA-256 stored in the locks
remain the immutable identity of the ORIGINALLY MEASURED artifacts;
``loadable_image_sha256`` is the criterion a reviewer uses to confirm that a
rebuild from the tagged tree produces the SAME firmware image.

The objcopy output for ``-O binary`` is deterministic for a given ELF and a
given binutils version; the official ADR-021 toolchain (binutils 2.43.1) is the
reference. Comments do not reach the loadable image, so a comment-only source
edit leaves ``loadable_image_sha256`` unchanged.

Modes:
  --from-elf <elf>                 print loadable_image_sha256 of <elf>
  --augment-locks                  add loadable_image_sha256 to every per-RTOS
                                   entry of each campaign lock, computed from
                                   the manifest-bound
                                   results/raw/<rtos>_<profile>_run01.elf;
                                   elf_sha256 / map_sha256 / results untouched
  --verify <rtos> <profile> <elf>  compare <elf>'s loadable hash against the
                                   lock's loadable_image_sha256 (exit 0 == OK)
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MANIFEST_DIR = os.path.join(REPO_ROOT, "results", "manifest")
DEFAULT_RAW_DIR = os.path.join(REPO_ROOT, "results", "raw")
LOCK_SUFFIX = "_campaign.lock.json"


def find_objcopy(explicit=None):
    """Resolve arm-none-eabi-objcopy from --objcopy, the env, or PATH."""
    cand = explicit or os.environ.get("OBJCOPY") or "arm-none-eabi-objcopy"
    resolved = shutil.which(cand) or (cand if os.path.isfile(cand) else None)
    if resolved is None:
        raise FileNotFoundError(
            "arm-none-eabi-objcopy not found (PATH / --objcopy / $OBJCOPY)")
    return resolved


def sha256_bytes(data):
    """SHA-256 hex digest of a byte string."""
    return hashlib.sha256(data).hexdigest()


def loadable_image_sha256(elf_path, objcopy=None):
    """Return the SHA-256 of `objcopy -O binary <elf>` (the flash image)."""
    tool = find_objcopy(objcopy)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "image.bin")
        subprocess.run([tool, "-O", "binary", elf_path, out],
                       check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE)
        with open(out, "rb") as fp:
            return sha256_bytes(fp.read())


def _profile_from_lock(name):
    return name[:-len(LOCK_SUFFIX)] if name.endswith(LOCK_SUFFIX) else None


def augment_lock(lock, profile, raw_dir, hash_fn):
    """Add loadable_image_sha256 to every RTOS entry of one lock dict.

    `hash_fn(elf_path)` returns the loadable hash; injected so the function is
    unit-testable without a toolchain. elf_sha256 / map_sha256 / other fields
    are left untouched. Returns the number of entries updated.
    """
    updated = 0
    for rtos, entry in sorted(lock.get("rtoses", {}).items()):
        elf = os.path.join(raw_dir, "%s_%s_run01.elf" % (rtos, profile))
        entry["loadable_image_sha256"] = hash_fn(elf)
        updated += 1
    return updated


def cmd_augment_locks(args):
    objcopy = find_objcopy(args.objcopy)
    hash_fn = lambda elf: loadable_image_sha256(elf, objcopy)
    locks = sorted(f for f in os.listdir(args.manifest_dir)
                   if f.endswith(LOCK_SUFFIX))
    if not locks:
        print("no *%s found in %s" % (LOCK_SUFFIX, args.manifest_dir),
              file=sys.stderr)
        return 1
    for name in locks:
        profile = _profile_from_lock(name)
        path = os.path.join(args.manifest_dir, name)
        with open(path, encoding="utf-8") as fp:
            lock = json.load(fp)
        n = augment_lock(lock, profile, args.raw_dir, hash_fn)
        with open(path, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(lock, fp, indent=2, sort_keys=True)
            fp.write("\n")
        print("augmented %-28s (%d RTOS entries)" % (name, n))
    return 0


def cmd_from_elf(args):
    print(loadable_image_sha256(args.elf, args.objcopy))
    return 0


def cmd_verify(args):
    lock_path = os.path.join(args.manifest_dir,
                             "%s%s" % (args.profile, LOCK_SUFFIX))
    with open(lock_path, encoding="utf-8") as fp:
        lock = json.load(fp)
    entry = lock.get("rtoses", {}).get(args.rtos)
    if entry is None:
        print("no entry for rtos=%s in %s" % (args.rtos, lock_path),
              file=sys.stderr)
        return 2
    expected = entry.get("loadable_image_sha256")
    if not expected:
        print("lock has no loadable_image_sha256 for %s/%s; run "
              "--augment-locks first" % (args.rtos, args.profile),
              file=sys.stderr)
        return 2
    got = loadable_image_sha256(args.elf, args.objcopy)
    ok = (got == expected)
    print("%s %s/%s\n  expected %s\n  got      %s"
          % ("OK" if ok else "MISMATCH", args.rtos, args.profile,
             expected, got))
    return 0 if ok else 1


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--objcopy", help="path to arm-none-eabi-objcopy")
    p.add_argument("--manifest-dir", default=DEFAULT_MANIFEST_DIR)
    p.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--from-elf", metavar="ELF")
    g.add_argument("--augment-locks", action="store_true")
    g.add_argument("--verify", nargs=3, metavar=("RTOS", "PROFILE", "ELF"))
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.from_elf:
        args.elf = args.from_elf
        return cmd_from_elf(args)
    if args.augment_locks:
        return cmd_augment_locks(args)
    args.rtos, args.profile, args.elf = args.verify
    return cmd_verify(args)


if __name__ == "__main__":
    sys.exit(main())
