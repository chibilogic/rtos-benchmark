#!/usr/bin/env sh
# ADR-021 thin wrapper - delegates to bootstrap_toolchain.py
exec python3 "$(dirname -- "$0")/bootstrap_toolchain.py" "$@"
