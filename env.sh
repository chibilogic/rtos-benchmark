#!/usr/bin/env sh
# ADR-021 - activate the repo-local toolchain for THIS shell only
# (Linux x86_64). Source it, do not exec:  . ./env.sh
REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE:-$0}")" && pwd)"
TC="$REPO_ROOT/tools/linux-x86_64"
PATH="$TC/arm-gnu-toolchain/bin:$TC/make/bin:$TC/openocd/bin:$PATH"
export PATH
if ! arm-none-eabi-gcc --version 2>/dev/null | head -n 1; then
  echo "[!] arm-none-eabi-gcc not found - run: python scripts/bootstrap_toolchain.py"
fi
