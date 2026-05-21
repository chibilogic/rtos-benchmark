#!/usr/bin/env python3
"""ADR-021 - repo-local toolchain bootstrap (hardened).

Reads tools/TOOLCHAIN.lock, downloads each pinned component from
its official HTTPS upstream, verifies SHA-256 BEFORE extraction,
unpacks into a temporary sibling, validates layout, then
replaces the repo-local destination. Idempotent;
never touches the system PATH or installs anything system-wide.

Core extraction/verification logic is stdlib only. Optional `truststore`
(when installed) is auto-injected to make HTTPS validation use the native
OS trust store (Windows CryptoAPI/Schannel, macOS SecureTransport, Linux
OpenSSL); on Windows this is the standard answer because CPython stdlib
`ssl` does NOT consume the Schannel store. The environment variables
`SSL_CERT_FILE` / `SSL_CERT_DIR` are honored on all OSes (for corporate
CA bundles) and take precedence over truststore injection. TLS certificate
verification is ALWAYS enforced; this script never disables it.

Security model (Codex 2026-05-18-bootstrap-toolchain-codereview
+ ADR-021 patch set 3a-extractor 2026-05-20-adr021-patch-set-3a-
symlink-discovery-001):
  - destinations are lock-relative and constrained to
    <repo-root>/tools/<platform>/...; absolute or escaping
    destinations are rejected;
  - archive members are normalised and containment-checked with
    Path.relative_to (no startswith); duplicate normalized member
    paths are rejected upfront to prevent type-collision ambiguity
    in the deferred-link phases (Codex CODE_REVIEW 2026-05-20-
    adr021-patch-set-3a-extractor-applied-code-review-001
    BLOCKER 1); zip symlink entries are rejected; tar non-regular
    members are rejected EXCEPT safe internal symlinks and
    hardlinks, where "safe" means the link target is non-empty,
    not absolute, not a drive letter, not UNC, contains no
    backslashes, and resolves within the extraction destination.
    Symlinks are recreated as symlinks on POSIX (clear failure on
    Windows without Developer Mode); hardlinks are materialised
    as content copies of the linked member, **only when that
    target is a validated regular file member in the same
    archive** (no sym, no dir, no missing target); the copy reads
    from the already-extracted file path on disk (no implicit
    link-following via tarfile);
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
import ssl
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


_TLS_STATUS: str = "uninitialised"


def configure_tls_trust_store() -> str:
    """Set up HTTPS trust store for urllib downloads.

    Precedence (Codex 2026-05-21-adr021-patch-set-3b-ssl-plan-review-001):
      1. SSL_CERT_FILE or SSL_CERT_DIR already in env: honored, no
         override (corporate-CA path; applies to all OSes).
      2. `truststore` library installed: inject_into_ssl() so Python ssl
         consults the native OS trust store (standard answer on Windows
         because stdlib ssl does NOT consume Schannel). If injection
         itself raises (broken/incompatible truststore install), the
         script fails with explicit guidance instead of silently
         falling back, to avoid masking a real host setup problem
         (Codex CODE_REVIEW 2026-05-21-adr021-patch-set-3b-ssl-code-
         review-001 IMPORTANT 3).
      3. Otherwise: stdlib defaults; if a download later fails with
         CERTIFICATE_VERIFY_FAILED, _emit_cert_error_guidance() prints
         an actionable message.
    Returns a short status string (also stored in _TLS_STATUS for
    diagnostics).
    """
    global _TLS_STATUS
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        _TLS_STATUS = ("SSL_CERT_FILE/SSL_CERT_DIR provided by "
                       "environment; trust store override skipped")
        return _TLS_STATUS
    try:
        import truststore  # type: ignore
    except ImportError:
        _TLS_STATUS = ("truststore not installed; using stdlib default "
                       "trust paths (Windows users: see SETUP sec. 2)")
        return _TLS_STATUS
    try:
        truststore.inject_into_ssl()
    except Exception as exc:
        fail(
            f"[tls] truststore native trust-store injection failed: "
            f"{exc}\n"
            f"\n"
            f"You may update/reinstall truststore:\n"
            f"  python -m pip install --upgrade truststore\n"
            f"\n"
            f"Or provide a CA bundle via SSL_CERT_FILE (PEM file) /\n"
            f"SSL_CERT_DIR (hashed OpenSSL CA directory) before running\n"
            f"the bootstrap; these take precedence over truststore."
        )
    _TLS_STATUS = "using truststore native OS trust store"
    return _TLS_STATUS


def _is_cert_verify_error(exc: BaseException) -> bool:
    """True if exc is or wraps an SSL certificate verification failure."""
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    if "CERTIFICATE_VERIFY_FAILED" in str(exc):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException):
        if isinstance(reason, ssl.SSLCertVerificationError):
            return True
        if "CERTIFICATE_VERIFY_FAILED" in str(reason):
            return True
    return False


def _emit_cert_error_guidance(name: str, exc: BaseException) -> NoReturn:
    """Print Codex-mandated actionable message and exit (Codex
    2026-05-21-adr021-patch-set-3b-ssl-plan-review-001)."""
    fail(
        f"[{name}] TLS certificate verification failed: {exc}\n"
        f"\n"
        f"On Windows install the standard Python system-trust adapter:\n"
        f"  python -m pip install truststore\n"
        f"Then re-run:\n"
        f"  python scripts/bootstrap_toolchain.py\n"
        f"\n"
        f"Alternatively, if your organisation provides a custom CA\n"
        f"bundle, set SSL_CERT_FILE (PEM file) or SSL_CERT_DIR (hashed\n"
        f"OpenSSL CA directory) before running the bootstrap."
    )


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
                              regular_by_norm: dict) -> None:
    """Reject unsafe hardlink targets. Codex CODE_REVIEW
    2026-05-20-adr021-patch-set-3a-extractor-applied-code-review-001
    BLOCKER 2: hardlinks may only target validated regular file
    members in the same archive (no sym, no dir, no missing); the
    actual content copy in Pass 3b reads from the already-extracted
    file under `into` (NOT via tf.extractfile, which has implicit
    link-following behaviour).
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
    if norm not in regular_by_norm:
        fail(f"hardlink target is not a validated regular file "
             f"member in this archive: {member.name} -> {lk}")


