# ADR-021 follow-up - thin wrapper around scripts/setup.py.
# Single source of truth lives in setup.py; this script selects
# a Python 3 launcher (`py -3` preferred, `python` fallback) and
# delegates, propagating $LASTEXITCODE.
# Codex 2026-05-21-setup-orchestrator-plan-review-001 REQ 2:
# no orchestration logic here.
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SetupPy = Join-Path $ScriptDir "setup.py"
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $SetupPy @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python $SetupPy @args
} else {
    Write-Error "Python 3 not found on PATH. See docs/SETUP.md sec. 2."
    exit 1
}
exit $LASTEXITCODE
