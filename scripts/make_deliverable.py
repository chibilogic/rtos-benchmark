#!/usr/bin/env python3
"""E1a - clean deliverable archive (ADR-021 split; packaging
hygiene only).

Builds a small, clean source archive of THIS project from the
committed tree (HEAD). It never bundles RTOS submodule trees or
the toolchain; instead it emits an EXTERNAL_SOURCES.lock with the
exact submodule URLs + gitlink SHAs and the clone/checkout +
west + bootstrap steps. stdlib only.

Default is --dry-run (lists what would ship, writes nothing). A
real archive (--write) hard-refuses a dirty tree and is produced
deterministically from HEAD.

Excluded ALWAYS (defense-in-depth denylist, even if tracked):
  notes/ reference/ results/ build/ .claude/ .codex/
  __pycache__/ dist/ tools/ (except tools/TOOLCHAIN.lock)
  AGENTS.md AGENTS.override.md CLAUDE.local.md
  docs/Phase1_Benchmark_Report.pdf
RTOS submodule trees are never copied (external sources).

Usage:
  python scripts/make_deliverable.py            # dry-run
  python scripts/make_deliverable.py --write     # real archive
  python scripts/make_deliverable.py --write --repo-root DIR
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NAME = "rtos-benchmark"

# Clearly private/cache names: denied at ANY path segment
# (including a final filename - no legitimate source is named
# exactly like these).
DENY_SEG = {"notes", "reference", "results", ".claude",
            ".codex", "__pycache__", ".pytest_cache",
            ".venv", "venv", "dist"}
DENY_EXACT = ("AGENTS.md", "AGENTS.override.md",
              "CLAUDE.local.md",
              "docs/Phase1_Benchmark_Report.pdf")
TOOLS_KEEP = ("tools/TOOLCHAIN.lock",)


def _is_build_dir(seg: str) -> bool:
    """Generated build directory names. Applied to DIRECTORY
    segments only, never to a final source filename (so e.g.
    scripts/build_report.py is NOT excluded)."""
    return (seg == "build" or seg.startswith("build_")
            or seg.startswith("cmake-build")
            or seg == "CMakeFiles")


def git(args: list, repo: Path) -> str:
    r = subprocess.run(["git", "-C", str(repo)] + args,
                        capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: "
                         f"{r.stderr.strip()}")
    return r.stdout


def git_bytes(args: list, repo: Path) -> bytes:
    r = subprocess.run(["git", "-C", str(repo)] + args,
                        capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed")
    return r.stdout


def is_denied(path: str) -> bool:
    norm = path.replace("\\", "/")
    if norm in DENY_EXACT:
        return True
    segs = [s for s in norm.split("/") if s not in ("", ".")]
    if not segs:
        return False
    dirs = segs[:-1]
    if any(s in DENY_SEG for s in segs):
        return True
    if any(_is_build_dir(s) for s in dirs):
        return True
    if norm == "tools" or norm.startswith("tools/"):
        return norm not in TOOLS_KEEP
    return False


def tree_clean(repo: Path) -> bool:
    return git(["status", "--porcelain",
                "--untracked-files=all"], repo).strip() == ""


def head_entries(repo: Path):
    """Yield (mode, sha, path) for every HEAD entry."""
    out = git(["ls-tree", "-r", "HEAD"], repo)
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        mode, _typ, sha = meta.split()
        yield mode, sha, path


def submodule_meta(repo: Path) -> dict:
    cfg = git(["config", "-f", ".gitmodules", "--list"], repo)
    by_path: dict = {}
    tmp: dict = {}
    for line in cfg.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        parts = k.split(".")
        if len(parts) < 3:
            continue
        name = ".".join(parts[1:-1])
        field = parts[-1]
        tmp.setdefault(name, {})[field] = v
    for name, d in tmp.items():
        if "path" in d:
            by_path[d["path"]] = {"url": d.get("url", ""),
                                  "branch": d.get("branch", "")}
    return by_path


def external_sources(gitlinks: list, repo: Path) -> dict:
    sm = submodule_meta(repo)
    items = []
    for _mode, sha, path in gitlinks:
        meta = sm.get(path, {})
        url = meta.get("url", "")
        if not url:
            raise SystemExit(
                f"gitlink '{path}' has no .gitmodules URL; "
                f"refusing to emit a broken fetch instruction")
        items.append({
            "path": path,
            "url": url,
            "branch": meta.get("branch", ""),
            "commit": sha,
            "fetch": [
                f"git clone {url} {path}",
                f"git -C {path} checkout {sha}",
            ],
        })
    return {
        "_note": "Submodule trees are NOT bundled. Recreate them "
                 "exactly with these commands, then run the "
                 "Zephyr west flow, then bootstrap the toolchain "
                 "(ADR-021).",
        "submodules": items,
        "zephyr": [
            "cd zephyr",
            "python -m venv .venv",
            ". .venv/bin/activate              # Linux/macOS",
            ".venv\\Scripts\\activate.bat      # Windows",
            "pip install west",
            "west init -l benchmark_zephyr",
            "west update",
        ],
        "toolchain": "python scripts/bootstrap_toolchain.py "
                     "(ADR-021; see docs/SETUP.md)",
    }


def notice_text(ext: dict, shortsha: str) -> str:
    lines = [
        f"{NAME} - clean source deliverable ({shortsha})",
        "",
        "This archive contains ONLY the project's own committed "
        "source. It does NOT contain the RTOS submodule trees, "
        "the toolchain, results, internal notes, reference "
        "material, the synthesis report PDF, or local AI/tooling "
        "files.",
        "",
        "To build (see docs/SETUP.md, README.md Quickstart):",
        "  1. Recreate the external sources (EXTERNAL_SOURCES."
        "lock):",
    ]
    for s in ext["submodules"]:
        lines.append(f"     - {s['path']} @ {s['commit']}")
        for c in s["fetch"]:
            lines.append(f"         {c}")
    lines += ["  2. Zephyr west flow:"]
    lines += [f"     {c}" for c in ext["zephyr"]]
    lines += ["  3. Toolchain: " + ext["toolchain"],
              "  4. Build the six publishable ELFs (README "
              "Quickstart).",
              "",
              "Integrity: MANIFEST.sha256 lists the SHA-256 of "
              "every file in this archive (excluding itself).",
              ""]
    return "\n".join(lines)


def collect(repo: Path):
    files, gitlinks, skipped = [], [], []
    for mode, sha, path in head_entries(repo):
        if mode == "160000":
            gitlinks.append((mode, sha, path))
            continue
        if mode == "120000":
            skipped.append(path)
            continue
        if is_denied(path):
            continue
        files.append((mode, sha, path))
    files.sort(key=lambda e: e[2])
    return files, gitlinks, skipped


def add_bytes_tar(tf: tarfile.TarFile, name: str, data: bytes,
                  mtime: int, mode: int) -> None:
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    ti.mtime = mtime
    ti.mode = mode
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    ti.type = tarfile.REGTYPE
    tf.addfile(ti, io.BytesIO(data))


def add_bytes_zip(zf: zipfile.ZipFile, name: str, data: bytes,
                  mode: int) -> None:
    zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    zi.external_attr = (mode & 0o777) << 16
    zi.create_system = 3  # stable across host OS
    zi.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(zi, data)


def build(repo: Path, out_dir: Path) -> list:
    shortsha = git(["rev-parse", "--short", "HEAD"], repo).strip()
    mtime = int(git(["show", "-s", "--format=%ct", "HEAD"],
                    repo).strip())
    files, gitlinks, skipped = collect(repo)
    if skipped:
        raise SystemExit(
            f"refusing to build: HEAD has symlink entries not "
            f"supported by the deliverable archive: {skipped}")
    ext = external_sources(gitlinks, repo)
    payload = []  # (name, data, mode)
    for mode, sha, path in files:
        data = git_bytes(["cat-file", "blob", sha], repo)
        fmode = 0o755 if mode == "100755" else 0o644
        payload.append((path, data, fmode))
    payload.append(("EXTERNAL_SOURCES.lock",
                    json.dumps(ext, indent=2,
                               sort_keys=True).encode()
                    + b"\n", 0o644))
    payload.append(("DELIVERABLE_NOTICE.txt",
                    notice_text(ext, shortsha).encode(), 0o644))
    man = "".join(
        f"{hashlib.sha256(d).hexdigest()}  {n}\n"
        for n, d, _ in sorted(payload, key=lambda e: e[0]))
    payload.append(("MANIFEST.sha256", man.encode(), 0o644))
    payload.sort(key=lambda e: e[0])

    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{NAME}-{shortsha}"
    tgz = out_dir / f"{base}.tar.gz"
    zp = out_dir / f"{base}.zip"
    with open(tgz, "wb") as raw, \
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode="w|") as tf:
        for n, d, m in payload:
            add_bytes_tar(tf, f"{base}/{n}", d, mtime, m)
    with zipfile.ZipFile(zp, "w") as zf:
        for n, d, m in payload:
            add_bytes_zip(zf, f"{base}/{n}", d, m)
    sums = out_dir / "SHA256SUMS"
    sums.write_text(
        "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  "
                f"{p.name}\n" for p in (tgz, zp)),
        encoding="utf-8")
    return [tgz, zp, sums]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="E1a clean deliverable archive")
    ap.add_argument("--write", action="store_true",
                    help="create the archive (default: dry-run)")
    ap.add_argument("--repo-root", default=str(REPO_ROOT))
    ap.add_argument("--out", default=None,
                    help="output dir (default <repo>/dist)")
    a = ap.parse_args()
    repo = Path(a.repo_root).resolve()
    out_dir = Path(a.out) if a.out else repo / "dist"
    clean = tree_clean(repo)
    files, gitlinks, skipped = collect(repo)

    if not a.write:
        print(f"[dry-run] {len(files)} files would be packaged "
              f"(committed tree HEAD).")
        for _m, _s, p in files:
            print(f"  + {p}")
        print(f"[dry-run] external sources (not bundled): "
              f"{[g[2] for g in gitlinks]}")
        if skipped:
            print(f"[dry-run] symlink entries skipped: {skipped}")
        if not clean:
            print("=" * 60)
            print("WARNING: working tree is DIRTY. A real archive "
                  "(--write) is refused in this state; the output "
                  "would NOT be releasable.")
            print("=" * 60)
        return 0

    if not clean:
        raise SystemExit(
            "refusing to build a real deliverable: working tree "
            "is dirty (git status --porcelain --untracked-files="
            "all is non-empty). Commit/clean first.")
    outs = build(repo, out_dir)
    print("deliverable written:")
    for p in outs:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
