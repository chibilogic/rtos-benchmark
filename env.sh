#!/usr/bin/env bash
# =============================================================
#  RTOS Benchmark - environment activation script (Linux x86_64)
#
#  Sources the project-local toolchain for THIS shell only.
#  Usage:  . ./env.sh    (or:  source ./env.sh)
#  Requires bash.
#
#  Tools under tools/ are populated by
#  scripts/bootstrap_toolchain.py (ADR-021) or installed manually
#  at the exact versions documented in docs/SETUP.md:
#    - arm-none-eabi-gcc 14.2.Rel1
#    - GNU Make 4.3
#    - xPack OpenOCD 0.12.0+dev
#  Optional:
#    - zephyr/.venv/bin/west  (only for Zephyr builds)
# =============================================================

# Source-vs-exec detection: this script MUST be sourced.
if [[ "${BASH_SOURCE[0]:-$0}" == "${0}" ]]; then
    echo "[!] env.sh must be sourced, not executed:  . ./env.sh" >&2
    exit 1
fi

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# --- ADR-021: prefer the tools/linux-x86_64 bootstrap layout;
#     fall back to a legacy tools/ layout if not bootstrapped. ---
TC_NEW="${REPO_ROOT}/tools/linux-x86_64"
if [[ -x "${TC_NEW}/arm-gnu-toolchain/bin/arm-none-eabi-gcc" ]]; then
    PATH="${TC_NEW}/arm-gnu-toolchain/bin:${TC_NEW}/make/bin:${TC_NEW}/openocd/bin:${PATH}"
    export OPENOCD_SCRIPTS="${TC_NEW}/openocd/openocd/scripts"
    export GNUARMEMB_TOOLCHAIN_PATH="${TC_NEW}/arm-gnu-toolchain"
elif [[ -x "${REPO_ROOT}/tools/gcc-arm/bin/arm-none-eabi-gcc" ]]; then
    PATH="${REPO_ROOT}/tools/gcc-arm/bin:${REPO_ROOT}/tools/openocd/bin:${PATH}"
    export OPENOCD_SCRIPTS="${REPO_ROOT}/tools/openocd/openocd/scripts"
    export GNUARMEMB_TOOLCHAIN_PATH="${REPO_ROOT}/tools/gcc-arm"
else
    echo "[!] arm-none-eabi-gcc not found under tools/" >&2
    echo "    run:  python3 scripts/bootstrap_toolchain.py" >&2
    echo "    or install the toolchain manually per docs/SETUP.md sec.2" >&2
    return 1
fi
export PATH

# --- Zephyr venv (optional). Adding bin/ to PATH gives us west
#     and the venv's python without explicit "activate". ---
if [[ -x "${REPO_ROOT}/zephyr/.venv/bin/west" ]]; then
    PATH="${REPO_ROOT}/zephyr/.venv/bin:${PATH}"
    export PATH
fi

export PROJECT_ROOT="${REPO_ROOT}"
export ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb

# --- Startup banner ---
echo ""
echo "=========================================="
echo "  RTOS Benchmark dev env ACTIVE"
echo "=========================================="
echo "Root        : ${REPO_ROOT}"
echo "OpenOCD cfg : ${OPENOCD_SCRIPTS}"
echo "Zephyr TC   : ${ZEPHYR_TOOLCHAIN_VARIANT} in ${GNUARMEMB_TOOLCHAIN_PATH}"
echo ""

# --- Tool version check ---
echo "Installed tools:"
echo "----------------"
if command -v arm-none-eabi-gcc >/dev/null 2>&1; then
    arm-none-eabi-gcc --version | head -n 1
else
    echo "[X] arm-none-eabi-gcc NOT found"
fi
if command -v make >/dev/null 2>&1; then
    make --version | head -n 1
else
    echo "[X] make NOT found"
fi
if command -v openocd >/dev/null 2>&1; then
    openocd --version 2>&1 | head -n 1
else
    echo "[X] openocd NOT found"
fi
if command -v cmake >/dev/null 2>&1; then
    cmake --version | head -n 1
else
    echo "[--] cmake NOT in PATH (required for FreeRTOS and Zephyr builds)"
fi
if command -v west >/dev/null 2>&1; then
    west --version 2>/dev/null | head -n 1
else
    echo "[--] west NOT in PATH (only needed for Zephyr builds)"
fi
echo ""