def _extract_tar(arc: Path, kind: str, into: Path) -> None:
    """Three-phase safe tar extractor (ADR-021 patch set 3a-extractor,
    refined by Codex CODE_REVIEW 2026-05-20-adr021-patch-set-3a-
    extractor-applied-code-review-001 BLOCKER 1+2).

    Pass 1a rejects duplicate normalized member paths (prevents
    type-collision ambiguity in the deferred-link phases).
    Pass 1b classifies remaining members into dirs/regs/syms/hards,
    rejecting special types non-negotiably and building a
    regular_by_norm map.
    Pass 1c validates hardlinks against the regular_by_norm map
    (hardlinks may only target validated regular file members).
    Pass 2 creates directories and writes regular files (chmod).
    Pass 3a recreates symlinks (POSIX or Windows Developer Mode);
    on Windows OSError the failure message recommends Linux.
    Pass 3b materialises hardlinks as content copies read from the
    already-extracted regular file under `into` (NOT via
    tf.extractfile(), which has implicit link-following behaviour).
    """
    into.mkdir(parents=True, exist_ok=True)
    mode = {"tar.xz": "r:xz", "tar.gz": "r:gz",
            "tar.bz2": "r:bz2", "tar": "r:"}[kind]
    with tarfile.open(arc, mode) as tf:
        # ----- Pass 1a: reject duplicate normalized member paths -----
        members_by_norm: dict = {}
        for m in tf.getmembers():
            name = norm_member(m.name)
            if name is None:
                fail(f"unsafe tar member: {m.name}")
            if name in members_by_norm:
                fail(f"duplicate normalized tar member: {m.name!r} "
                     f"collides with {members_by_norm[name].name!r} "
                     f"(both normalize to {name!r})")
            members_by_norm[name] = m
        # ----- Pass 1b: classify (defer hardlink validation) -----
        dirs: list = []
        regs: list = []
        regular_by_norm: dict = {}
        syms: list = []
        hards: list = []
        for name, m in members_by_norm.items():
            target = into / name
            if not is_within(target, into):
                fail(f"unsafe tar member: {m.name}")
            if m.isdir():
                dirs.append((m, target))
            elif m.isreg():
                regs.append((m, target))
                regular_by_norm[name] = m
            elif m.issym():
                _validate_symlink_target(m, target, into)
                syms.append((m, target))
            elif m.islnk():
                hards.append((m, target))
            else:
                fail(f"unsafe tar member (special: type={m.type!r}): "
                     f"{m.name}")
        # ----- Pass 1c: validate hardlinks now that regular_by_norm complete -----
        for m, target in hards:
            _validate_hardlink_target(m, target, into, regular_by_norm)
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
        # ----- Pass 3b: hardlinks materialised as content copies
        #              read from disk (Codex BLOCKER 2: avoid
        #              tf.extractfile implicit link-following) -----
        for m, target in hards:
            target_norm = norm_member(m.linkname)
            src_path = into / target_norm
            target.parent.mkdir(parents=True, exist_ok=True)
            with src_path.open("rb") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            target.chmod(safe_mode(regular_by_norm[target_norm].mode))


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
    # ADR-021 patch set 3b: unmanaged entries (host prerequisites)
    # are skipped deliberately. They must declare skip_reason so the
    # skip is informative and not a silent gap.
    if not spec.get("managed", True):
        reason = spec.get("skip_reason", "")
        if not reason:
            fail(f"[{name}] managed=false requires a non-empty "
                 f"'skip_reason' in TOOLCHAIN.lock (ADR-021 patch "
                 f"set 3b contract)")
        print(f"[{name}] unmanaged: {reason}")
        expect_on_path = spec.get("expect_on_path", "")
        if expect_on_path:
            found = shutil.which(expect_on_path)
            if found:
                print(f"[{name}] host '{expect_on_path}' found: {found}")
            else:
                print(f"[{name}] WARNING: host '{expect_on_path}' "
                      f"NOT on PATH; the build will fail without it")
        return

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
        if _is_cert_verify_error(exc):
            _emit_cert_error_guidance(name, exc)
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
    print(f"[tls] {configure_tls_trust_store()}")
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
