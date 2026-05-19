#!/usr/bin/env bash
#
# flash_all.sh - build, flash and capture the benchmark across the
# 3 RTOS ports.
#
# Round-11 item 1+item 2 ordering: the collector is started BEFORE the chip
# is reset, so the boot banner (banner divider + memory placement +
# CSV header) is captured. The previous version of this script did
# `flash -> sleep 2 -> collect` and consequently lost the banner -
# collect_results.py would then exit non-zero on
#  "expected exactly 2 banner divider lines (= 1 boot), found 0".
#
# After every successful per-RTOS capture, the script also runs:
#   analyze_results.py   to cross-check firmware stats
#   report_results.py    to generate per-run + aggregate summaries
#   plot_results.py      to render charts from those summaries
#
# Usage:
#   ./scripts/flash_all.sh chibios   [--profile fair_perf] [--run-id 01]
#   ./scripts/flash_all.sh freertos  [--profile fair_perf] [--run-id 01]
#   ./scripts/flash_all.sh zephyr    [--profile fair_perf] [--run-id 01]
#   ./scripts/flash_all.sh all       [--profile fair_perf] [--run-id 01]
#
# Env:
#   PORT                serial device for the ST-Link VCP
#                       (default: /dev/ttyACM0; on Windows pass
#                       PORT=COM5 or similar before invoking)
#   PROFILE             build profile (default: fair_perf)
#   RUN_ID              run id used in output filenames (default: 01)
#   COLLECTOR_TIMEOUT   timeout in seconds passed to collect_results.py
#                       (default: 600 - long enough for a B1-gated run)
#   PUBLICATION_MODE    'la' or 'dwt_only'; default 'dwt_only'
#                       (ADR-015 Phase 1).
#   AUTORUN             0 or 1; default 1 in this dev helper so the
#                       operator does not have to press B1 between
#                       tests. For lab publication campaigns use
#                       lab_campaign.ps1 which sets AUTORUN
#                       coherently with PUBLICATION_MODE.
#
# This script is intended for development / CI runs.
# Lab campaigns for the publishable 5x3 matrix should run each
# command manually so the operator can arm the logic analyzer
# between the collector start and the board reset (see
# docs/SETUP.md sec. 6).

set -e

PORT="${PORT:-/dev/ttyACM0}"
PROFILE="${PROFILE:-fair_perf}"
RUN_ID="${RUN_ID:-01}"
COLLECTOR_TIMEOUT="${COLLECTOR_TIMEOUT:-600}"
PUBLICATION_MODE="${PUBLICATION_MODE:-dwt_only}"

# 2b followup (Codex round-3 IMPORTANT 1): AUTORUN must agree
# with PUBLICATION_MODE. Mode 'la' requires B1 gating
# (AUTORUN=0); Mode 'dwt_only' allows AUTORUN=1 (default). If
# the operator supplies an inconsistent combination we fail
# before touching the toolchain.
if [ "$PUBLICATION_MODE" = "dwt_only" ]; then
    AUTORUN="${AUTORUN:-1}"
elif [ "$PUBLICATION_MODE" = "la" ]; then
    AUTORUN="${AUTORUN:-0}"
else
    echo "FAIL: unknown PUBLICATION_MODE='$PUBLICATION_MODE'" >&2
    exit 2
fi
if [ "$PUBLICATION_MODE" = "la" ] && [ "$AUTORUN" = "1" ]; then
    echo "FAIL: PUBLICATION_MODE=la is incompatible with AUTORUN=1" >&2
    echo "       Mode LA requires B1 gating (ADR-016)." >&2
    exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# --- Builds ---------------------------------------------------------

build_chibios() {
    echo "===== Build ChibiOS ($PROFILE, AUTORUN=$AUTORUN) ====="
    cd "$ROOT/chibios/benchmark_chibios"
    make PROFILE="$PROFILE" AUTORUN="$AUTORUN" -j
}

build_freertos() {
    echo "===== Build FreeRTOS ($PROFILE, AUTORUN=$AUTORUN) ====="
    cd "$ROOT/freertos/benchmark_freertos"
    make PROFILE="$PROFILE" AUTORUN="$AUTORUN"
}

build_zephyr() {
    echo "===== Build Zephyr ($PROFILE, AUTORUN=$AUTORUN) ====="
    cd "$ROOT/zephyr/benchmark_zephyr"
    make PROFILE="$PROFILE" AUTORUN="$AUTORUN"
}

# --- ELF paths (canonical Makefile-wrapper layout, Codex B5) -------

elf_chibios() {
    echo "$ROOT/chibios/benchmark_chibios/build/$PROFILE/benchmark_chibios.elf"
}
elf_freertos() {
    echo "$ROOT/freertos/benchmark_freertos/build/$PROFILE/benchmark_freertos.elf"
}
elf_zephyr() {
    echo "$ROOT/zephyr/build/$PROFILE/zephyr/zephyr.elf"
}

# --- Flash + collect (correct ordering) -----------------------------

