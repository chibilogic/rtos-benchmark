# RTOS Benchmark — ChibiOS vs FreeRTOS vs Zephyr

Confronto rigoroso e riproducibile delle prestazioni di tre RTOS embedded
sul medesimo hardware (STM32 Nucleo-H743ZI2, Cortex-M7 @ 480 MHz).

## Test implementati

Due varianti del context switch, le piu rappresentative del comportamento RT:

| ID  | Test                              | Descrizione                                                |
|-----|-----------------------------------|------------------------------------------------------------|
| T1  | Context switch via IRQ wake-up    | Un IRQ HW sveglia un thread bloccato su semaforo/signal    |
| T2  | Context switch via mutex          | Due thread si contendono un mutex con priority inheritance |

Entrambi i test sono ispirati alla logica di `rt_test_sequence_012.c` di
ChibiOS (vedi `reference/`) ma riscritti con API native per ciascun RTOS
e misurati con strumento neutrale (`DWT->CYCCNT` + GPIO toggle).

## Hardware richiesto

- STM32 Nucleo-H743ZI2 (~28€)
- Oscilloscopio 100 MHz, 2 canali (per validazione esterna del DWT)
- Cavo USB micro-B
- Eventuali jumper per esporre PB0 (GPIO di test)

## Quick start

Vedi `docs/SETUP.md` per la procedura completa di installazione delle
toolchain. Una volta pronto:

```bash
# Build ChibiOS
cd chibios/benchmark_chibios && make

# Build FreeRTOS
cd freertos/benchmark_freertos && cmake -B build && cmake --build build

# Build Zephyr
cd zephyr && west build -b nucleo_h743zi benchmark_zephyr

# Raccogli risultati
./scripts/collect_results.py --port /dev/ttyACM0 --rtos chibios

# Plot comparativo
./scripts/plot_results.py
```

## Struttura del repository

```
rtos-benchmark/
├── common/         API astratta + DWT cycle counter (codice condiviso)
├── chibios/        Progetto ChibiOS (con submodule)
├── freertos/       Progetto FreeRTOS + STM32 HAL (con submodule)
├── zephyr/         Workspace west per Zephyr
├── reference/      Codice ChibiOS di riferimento (sequence_012)
├── scripts/        Tool Python per parsing e plotting risultati
├── results/        CSV grezzi e grafici prodotti
└── docs/           Metodologia, setup, analisi
```

## Metodologia

Vedi `docs/METHODOLOGY.md` per i dettagli su:
- Configurazione clock identica sui 3 RTOS (480 MHz, cache OFF)
- Tick rate (1000 Hz) e modalita tickless
- Strategia di misurazione hardware-ground-truth
- Numero di iterazioni e analisi statistica (10.000 run, min/max/mean/sigma/p99.9)

## Licenze

- ChibiOS: Apache 2.0
- FreeRTOS: MIT
- Zephyr: Apache 2.0
- STM32 HAL: BSD 3-clause
- Codice di questo progetto: MIT (vedi `LICENSE`)
