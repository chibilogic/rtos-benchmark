#!/usr/bin/env python3
"""
Compact release / reproducibility manifest (Codex -015 Gate B, P1.4;
hardened per Codex CODE_REVIEW -016, -017, -018).

Fail-stop provenance tool. It records ONE coherent committed source state and
REFUSES to emit a manifest unless:
  - the root working tree is clean and every git query succeeds;
  - all submodules are initialized and at a clean checked-out commit (no +/-/U);
  - the toolchain and direct-requirements files exist;
  - the Zephyr west workspace resolves: every active project is cloned, clean,
    and its checked-out HEAD EQUALS the west-resolved SHA (from
    `west manifest --freeze --active-only`).
Digests are full SHA-256; submodule and west commits are exact 40-hex SHAs.

provenance_ready=true is emitted when the above all pass. release_ready stays
False until every entry in remaining_gates is closed; only Gate D / final
verification may set release_ready true. Source / metadata only; runs no build,
takes no measurement. The complete transitive hash-pinned dependency lock is
requirements.lock (bound here by publication_lock_sha256); only the clean-venv
install validation from it (B5) remains Gate D.

Run on a clean committed tree from a state where the Zephyr west workspace
(<root>/zephyr) is initialized and `west` (with PyYAML) is available, e.g. the
zephyr venv active.

Usage:
    python scripts/release_manifest.py
    python scripts/release_manifest.py --out PATH
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT_DEFAULT = Path(__file__).resolve().parent.parent

DIRECT_REQUIREMENTS = "requirements-publication-direct.txt"
LOCK_REQUIREMENTS = "requirements.lock"

_SHA40 = re.compile(r"[0-9a-fA-F]{40}")


class ManifestError(Exception):
    """Release provenance cannot be certified coherently."""


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), check=False,
                          capture_output=True, text=True)


def _git(root, *args, runner=None):
    out = (runner or _run)(["git", "-C", str(root), *args], root)
    if out.returncode != 0:
        raise ManifestError(
            f"git {' '.join(args)} failed (rc={out.returncode}): "
            f"{out.stderr.strip()}")
    return out.stdout


def _sha256_full(path):
    if not path.exists():
        raise ManifestError(f"required file missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _west_revision(root):
    wy = root / "zephyr" / "benchmark_zephyr" / "west.yml"
    if not wy.exists():
        raise ManifestError(f"missing {wy}")
    m = re.search(r"revision:\s*(\S+)",
                  wy.read_text(encoding="utf-8", errors="replace"))
    if not m:
        raise ManifestError("no 'revision:' found in west.yml")
    return m.group(1)


_SUBMODULE_RE = re.compile(
    r"^(?P<marker>[ \-+U])(?P<sha>[0-9a-fA-F]{40})\s+(?P<path>\S+)"
    r"(?:\s+\((?P<desc>.+)\))?\s*$")


def _submodules(root, git):
    raw = git(root, "submodule", "status")
    subs = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        m = _SUBMODULE_RE.match(line)
        if not m:
            raise ManifestError(f"unparseable submodule status: {line!r}")
        marker = m.group("marker")
        if marker == "-":
            raise ManifestError(
                f"submodule not initialized: {m.group('path')}")
        if marker in "+U":
            raise ManifestError(
                f"submodule {m.group('path')} not at the recorded commit "
                f"(marker {marker!r}); sync/commit it first")
        subs[m.group("path")] = {
            "commit": m.group("sha"),
            "describe": m.group("desc") or "no-describe",
        }
    if not subs:
        raise ManifestError("git submodule status reported no submodules")
    return subs


def _proj_git(runner, proj, args, *, allow_fail=False):
    out = (runner or _run)(["git", "-C", str(proj), *args], proj)
    if out.returncode != 0:
        if allow_fail:
            return None
        raise ManifestError(
            f"git {' '.join(args)} failed in {proj}: {out.stderr.strip()}")
    return out.stdout


def _parse_frozen_manifest(text):
    """Parse `west manifest --freeze` YAML into (projects, self_path).

    projects: list of dicts each with at least 'name' and 'revision'.
    Requires PyYAML (available in the Zephyr venv that hosts west)."""
    try:
        import yaml
    except ImportError as e:  # pragma: no cover - environment-dependent
        raise ManifestError(
            "PyYAML is required to parse the frozen west manifest: "
            + str(e))
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        raise ManifestError(f"could not parse frozen west manifest: {e}")
    man = (data or {}).get("manifest")
    if not isinstance(man, dict):
        raise ManifestError("frozen west manifest has no 'manifest' mapping")
    projects = man.get("projects") or []
    self_path = (man.get("self") or {}).get("path")
    return projects, self_path


def _west_projects(root, *, west_runner=None, git_runner=None):
    """Resolve exact west provenance from the <root>/zephyr workspace.

    Uses `west manifest --freeze --active-only` (run IN THE WORKSPACE) as the
    authoritative resolved inventory: every active project resolves to an exact
    40-hex SHA. For each project it records the checked-out HEAD and FAILS unless
    the project is cloned, clean, has a 40-hex resolved revision, and its HEAD
    EQUALS that resolved SHA. The manifest repository (west `self`) is recorded
    separately (its commit is the root repo commit; filled by build_manifest).
    Returns {"projects": {name: {"commit": sha40}},
             "manifest_repo": {"path": .., "commit": None,
                               "commit_source": "root_commit"}}."""
    ws = root / "zephyr"
    if not (ws / ".west").exists():
        raise ManifestError(f"no west workspace at {ws} (.west missing)")
    out = (west_runner or _run)(
        ["west", "manifest", "--freeze", "--active-only"], ws)
    if out.returncode != 0:
        raise ManifestError(
            f"`west manifest --freeze --active-only` failed in {ws}: "
            f"{out.stderr.strip()}")
    raw_projects, self_path = _parse_frozen_manifest(out.stdout)
    projects = {}
    for p in raw_projects:
        if not isinstance(p, dict) or "name" not in p:
            raise ManifestError(f"unparseable frozen project entry: {p!r}")
        name = p["name"]
        resolved = str(p.get("revision") or "")
        if not _SHA40.fullmatch(resolved):
            raise ManifestError(
                f"west project {name!r} has no resolved 40-hex revision in "
                f"the frozen manifest (got {resolved!r}); cannot certify "
                f"consistency")
        path = p.get("path") or name
        proj = ws / path
        if not (proj / ".git").exists():
            raise ManifestError(
                f"west project {name!r} is active but not cloned at {proj}")
        head = (_proj_git(git_runner, proj,
                          ["rev-parse", "--verify", "--quiet", "HEAD"])
                or "").strip()
        if not _SHA40.fullmatch(head):
            raise ManifestError(
                f"unexpected HEAD for west project {name!r}: {head!r}")
        dirty = _proj_git(git_runner, proj, ["status", "--porcelain"]) or ""
        if dirty.strip():
            raise ManifestError(f"west project {name!r} checkout is dirty")
        if head != resolved:
            raise ManifestError(
                f"west project {name!r} HEAD {head} != manifest-resolved "
                f"revision {resolved}")
        projects[name] = {"commit": head}
    if not projects:
        raise ManifestError(
            "frozen west manifest listed no active projects")
    manifest_repo = {
        "path": self_path,
        "commit": None,          # filled by build_manifest = root_commit
        "commit_source": "root_commit",
    }
    return {"projects": projects, "manifest_repo": manifest_repo}


def build_manifest(root, *, git=_git, west=_west_projects):
    """Build the provenance manifest dict, or raise ManifestError.

    provenance_ready is True only when the root git tree, submodules and the
    west workspace all pass coherence checks. release_ready stays False until
    every remaining_gates entry is closed (Gate D)."""
    status = git(root, "status", "--porcelain")
    if status.strip():
        raise ManifestError(
            "working tree not clean; a release manifest must describe ONE "
            "committed state. Offending entries:\n" + status.strip())
    head = git(root, "rev-parse", "HEAD").strip()
    if not _SHA40.fullmatch(head):
        raise ManifestError(f"unexpected HEAD: {head!r}")
    west_info = west(root)
    manifest_repo = west_info["manifest_repo"]
    if manifest_repo is not None and manifest_repo.get("commit") is None:
        manifest_repo = {**manifest_repo, "commit": head}
    return {
        "root_commit": head,
        "submodules": _submodules(root, git),
        "zephyr_west_manifest_revision": _west_revision(root),
        "zephyr_west_projects": west_info["projects"],
        "zephyr_west_manifest_repo": manifest_repo,
        "toolchain_lock_sha256": _sha256_full(
            root / "tools" / "TOOLCHAIN.lock"),
        "publication_direct_requirements_sha256": _sha256_full(
            root / DIRECT_REQUIREMENTS),
        "publication_lock_sha256": _sha256_full(root / LOCK_REQUIREMENTS),
        "publication_runtime": (
            f"Direct package versions per {DIRECT_REQUIREMENTS}; the complete "
            f"transitive hash-pinned lock is {LOCK_REQUIREMENTS} (bound by "
            "publication_lock_sha256). Validated host: Windows x86_64, CPython "
            "3.14.3. Clean-venv install validation (B5) remains Gate D."),
        "provenance_ready": True,
        "release_ready": False,
        "remaining_gates": [
            "Gate D: clean-venv install + report/PDF build validation from "
            "requirements.lock (B5)",
            "Gate D: final public asset verification (tag/release URL + "
            "sha256)",
        ],
        "readiness_note": (
            "provenance_ready reflects coherent git + submodule + west "
            "provenance only. release_ready stays False until every entry in "
            "remaining_gates is closed; only Gate D / final verification may "
            "set release_ready true."),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Emit the fail-stop provenance manifest JSON.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--project-root", default=None)
    args = ap.parse_args(argv)
    root = (Path(args.project_root).resolve() if args.project_root
            else PROJECT_ROOT_DEFAULT)
    try:
        manifest = build_manifest(root)
    except ManifestError as e:
        sys.stderr.write(f"release_manifest: REFUSED -- {e}\n")
        return 2
    out = (Path(args.out) if args.out
           else root / "results" / "manifest" / "release_manifest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"OK: {out}")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
