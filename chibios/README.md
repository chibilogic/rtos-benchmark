# Benchmark ChibiOS

ChibiOS/RT port of the RTOS benchmark on STM32H750B-DK at 480 MHz.

## Build

```cmd
cd chibios\benchmark_chibios
make
```

Default profile is `fair_perf`. Output:
`build/fair_perf/benchmark_chibios.elf` (also .bin, .hex, .list, .map).
For other profiles:

```cmd
make PROFILE=realistic_tickless
make PROFILE=debug_dev
```

The Makefile points at the upstream ChibiOS board file
(`os/hal/boards/ST_STM32H750XB_DISCOVERY/board.mk`) and the
upstream linker script `STM32H750xB.ld`. The cfg/ directory
holds project-local `chconf.h`, `halconf.h`, `mcuconf.h` derived
from the upstream demo `RT-STM32-MULTI/cfg/stm32h750xb_discovery/`.

## Flash

```cmd
openocd -f interface/stlink.cfg -f target/stm32h7x.cfg ^
        -c "program build/fair_perf/benchmark_chibios.elf verify reset exit"
```

## UART output

ST-Link VCP at 115200 8N1 on USART3 (PB10/PB11).

```cmd
python ..\..\scripts\collect_results.py ^
       --port COM<n> --rtos chibios --profile fair_perf --run-id 01
```

## Notes

- I+D cache **ON** at runtime (ADR-010).
- LTO disabled for cross-RTOS comparability (ADR-009).
- Static thread allocation (`chThdCreateStatic` +
  `THD_WORKING_AREA`). `CH_CFG_USE_HEAP` /
  `CH_CFG_USE_DYNAMIC` remain at their kernel defaults but
  the benchmark application code does not call any dynamic
  allocation primitive.
- Marker GPIOs use direct `GPIOH/I->BSRR` writes; identical
  shape to the FreeRTOS and Zephyr ports (round-4 cleanup).
- TIM2 driven directly by `test_ctxsw_irq.c` (PWM mode 2 + CC1
  IRQ at NVIC priority 7); the ChibiOS GPT driver is bypassed
  via `STM32_GPT_USE_TIM2 = FALSE` in mcuconf.h.

For the full methodology see `notes/ADR-001..015.md` and
`docs/METHODOLOGY.md` at the repo root.
