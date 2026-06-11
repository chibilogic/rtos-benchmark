#!/usr/bin/env python3
"""
release_gate.py -- post-publication verifier (review P2.2).

Checks that a published `phase1-v1.0` tag/release is real and consistent with
the committed artefacts:
  - the git tag resolves on GitHub;
  - a GitHub Release exists for the tag;
  - the raw ZIP downloads from the immutable tag URL and its SHA-256 matches the
    committed sidecar;
  - the published README names the exact ZIP filename;
  - build_report's PUBLICATION_STATUS is "published".

This is a NETWORK tool, run at/after publication (Gate D); it is deliberately
NOT part of the offline host test suite. The HTTP fetcher is injectable so the
unit tests can run without network. Fail-stop: non-zero exit on any failure.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT_DEFAULT = Path(__file__).resolve().parent.parent
OWNER = "chibilogic"
REPO = "rtos-benchmark"


class GateError(Exception):
    """The release gate cannot run (not a publication failure)."""


def _http_get(url, *, fetch=None):
    """Return (status, body). `fetch` (url -> (status, bytes)) overrides the
    real HTTP for tests."""
    if fetch is not None:
        return fetch(url)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # pragma: no cover - network-dependent
        raise GateError(f"GET {url} failed: {e}")


def _published_zip(pub_dir):
    zips = sorted(pub_dir.glob("phase1-raw-logs-*.zip"))
    if len(zips) != 1:
        raise GateError(
            f"expected exactly one published zip in {pub_dir}, "
            f"found {len(zips)}")
    z = zips[0]
    side = pub_dir / (z.name + ".sha256")
    if not side.exists():
        raise GateError(f"missing sidecar {side}")
    expected = side.read_text(encoding="utf-8").split()[0]
    local = hashlib.sha256(z.read_bytes()).hexdigest()
    if local != expected:
        raise GateError(
            f"local sidecar mismatch for {z.name}: {local} != {expected}")
    return z.name, local


def _build_report_constants(root):
    """Structurally parse the TOP-LEVEL constant assignments in build_report.py
    (via ast, so a misleading comment cannot be mistaken for the assignment).
    Returns {name: value} for the publication constants."""
    src = (root / "scripts" / "build_report.py").read_text(
        encoding="utf-8", errors="replace")
    wanted = {"PUBLICATION_STATUS", "PUBLIC_REPOSITORY_URL",
              "PUBLIC_RAW_LOGS_URL"}
    consts = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in wanted:
                    try:
                        consts[t.id] = ast.literal_eval(node.value)
                    except Exception:
                        consts[t.id] = None
    return consts


def run_gate(root, tag="phase1-v1.0", *, fetch=None):
    """Return a list of failure strings (empty == PASS), or raise GateError."""
    failures = []
    pub = root / "published-logs" / "phase1"
    zip_name, zip_sha = _published_zip(pub)

    st, _ = _http_get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/git/refs/tags/{tag}",
        fetch=fetch)
    if st != 200:
        failures.append(f"git tag {tag} not found (HTTP {st})")

    st, _ = _http_get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/releases/tags/{tag}",
        fetch=fetch)
    if st != 200:
        failures.append(f"GitHub Release for {tag} not found (HTTP {st})")

    raw = (f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{tag}/"
           f"published-logs/phase1/{zip_name}")
    st, body = _http_get(raw, fetch=fetch)
    if st != 200:
        failures.append(f"raw ZIP not downloadable (HTTP {st}): {raw}")
    elif hashlib.sha256(body).hexdigest() != zip_sha:
        failures.append("downloaded ZIP sha256 != committed sidecar")

    readme = pub / "README.md"
    if not readme.is_file():
        failures.append(f"published README missing: {readme}")
    elif zip_name not in readme.read_text(encoding="utf-8", errors="replace"):
        failures.append(f"published README does not name {zip_name}")

    c = _build_report_constants(root)
    status = c.get("PUBLICATION_STATUS")
    if status != "published":
        failures.append(
            f"build_report PUBLICATION_STATUS is {status!r}, "
            f"expected 'published'")
    repo_url = c.get("PUBLIC_REPOSITORY_URL") or ""
    logs_url = c.get("PUBLIC_RAW_LOGS_URL") or ""
    expected_repo = f"https://github.com/{OWNER}/{REPO}/tree/{tag}"
    if repo_url != expected_repo:
        failures.append(
            f"PUBLIC_REPOSITORY_URL must equal the canonical "
            f"{expected_repo!r}, got {repo_url!r}")
    if logs_url != raw:
        failures.append(
            f"PUBLIC_RAW_LOGS_URL must equal the canonical {raw!r}, "
            f"got {logs_url!r}")

    return failures


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Post-publication release gate (network).")
    ap.add_argument("--tag", default="phase1-v1.0")
    ap.add_argument("--project-root", default=None)
    args = ap.parse_args(argv)
    root = (Path(args.project_root).resolve() if args.project_root
            else PROJECT_ROOT_DEFAULT)
    try:
        failures = run_gate(root, args.tag)
    except GateError as e:
        sys.stderr.write(f"release_gate: ERROR -- {e}\n")
        return 2
    if failures:
        sys.stderr.write("release_gate: FAIL:\n")
        for f in failures:
            sys.stderr.write(f"  - {f}\n")
        return 1
    print(f"release_gate: PASS -- {args.tag} is published and consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
