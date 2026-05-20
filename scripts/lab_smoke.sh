#!/usr/bin/env bash
# ADR-021 / Codex 2026-05-20-cross-platform-linux-readiness-001 -
# thin bash wrapper around the platform-neutral lab_runner.py.
# Equivalent to lab_smoke.ps1 on Windows. PowerShell script is
# kept intact in this commit (additive migration).
exec python3 "$(dirname -- "$0")/lab_runner.py" smoke "$@"
