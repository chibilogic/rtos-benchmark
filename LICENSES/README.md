# License texts

This repository combines code under several licenses; the per-file SPDX headers
are authoritative and `../THIRD_PARTY_NOTICES.md` has the per-file mapping. The
top-level `../LICENSE` (GPL-3.0-or-later) is the default for Chibilogic files
without a per-file license. The full license texts are provided here for
redistribution compliance.

- `MIT.txt` — MIT (Chibilogic): the shared `common/` measurement layer and the
  `freertos/benchmark_freertos/` Chibilogic sources.
- `MIT-FreeRTOS.txt` — MIT (FreeRTOS kernel, Amazon.com):
  `freertos/benchmark_freertos/cfg/FreeRTOSConfig.h`.
- `Apache-2.0.txt` — Apache-2.0: the `zephyr/benchmark_zephyr/` Chibilogic
  sources; CMSIS Device `system_stm32h7xx.c` + `startup_stm32h750xbhx.s`
  (ARM/ST); and the ChibiOS `cfg/*.h` + `cfg/portab.*` files.
- `BSD-3-Clause.txt` — BSD-3-Clause (STM32H7 HAL): the HAL driver sources
  linked from the STM32CubeH7 submodule.
- `SLA0044.txt` — STMicroelectronics SLA0044 (STM32 Projects / CubeIDE):
  `freertos/benchmark_freertos/cfg/stm32h7xx_hal_conf.h`,
  `freertos/benchmark_freertos/cfg/stm32h7xx_it.h`,
  `freertos/benchmark_freertos/system/stm32h7xx_it.c`. The STM32CubeIDE
  linker script `freertos/benchmark_freertos/startup/STM32H750XBHX_FLASH.ld`
  has a TBD applicable license and is conservatively treated as SLA0044 for
  release compliance.

The top-level GPL-3.0-or-later text is in `../LICENSE` and covers the ChibiOS
port (`chibios/benchmark_chibios/`) and the host tooling (`scripts/`, `tests/`).
The submodule RTOS / HAL trees keep their own license files in-tree.
