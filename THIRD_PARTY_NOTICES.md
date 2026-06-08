# Third-party notices

This repository's original code — the `common/` measurement layer, the
per-RTOS benchmark sources under `*/benchmark_*/`, `scripts/`, the board
configuration written for this project, and the tests — is licensed under
**GPL-3.0-or-later** (see `LICENSE`). The per-file `SPDX-License-Identifier`
headers are authoritative.

The items below are **not** Chibilogic-authored and are **not** relicensed
under GPL-3.0. They retain their original copyright and license; the
notice inside each file is authoritative.

## Application-tree files derived from upstream templates

These files live in the application tree (not in the RTOS/HAL submodule
trees) but are derived from upstream RTOS / vendor templates and keep
their original notices.

### ChibiOS port (Apache-2.0, Copyright ChibiOS / Giovanni Di Sirio)

- `chibios/benchmark_chibios/cfg/chconf.h`
- `chibios/benchmark_chibios/cfg/halconf.h`
- `chibios/benchmark_chibios/cfg/mcuconf.h`
- `chibios/benchmark_chibios/cfg/portab.c`
- `chibios/benchmark_chibios/cfg/portab.h`

### STMicroelectronics (FreeRTOS-port STM32 HAL / startup / linker)

- `freertos/benchmark_freertos/cfg/stm32h7xx_hal_conf.h`
- `freertos/benchmark_freertos/cfg/stm32h7xx_it.h`
- `freertos/benchmark_freertos/startup/startup_stm32h750xbhx.s`
- `freertos/benchmark_freertos/startup/STM32H750XBHX_FLASH.ld`
- `freertos/benchmark_freertos/system/system_stm32h7xx.c`

> Note: `freertos/benchmark_freertos/cfg/FreeRTOSConfig.h` and
> `freertos/benchmark_freertos/system/stm32h7xx_it.c` carry a Chibilogic
> `SPDX-License-Identifier: GPL-3.0-or-later` header and are therefore
> Chibilogic-licensed (GPL), NOT listed here. The per-file SPDX header is
> authoritative.

## Bundled RTOS / HAL trees (git submodules / west)

Referenced as git submodules or a Zephyr west tree, kept under their own
upstream licenses, not relicensed:

- ChibiOS (`chibios/ChibiOS`) — Apache-2.0 / GPL dual.
- FreeRTOS-Kernel (`freertos/FreeRTOS-Kernel`) — MIT.
- STM32CubeH7 HAL + CMSIS (`freertos/stm32_hal`) — Apache-2.0 /
  BSD-3-Clause / STMicroelectronics license, per file.
- Zephyr (`zephyr/zephyr`) — Apache-2.0.

When in doubt, the license header inside each individual file is
authoritative.
