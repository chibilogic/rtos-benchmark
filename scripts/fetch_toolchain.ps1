# ADR-021 thin wrapper - delegates to bootstrap_toolchain.py
python "$PSScriptRoot\bootstrap_toolchain.py" @args
exit $LASTEXITCODE
