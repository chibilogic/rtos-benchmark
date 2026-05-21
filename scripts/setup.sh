#!/usr/bin/env sh
# ADR-021 follow-up - thin wrapper around scripts/setup.py.
# Single source of truth lives in setup.py; this script just
# selects a Python 3 launcher (`python3` preferred, `python`
# fallback for Git-Bash on Windows or minimal Linux installs)
# and delegates, propagating the exit code.
# Codex 2026-05-21-setup-orchestrator-plan-review-001 REQ 2:
# no orchestration logic here.
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$DIR/setup.py" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "$DIR/setup.py" "$@"
else
    echo "Python 3 not found on PATH. See docs/SETUP.md sec. 2." >&2
    exit 1
fi
