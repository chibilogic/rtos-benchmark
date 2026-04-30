# Benchmark FreeRTOS

Implementazione del benchmark per FreeRTOS su NUCLEO-H743ZI2.

## Setup iniziale

```bash
# Submodule FreeRTOS Kernel
git submodule add https://github.com/FreeRTOS/FreeRTOS-Kernel \
                  freertos/FreeRTOS-Kernel

# Submodule STM32CubeH7 (per HAL e CMSIS)
git submodule add https://github.com/STMicroelectronics/STM32CubeH7 \
                  freertos/stm32_hal

git submodule update --init --recursive
```

## File da generare manualmente / con Claude Code

Lo scaffold contiene gia':
- CMakeLists.txt
- FreeRTOSConfig.h
- main.c
- test_ctxsw_irq.c
- test_ctxsw_mutex.c

Mancano (Claude Code puo' generarli partendo dai template STM32CubeH7):
- `system_stm32h7xx.c` — clock init a 480 MHz
- `startup_stm32h743xx.s` — vector table assembly
- `stm32h7xx_it.c` — wrapper IRQ (chiama `bench_t1_isr()`)
- `stm32h7xx_hal_msp.c` — HAL MSP init
- `STM32H743ZITx_FLASH.ld` — linker script

Tutti questi file si trovano nei template ufficiali di STMicroelectronics
in `STM32CubeH7/Projects/NUCLEO-H743ZI/Templates/`. Da li' vanno copiati
e modificati per il tuo progetto.

## Build

```bash
cd freertos/benchmark_freertos
cmake -B build -G Ninja \
      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake
cmake --build build
```

## Flash e UART

Identico al ChibiOS — vedi `chibios/README.md`.

## Verifica equivalenza con ChibiOS

Dopo il primo run, controlla che:
- `dwt_baseline` sia simile (~2-4 cicli)
- Il numero di iterazioni completate sia 10000 (verifica via CSV)
- Il GPIO PB0 produca lo stesso pattern all'oscilloscopio
