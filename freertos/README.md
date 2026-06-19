# Benchmark FreeRTOS

FreeRTOS port of the RTOS benchmark on STM32H750B-DK at 480 MHz.

## Setup

The submodules are already in the repo:
- `freertos/FreeRTOS-Kernel` (V11.3.0)
- `freertos/stm32_hal` (STM32CubeH7 v1.12.1, HAL + CMSIS)

```cmd
git submodule update --init --recursive
```

## Build

```cmd
cd freertos\benchmark_freertos
make PROFILE=fair_perf
```

The Makefile wrapper invokes CMake/Ninja under the hood. Output:
`build/<profile>/benchmark_freertos.elf` (also .bin, .hex, .map).

Other profiles: `realistic_tickless`, `debug_dev`.

## Flash

```cmd
openocd -f interface/stlink.cfg -f target/stm32h7x.cfg ^
        -c "program build/fair_perf/benchmark_freertos.elf verify reset exit"
```

## UART

ST-Link VCP at 115200 8N1 on USART3 (PB10/PB11). Same as the
other ports. Capture with `scripts/collect_results.py`.

## FreeRTOS-specific notes (post round-5)

- **All static, no heap**:
    `configSUPPORT_STATIC_ALLOCATION = 1`
    `configSUPPORT_DYNAMIC_ALLOCATION = 0`
    `configUSE_COUNTING_SEMAPHORES = 1`
  Every TCB and synchronisation object is statically declared
  by the application. `vApplicationGetIdleTaskMemory()` is
  provided in `main.c`. `heap_4.c` is intentionally NOT
  included in the build (`configSUPPORT_DYNAMIC_ALLOCATION=0`
  would otherwise trigger its compile-time `#error`); the
  FreeRTOS dynamic allocation path is unreachable.
- **TIM2 IRQ NVIC priority = 7** (uniform across the 3 RTOS
  ports). `configMAX_SYSCALL_INTERRUPT_PRIORITY = 5`, so 7 is
  numerically larger (= less urgent) than the kernel threshold
  and may safely call `vTaskNotifyGiveFromISR()`.
- **Mutexes (T3, T4)** use `xSemaphoreCreateMutexStatic` —
  priority inheritance is enabled by default. Do NOT use
  `xSemaphoreCreateBinary` for mutex semantics (no PI).
- **Marker GPIOs** use direct BSRR writes via the inline
  helpers in `bench_pins.h` — same shape as the ChibiOS and
  Zephyr ports.

For the full methodology see `docs/METHODOLOGY.md` at the repo root.