# Strategy: we first flash WITHOUT releasing reset, then start the
# collector, then explicitly reset the board so the banner arrives
# while the collector is already listening.
#
#   step 1: openocd "program <elf> verify exit"   - flashes, halts CPU
#   step 2: collect_results.py opens UART (background)
#   step 3: openocd "init; reset run; exit"        - runs the firmware
#   step 4: wait for the collector to finish
#
# This eliminates the race the round-11 reviewer flagged on the old
# `flash; sleep 2; collect` ordering.

flash_only() {
    local elf="$1"
    echo "===== Flash $elf (no reset) ====="
    openocd -f interface/stlink.cfg -f target/stm32h7x.cfg \
        -c "reset_config srst_only srst_nogate connect_assert_srst" \
        -c "program $elf verify exit"
}

reset_run() {
    echo "===== Reset and run ====="
    openocd -f interface/stlink.cfg -f target/stm32h7x.cfg \
        -c "reset_config srst_only srst_nogate connect_assert_srst" \
        -c "init; reset run; exit"
}

flash_and_collect() {
    local rtos=$1
    local elf=$2
    local prefix="$ROOT/results/raw/${rtos}_${PROFILE}_run${RUN_ID}"
    local map="${elf%.elf}.map"

    echo "===== flash + collect: $rtos / $PROFILE / run $RUN_ID ====="

    # 2b-D (Codex round-3): publishable profiles require both ELF
    # and MAP. Fail before openocd touches the chip so no stale
    # binary gets a misleading "validated" stamp downstream.
    if [ ! -f "$elf" ]; then
        echo "FAIL: ELF not found: $elf" >&2
        return 1
    fi
    if [ ! -f "$map" ]; then
        echo "FAIL: MAP not found: $map" >&2
        return 1
    fi

    # Audit log: print actual artefact hashes (Codex
    # auditability principle, mirrors lab_smoke.ps1 2b-B).
    if command -v sha256sum >/dev/null 2>&1; then
        echo "  ELF: $elf  ($(sha256sum "$elf" | awk '{print $1}'))"
        echo "  MAP: $map  ($(sha256sum "$map" | awk '{print $1}'))"
    else
        echo "  ELF: $elf"
        echo "  MAP: $map"
    fi
    echo "  publication-mode: $PUBLICATION_MODE"

    flash_only "$elf"

    # Start the collector in the background so it is already
    # listening on the UART when we release the reset.
    python "$ROOT/scripts/collect_results.py" \
        --port "$PORT" \
        --rtos "$rtos" \
        --profile "$PROFILE" \
        --run-id "$RUN_ID" \
        --output "$prefix" \
        --timeout "$COLLECTOR_TIMEOUT" \
        --publication-mode "$PUBLICATION_MODE" \
        --elf-file "$elf" \
        --map-file "$map" &
    local collector_pid=$!

    # Tiny grace period so pyserial actually opens the device before
    # the firmware emits its first byte.
    sleep 1

    reset_run

    # Wait for the collector to finish (it self-terminates on
    # BENCHMARK COMPLETE + grace, or on idle timeout). If it
    # exited non-zero, propagate the failure.
    if ! wait "$collector_pid"; then
        echo "FAIL: collector returned non-zero for $rtos run $RUN_ID" >&2
        return 1
    fi

    # Cross-check firmware vs Python stats on this run.
    echo "===== analyze: $rtos run $RUN_ID ====="
    python "$ROOT/scripts/analyze_results.py" "$prefix"
}

run_one() {
    local rtos=$1
    case "$rtos" in
        chibios)  build_chibios;  flash_and_collect chibios  "$(elf_chibios)"  ;;
        freertos) build_freertos; flash_and_collect freertos "$(elf_freertos)" ;;
        zephyr)   build_zephyr;   flash_and_collect zephyr   "$(elf_zephyr)"   ;;
        *) echo "Unknown RTOS: $rtos" >&2; exit 1 ;;
    esac
}

# --- Post-collect pipeline ------------------------------------------

run_report_and_plot() {
    echo "===== report_results.py: $PROFILE ====="
    cd "$ROOT" && python scripts/report_results.py --profile "$PROFILE"

    echo "===== plot_results.py: $PROFILE ====="
    cd "$ROOT" && python scripts/plot_results.py --profile "$PROFILE"
}

# --- Main ------------------------------------------------------------

main() {
    local target="${1:-all}"
    if [ $# -gt 0 ]; then shift; fi
    while [ $# -gt 0 ]; do
        case "$1" in
            --profile) PROFILE="$2"; shift 2 ;;
            --run-id)  RUN_ID="$2";  shift 2 ;;
            *) echo "Unknown flag: $1" >&2; exit 1 ;;
        esac
    done
    case "$target" in
        all)
            run_one chibios
            run_one freertos
            run_one zephyr
            run_report_and_plot
            ;;
        report)
            run_report_and_plot
            ;;
        *)
            run_one "$target"
            # Round-12 follow-up: single-target also generates the
            # exploratory report/plot so the operator sees the
            # full pipeline output immediately. The MD outputs
            # carry the "EXPLORATORY ONLY" banner because we
            # never pass --publication-gate from a single-RTOS
            # invocation.
            run_report_and_plot
            ;;
    esac
}

main "$@"
