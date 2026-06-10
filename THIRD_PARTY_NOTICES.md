# Third-party notices

This repository combines Chibilogic-authored code and upstream code, each under
its own license; the per-file `SPDX-License-Identifier` headers are
authoritative and complete texts are under `LICENSES/`.

Chibilogic-authored code is licensed **per port, matching the RTOS it runs on**:
- `chibios/benchmark_chibios/` sources — GPL-3.0-or-later (ChibiOS RT kernel is
  GPLv3);
- `freertos/benchmark_freertos/` Chibilogic sources — MIT;
- `zephyr/benchmark_zephyr/` Chibilogic sources — Apache-2.0;
- shared `common/` measurement layer — MIT;
- host tooling `scripts/` and `tests/` — GPL-3.0-or-later.

The top-level `LICENSE` (GPL-3.0-or-later) is the default where no per-file
license applies.

The upstream-derived items below are **not** Chibilogic-authored and keep their
original copyright and license; the notice inside each file is authoritative.

## Application-tree files that keep their upstream license

These files live in the application tree (not in the RTOS/HAL submodule
trees) but retain their upstream licenses and are NOT relicensed under GPL.
Some were configured or modified for this project; each retains its original
license and notice. Complete upstream license texts are under `LICENSES/`.

### ChibiOS port (Apache-2.0, Copyright ChibiOS / Giovanni Di Sirio)

- `chibios/benchmark_chibios/cfg/chconf.h`
- `chibios/benchmark_chibios/cfg/halconf.h`
- `chibios/benchmark_chibios/cfg/mcuconf.h`
- `chibios/benchmark_chibios/cfg/portab.c`
- `chibios/benchmark_chibios/cfg/portab.h`

### FreeRTOS (MIT, Copyright Amazon.com, Inc.)

- `freertos/benchmark_freertos/cfg/FreeRTOSConfig.h` — from the STM32CubeH7
  FreeRTOS_Mail template; configured for this project, retains the FreeRTOS
  MIT copyright and permission notice. See `LICENSES/MIT-FreeRTOS.txt`.

### CMSIS Device (Apache-2.0, Copyright ARM Limited / STMicroelectronics)

- `freertos/benchmark_freertos/system/system_stm32h7xx.c`
- `freertos/benchmark_freertos/startup/startup_stm32h750xbhx.s`

  See `LICENSES/Apache-2.0.txt`.

### STMicroelectronics — STM32CubeH7 examples / CubeIDE (SLA0044)

- `freertos/benchmark_freertos/system/stm32h7xx_it.c` — ST interrupt-handler
  template; handler bodies configured for this project (delegate to FreeRTOS
  and the T1 test). Retains the ST notice.
- `freertos/benchmark_freertos/cfg/stm32h7xx_it.h`
- `freertos/benchmark_freertos/cfg/stm32h7xx_hal_conf.h` — module selection and
  oscillator values configured for this project. Retains the ST notice.
- `freertos/benchmark_freertos/startup/STM32H750XBHX_FLASH.ld` — STM32CubeIDE
  linker script; memory map set for STM32H750B-DK. Retains the ST notice.
  Its applicable license is TBD; it is conservatively treated as SLA0044 for
  release compliance pending confirmation by ST or counsel.

  The `stm32h7xx_it.c/.h` and `stm32h7xx_hal_conf.h` files are licensed by
  STMicroelectronics under SLA0044 (the STM32 Projects component, per the
  STM32CubeH7 `LICENSE.md`). See `LICENSES/SLA0044.txt`. They are
  configured/modified for this project but are NOT relicensed under GPL.

## Bundled RTOS / HAL trees (git submodules / west)

Referenced as git submodules or a Zephyr west tree, kept under their own
upstream licenses, not relicensed:

- ChibiOS (`chibios/ChibiOS`) — GPLv3 (this pinned build selects
  `CH_LICENSE_GPL`).
- FreeRTOS-Kernel (`freertos/FreeRTOS-Kernel`) — MIT.
- STM32CubeH7 HAL + CMSIS (`freertos/stm32_hal`) — Apache-2.0 /
  BSD-3-Clause / STMicroelectronics license, per file.
- Zephyr (`zephyr/zephyr`) — Apache-2.0.

When in doubt, the license header inside each individual file is
authoritative.
