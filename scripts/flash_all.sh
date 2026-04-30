#!/usr/bin/env bash
#
# flash_all.sh — script di convenienza per il ciclo completo
# build → flash → collect su tutti e tre gli RTOS.
#
# Uso:
#   ./scripts/flash_all.sh chibios
#   ./scripts/flash_all.sh freertos
#   ./scripts/flash_all.sh zephyr
#   ./scripts/flash_all.sh all
#
# Richiede: openocd, arm-none-eabi-gcc, cmake, west (per zephyr)

set -e

PORT="${PORT:-/dev/ttyACM0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

build_chibios() {
    echo "===== Build ChibiOS ====="
    cd "$ROOT/chibios/benchmark_chibios"
    make -j
}

flash_chibios() {
    echo "===== Flash ChibiOS ====="
    openocd -f interface/stlink.cfg -f target/stm32h7x.cfg \
        -c "program $ROOT/chibios/benchmark_chibios/build/benchmark_chibios.elf verify reset exit"
}

build_freertos() {
    echo "===== Build FreeRTOS ====="
    cd "$ROOT/freertos/benchmark_freertos"
    cmake -B build -G Ninja
    cmake --build build
}

flash_freertos() {
    echo "===== Flash FreeRTOS ====="
    openocd -f interface/stlink.cfg -f target/stm32h7x.cfg \
        -c "program $ROOT/freertos/benchmark_freertos/build/benchmark_freertos.elf verify reset exit"
}

build_zephyr() {
    echo "===== Build Zephyr ====="
    cd "$ROOT/zephyr"
    source .venv/bin/activate
    west build -b nucleo_h743zi benchmark_zephyr -p always
}

flash_zephyr() {
    echo "===== Flash Zephyr ====="
    cd "$ROOT/zephyr"
    source .venv/bin/activate
    west flash
}

collect() {
    local rtos=$1
    echo "===== Collect risultati per $rtos ====="
    cd "$ROOT"
    ./scripts/collect_results.py --port "$PORT" --rtos "$rtos" \
        --output "results/${rtos}_results.csv"
}

run_one() {
    local rtos=$1
    case "$rtos" in
        chibios)
            build_chibios
            flash_chibios
            sleep 2
            collect chibios
            ;;
        freertos)
            build_freertos
            flash_freertos
            sleep 2
            collect freertos
            ;;
        zephyr)
            build_zephyr
            flash_zephyr
            sleep 2
            collect zephyr
            ;;
        *)
            echo "RTOS sconosciuto: $rtos"
            exit 1
            ;;
    esac
}

main() {
    local target="${1:-all}"
    case "$target" in
        all)
            run_one chibios
            run_one freertos
            run_one zephyr
            echo "===== Plot finale ====="
            cd "$ROOT" && ./scripts/plot_results.py
            ;;
        *)
            run_one "$target"
            ;;
    esac
}

main "$@"
