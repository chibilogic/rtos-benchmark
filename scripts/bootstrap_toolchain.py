#!/usr/bin/env python3
"""ADR-021 - repo-local toolchain bootstrap (hardened).

Reads tools/TOOLCHAIN.lock, downloads each pinned component from
its official HTTPS upstream, verifies SHA-256 BEFORE extraction,
unpacks into a temporary sibling, validates layout, then
replaces the repo-local destination. Idempotent;
never touches the system PATH or installs anything system-wide.
stdlib only.

Security model (Codex 2026-05-18-bootstrap-toolchain-codereview
+ ADR-021 patch set 3a-extractor 2026-05-20-adr021-patch-set-3a-
symlink-discovery-001):
  - destinations are lock-relative and constrained to
    <repo-root>/tools/<platform>/...; absolute or escaping
    destinations are rejected;
  - archive members are normalised and containment-checked with
    Path.relative_to (no startswith); zip symlink entries are
    rejected; tar non-regular members are rejected EXCEPT safe
    internal symlinks and hardlinks, where "safe" means the link
    target is non-empty, not absolute, not a drive letter, not
    UNC, contains no backslashes, and resolves within the
    extraction destination. Symlinks are recreated as symlinks on
    POSIX (clear failure on Windows without Developer Mode);
    hardlinks are materialised as content copies of the linked
    member (portable across OSes);
  - special files (FIFO, char/block device, socket) are still
    rejected non-negotiably;
  - download scheme is https only (file:// behind
    --allow-file-url for offline tests);
  - extraction uses a temp dir -> validate -> replace (not a
    crash-proof filesystem transaction);
  - idempotent skip only when the SHA marker AND the expected
    layout are both present.

Usage:
    python scripts/bootstrap_toolchain.py [--platform NAME]
        [--lock PATH] [--force] [--repo-root DIR]
        [--allow-file-url]
Exit codes: 0 ok; 1 on any failure.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NoReturn

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO_ROOT / "tools" / "TOOLCHAIN.lock"
SUPPORTED = ("windows-x86_64", "linux-x86_64")


def fail(msg: str) -> NoReturn:
    raise SystemExit(msg)


def safe_mode(raw: int) -> int:
    """Keep owner/group/other rwx bits only; strip setuid,
    setgid, sticky and any other special bits."""
    return raw & 0o777


def detect_platform() -> str:
    import platform as _p
    s = _p.system().lower()
    m = _p.machine().lower()
    x64 = m in ("x86_64", "amd64")
    if s == "windows" and x64:
        return "windows-x86_64"
    if s == "linux" and x64:
        return "linux-x86_64"
    fail(f"unsupported platform: {s}/{m}; ADR-021 supports "
         f"{', '.join(SUPPORTED)} only")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_within(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def norm_member(raw: str) -> str | None:
    """Normalise an archive member name to a safe relative posix
    path, or None if it is absolute / drive / UNC / contains
    a parent-dir traversal."""
    n = raw.replace("\\", "/")
    if not n or n.startswith("/") or n.startswith("//"):
        return None
    if PureWindowsPath(raw).drive or PurePosixPath(n).is_absolute():
        return None
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts) if parts else None


def validate_url(url: str, allow_file: bool) -> None:
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme == "https":
        return
    if scheme == "file" and allow_file:
        return
    fail(f"refused URL scheme '{scheme or '(none)'}': only https "
         f"is allowed (file:// needs --allow-file-url)")


def resolve_destination(plat: str, destination: str,
                        repo_root: Path) -> Path:
    if PureWindowsPath(destination).drive or \
            PurePosixPath(destination.replace('\\', '/')).is_absolute():
        fail(f"destination must be repo-relative, got "
             f"'{destination}'")
    base = (repo_root / "tools" / plat).resolve()
    dest = (repo_root / destination).resolve()
    if dest == base or not is_within(dest, base):
        fail(f"destination '{destination}' escapes the repo-local "
             f"tools/{plat}/ subtree")
    return dest


def _extract_zip(arc: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arc) as zf:
        for zi in zf.infolist():
            mode = (zi.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                fail(f"zip symlink member rejected: {zi.filename}")
            name = norm_member(zi.filename)
            if name is None:
                fail(f"unsafe zip member: {zi.filename}")
            target = into / name
            if not is_within(target, into):
                fail(f"unsafe zip member: {zi.filename}")
            if zi.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(zi) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            perm = (zi.external_attr >> 16) & 0o777
            if perm:
                target.chmod(safe_mode(perm))


def _validate_symlink_target(member, target: Path, into: Path) -> None:
    """Reject unsafe symlink targets (ADR-021 patch set 3a-extractor).

    Symlink linkname is the literal string that will be written into
    the symlink and interpreted by the kernel at lookup time. Allowed
    only if non-empty, relative, contains no backslashes, no drive
    letter, no UNC prefix, and `(target.parent / linkname)` resolves
    to a path within `into`.
    """
    lk = member.linkname
    if not lk:
        fail(f"empty symlink target: {member.name}")
    if lk.startswith("/") or lk.startswith("//"):
        fail(f"absolute symlink rejected: {member.name} -> {lk}")
    if len(lk) >= 2 and lk[1] == ":":
        fail(f"drive-letter symlink rejected: {member.name} -> {lk}")
    if "\\" in lk:
        fail(f"backslash-containing symlink rejected: "
             f"{member.name} -> {lk}")
    resolved = (target.parent / lk).resolve(strict=False)
    if not is_within(resolved, into):
        fail(f"symlink escapes destination: {member.name} -> {lk}")


def _validate_hardlink_target(member, target: Path, into: Path,
                              all_names: set) -> None:
    """Reject unsafe hardlink targets (ADR-021 patch set 3a-extractor).

    Hardlink linkname is the archive-relative path of another member.
    Validated via `norm_member` + containment, plus a membership
    check in `all_names` so we never dereference a missing member.
    """
    lk = member.linkname
    if not lk:
        fail(f"empty hardlink target: {member.name}")
    if (lk.startswith("/") or lk.startswith("\\") or
            (len(lk) >= 2 and lk[1] == ":")):
        fail(f"unsafe hardlink target name: {member.name} -> {lk}")
    norm = norm_member(lk)
    if norm is None:
        fail(f"unsafe hardlink target name: {member.name} -> {lk}")
    expected = into / norm
    if not is_within(expected, into):
        fail(f"hardlink target escapes destination: "
             f"{member.name} -> {lk}")
    if lk not in all_names:
        fail(f"hardlink target not in archive: {member.name} -> {lk}")


def _extract_tar(arc: Path, kind: str, into: Path) -> None:
    """Two-pass safe tar extractor (ADR-021 patch set 3a-extractor).

    Pass 1: validate + classify every member by type. Pass 2: create
    directories and regular files (chmod with safe_mode). Pass 3:
    recreate safe symlinks (POSIX or Windows Developer Mode) and
    materialise safe hardlinks as content copies of the linked member.
    Special files (FIFO, char/block device, socket) are rejected.
    """
    into.mkdir(parents=True, exist_ok=True)
    mode = {"tar.xz": "r:xz", "tar.gz": "r:gz",
            "tar.bz2": "r:bz2", "tar": "r:"}[kind]
    with tarfile.open(arc, mode) as tf:
        all_names = {m.name for m in tf.getmembers()}
        dirs: list = []
        regs: list = []
        syms: list = []
        hards: list = []
        # ----- Pass 1: validate + classify -----
        for m in tf.getmembers():
            name = norm_member(m.name)
            if name is None:
                fail(f"unsafe tar member: {m.name}")
            target = into / name
            if not is_within(target, into):
                fail(f"unsafe tar member: {m.name}")
            if m.isdir():
                dirs.append((m, target))
            elif m.isreg():
                regs.append((m, target))
            elif m.issym():
                _validate_symlink_target(m, target, into)
                syms.append((m, target))
            elif m.islnk():
                _validate_hardlink_target(m, target, into, all_names)
                hards.append((m, target))
            else:
                fail(f"unsafe tar member (special: type={m.type!r}): "
                     f"{m.name}")
        # ----- Pass 2: directories + regular files -----
        for _m, target in dirs:
            target.mkdir(parents=True, exist_ok=True)
        for m, target in regs:
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(m)
            if src is None:
                fail(f"unreadable tar member: {m.name}")
            with src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            target.chmod(safe_mode(m.mode))
        # ----- Pass 3a: symlinks (POSIX; clear failure on Windows) -----
        for m, target in syms:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                target.unlink()
            try:
                target.symlink_to(m.linkname)
            except OSError as exc:
                fail(f"cannot create symlink {m.name} -> {m.linkname}: "
                     f"{exc}. Linux tarballs with symlinks must be "
                     f"extracted on Linux (or enable Windows Developer "
                     f"Mode if you really need this on Windows).")
        # ----- Pass 3b: hardlinks materialised as content copies -----
        for m, target in hards:
            src_member = tf.getmember(m.linkname)
            src = tf.extractfile(src_member)
            if src is None:
                fail(f"unreadable hardlink target {m.linkname} "
                     f"for {m.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            target.chmod(safe_mode(src_member.mode))


def extract(arc: Path, kind: str, into: Path) -> None:
    if kind == "zip":
        _extract_zip(arc, into)
    elif kind in ("tar.xz", "tar.gz", "tar.bz2", "tar"):
        _extract_tar(arc, kind, into)
    else:
        fail(f"unknown archive type: {kind}")


def effective_root(tmp: Path, strip_prefix: str) -> Path:
    if not strip_prefix:
        return tmp
    tops = sorted(p.name for p in tmp.iterdir())
    if tops != [strip_prefix]:
        fail(f"strip_prefix '{strip_prefix}': archive payload is "
             f"not entirely under it (top-level: {tops})")
    top = tmp / strip_prefix
    if not top.is_dir():
        fail(f"strip_prefix '{strip_prefix}' is not a directory")
    return top


def _expect_path(entry) -> str:
    return entry["path"] if isinstance(entry, dict) else entry


def layout_ok(root: Path, expect: list, plat: str) -> bool:
    win = plat.startswith("windows")
    for entry in expect:
        rel = _expect_path(entry)
        need_x = isinstance(entry, dict) and bool(
            entry.get("executable"))
        p = root / rel
        if not p.is_file():
            return False
        if need_x and not win and not os.access(p, os.X_OK):
            return False
    return True


def bootstrap_component(name: str, spec: dict, repo_root: Path,
                        plat: str, force: bool,
                        allow_file: bool) -> None:
    url = spec.get("url", "")
    sha = spec.get("sha256", "").lower()
    kind = spec.get("archive", "")
    expect = spec.get("expect", [])
    if not url or not sha:
        fail(f"[{name}] not pinned: populate 'url' and 'sha256' "
             f"in TOOLCHAIN.lock (ADR-021); refusing to guess")
    dest = resolve_destination(plat, spec["destination"], repo_root)
    marker = dest / ".bootstrap_ok"
    if (not force and marker.is_file()
            and marker.read_text().strip() == sha
            and layout_ok(dest, expect, plat)):
        print(f"[{name}] already bootstrapped (sha + layout), skip")
        return
    validate_url(url, allow_file)
    cache = (repo_root / "tools" / "_cache")
    cache.mkdir(parents=True, exist_ok=True)
    arc = cache / f"{name}.{kind}"
    print(f"[{name}] downloading {url}")
    try:
        urllib.request.urlretrieve(url, arc)  # noqa: S310 (scheme gated)
    except Exception as exc:
        fail(f"[{name}] download failed: {exc}")
    got = sha256_file(arc)
    if got != sha:
        arc.unlink(missing_ok=True)
        fail(f"[{name}] SHA-256 mismatch: expected {sha}, got {got}")
    tmp = dest.parent / (dest.name + ".tmp-bootstrap")
    if tmp.exists():
        shutil.rmtree(tmp)
    try:
        extract(arc, kind, tmp)
        root = effective_root(tmp, spec.get("strip_prefix", ""))
        if not layout_ok(root, expect, plat):
            missing = [_expect_path(e) for e in expect
                       if not (root / _expect_path(e)).is_file()]
            fail(f"[{name}] expected layout invalid after extract "
                 f"(missing or non-executable; missing files: "
                 f"{missing})")
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root), str(dest))
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    marker.write_text(sha + "\n")
    print(f"[{name}] OK -> {dest}")


def print_versions(plat: str, repo_root: Path) -> None:
    base = repo_root / "tools" / plat
    suf = ".exe" if plat.startswith("windows") else ""
    for label, rel in (
            ("arm-none-eabi-gcc",
             f"arm-gnu-toolchain/bin/arm-none-eabi-gcc{suf}"),
            ("make", f"make/bin/make{suf}"),
            ("openocd", f"openocd/bin/openocd{suf}")):
        cand = base / rel
        if not cand.is_file():
            print(f"  {label}: not provisioned")
            continue
        try:
            r = subprocess.run([str(cand), "--version"],
                               capture_output=True, text=True)
            lines = (r.stdout or r.stderr or "").splitlines()
            print(f"  {label}: "
                  f"{lines[0] if lines else 'version unavailable'}")
        except Exception as exc:
            print(f"  {label}: present, --version failed: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="ADR-021 toolchain bootstrap")
    ap.add_argument("--platform", default=None)
    ap.add_argument("--lock", default=str(DEFAULT_LOCK))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--repo-root", default=str(REPO_ROOT),
                    help="test/CI only: override the repo root "
                         "used to resolve repo-local destinations")
    ap.add_argument("--allow-file-url", action="store_true",
                    help="test/CI only: permit file:// downloads")
    a = ap.parse_args()
    repo_root = Path(a.repo_root).resolve()
    plat = a.platform or detect_platform()
    if plat not in SUPPORTED:
        fail(f"platform '{plat}' not supported "
             f"({', '.join(SUPPORTED)})")
    lock = json.loads(Path(a.lock).read_text(encoding="utf-8"))
    plats = lock.get("platforms", {})
    if plat not in plats:
        fail(f"platform '{plat}' not in lock")
    for cname, spec in plats[plat].items():
        bootstrap_component(cname, spec, repo_root, plat,
                            a.force, a.allow_file_url)
    print(f"toolchain ready for {plat}; versions:")
    print_versions(plat, repo_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
