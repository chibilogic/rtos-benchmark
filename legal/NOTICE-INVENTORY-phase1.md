# Phase 1 per-ELF NOTICE inventory

> READY FOR LEGAL REVIEW — NOT LEGAL SIGN-OFF.
>
> Per-ELF linked-component / licence / copyright-notice inventory for the six
> publishable firmware images, prepared for legal review. Linked components are
> read from each image's GNU ld `.map` (the .map is the authoritative full set;
> the object/component columns list representative linked objects). Copyright
> notices are reproduced from the pinned source headers with whitespace and line
> breaks normalised; the source headers remain authoritative. Toolchain runtime
> (newlib/picolibc, libgcc, libm) is shared by all images and listed once at the
> end.
>
> Status legend: `OK` = standard permissive/copyleft notice; `LEGAL_REVIEW` =
> needs counsel; `TBD` = applicable licence unconfirmed.

## Source of truth
- Linked objects/archives: `results/raw/<rtos>_<profile>_run01.map`.
- Firmware identity: `loadable_image_sha256` in the campaign locks (ADR-025).
- Source provenance: root + submodule commits + west projects in the release
  manifest (`scripts/release_manifest.py`).
- The two profiles (fair_perf / realistic_tickless) of a given RTOS link the
  same component set; each section covers BOTH that RTOS's ELFs.

## chibios_fair_perf_run01.elf · chibios_realistic_tickless_run01.elf
Resulting image: GPLv3 (links the GPLv3 ChibiOS RT kernel).

| Component | Linked objects (.map) | SPDX | Copyright notice (normalized) | Notice action | Status |
|---|---|---|---|---|---|
| ChibiOS RT kernel + port | chschd, chthreads, chmtx, chsem, chsys, chvt, chcore, chcoreasm, chdebug, chinstances, chrfcu, chtrace (os/rt) | GPL-3.0-or-later | `ChibiOS - Copyright (C) 2006-2026 Giovanni Di Sirio.` | LICENSE (GPLv3) + Corresponding Source | OK |
| ChibiOS HAL / OSAL / OOP / board / startup | hal*, stm32_*, osal (os/hal/osal), oop_base_object (os/common/oop), nvic, vectors, board, portab, crt0_v7m, crt1 | Apache-2.0 | `ChibiOS - Copyright (C) 2006-2026 Giovanni Di Sirio.` | LICENSES/Apache-2.0.txt (modified-file note: counsel open item, not currently present) | OK |
| Chibilogic application | main, test_ctxsw_irq, test_thread_handoff, test_mutex_uncontended, test_mutex_pi | GPL-3.0-or-later | `Copyright (C) 2025-2026 Chibilogic s.r.l.` | LICENSE (GPLv3) | OK |
| Common measurement layer | bench_button, benchmark_stats, dwt_cycle_counter | MIT | `Copyright (C) 2025-2026 Chibilogic s.r.l.` | LICENSES/MIT.txt | OK |

## freertos_fair_perf_run01.elf · freertos_realistic_tickless_run01.elf
Resulting image: combination of component terms; NOT a single MIT/Apache work;
the SLA0044 portions are ST-device-only.

| Component | Source/objects | SPDX | Copyright notice (normalized) | Notice action | Status |
|---|---|---|---|---|---|
| Chibilogic application | benchmark_freertos/ (main, test_*, bench_pins, syscalls_stubs) | MIT | `Copyright (C) 2025-2026 Chibilogic s.r.l.` | LICENSES/MIT.txt | OK |
| Common measurement layer | common/ | MIT | `Copyright (C) 2025-2026 Chibilogic s.r.l.` | LICENSES/MIT.txt | OK |
| FreeRTOS kernel + ARM_CM7 port | FreeRTOS-Kernel/ + portable/GCC/ARM_CM7/r0p1 | MIT | `Copyright (C) 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.` ; `Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>` | LICENSES/MIT-FreeRTOS.txt | OK |
| FreeRTOSConfig.h | cfg/FreeRTOSConfig.h | MIT | `Copyright (C) 2017 Amazon.com, Inc. or its affiliates. All Rights Reserved.` | LICENSES/MIT-FreeRTOS.txt (modified-file note: counsel open item, not currently present) | OK |
| STM32H7 HAL drivers | stm32_hal/Drivers/STM32H7xx_HAL_Driver/Src | BSD-3-Clause | `Copyright (c) 2017 STMicroelectronics. All rights reserved.` | LICENSES/BSD-3-Clause.txt | OK |
| CMSIS Device system | system/system_stm32h7xx.c | Apache-2.0 | `Copyright (c) 2017 STMicroelectronics. All rights reserved.` | LICENSES/Apache-2.0.txt (modified-file note: counsel open item, not currently present) | OK |
| CMSIS Device startup | startup/startup_stm32h750xbhx.s | Apache-2.0 | `Copyright (c) 2018 STMicroelectronics. All rights reserved.` | LICENSES/Apache-2.0.txt | OK |
| ST interrupt handlers | system/stm32h7xx_it.c, cfg/stm32h7xx_it.h | SLA0044 (ST-device-only) | `Copyright (c) 2019 STMicroelectronics. All rights reserved.` | LICENSES/SLA0044.txt + ST-device note | LEGAL_REVIEW |
| ST HAL config | cfg/stm32h7xx_hal_conf.h | SLA0044 (ST-device-only) | `Copyright (c) 2019 STMicroelectronics. All rights reserved.` | LICENSES/SLA0044.txt (modified-file note: counsel open item, not currently present) | LEGAL_REVIEW |
| STM32CubeIDE linker script | startup/STM32H750XBHX_FLASH.ld | TBD (conservatively SLA0044) | `Copyright (c) 2022 STMicroelectronics. All rights reserved.` | LICENSES/SLA0044.txt; ST/counsel confirm BSD-3 basic-example vs SLA0044 | TBD |

## zephyr_fair_perf_run01.elf · zephyr_realistic_tickless_run01.elf
Resulting image: primarily Apache-2.0 (Zephyr + Chibilogic app), with documented
third-party components under their own terms; STM32 HAL portions BSD-3-Clause /
Apache-2.0.

| Component | Linked archives (.map) | SPDX | Copyright notice (normalized / representative) | Notice action | Status |
|---|---|---|---|---|---|
| Zephyr kernel/arch/drivers/subsys/lib | libzephyr, libkernel, libarch__arm__core*, libdrivers__*, liblib__* | Apache-2.0 (+ per-file) | per-file `SPDX-FileCopyrightText` (e.g. `Copyright The Zephyr Project Contributors`); many individual holders | LICENSES/Apache-2.0.txt + per-file attribution | LEGAL_REVIEW |
| Chibilogic application | libapp.a (benchmark_zephyr/src/*) | Apache-2.0 | `Copyright (C) 2025-2026 Chibilogic s.r.l.` | LICENSES/Apache-2.0.txt | OK |
| Common measurement layer | (linked into app) | MIT | `Copyright (C) 2025-2026 Chibilogic s.r.l.` | LICENSES/MIT.txt | OK |
| STM32 HAL + CMSIS (hal_stm32 module) | lib..__modules__hal__stm32__stm32cube.a | BSD-3-Clause (HAL) + Apache-2.0 (CMSIS) | `Copyright (c) ... STMicroelectronics` ; `Copyright (c) ... Arm Limited` | LICENSES/BSD-3-Clause.txt + Apache-2.0.txt | OK |
| picolibc | liblib__libc__picolibc.a | BSD-3-Clause / MIT (per file) | multiple (Keith Packard, Arm, SiFive, ...) | toolchain runtime; per-file | LEGAL_REVIEW |

## Toolchain runtime (all six images)
| Component | Archive | SPDX | Notes |
|---|---|---|---|
| newlib (full / nano / nosys) | libg.a, libc_nano.a, libnosys.a, libm.a | newlib (BSD-like, multiple holders) | ChibiOS links full newlib, FreeRTOS links nano; ADR-009 libc disclaimer |
| GCC runtime | libgcc.a | GPL-3.0 + GCC Runtime Library Exception | FSF; the runtime exception permits linking into non-GPL images |

## Modified-vs-upstream (Apache/MIT modified-file notices) — STATUS + OPEN ITEM
Files configured/modified for this project: `cfg/FreeRTOSConfig.h`,
`system/system_stm32h7xx.c`, `system/stm32h7xx_it.c`, `cfg/stm32h7xx_hal_conf.h`,
`startup/STM32H750XBHX_FLASH.ld`, ChibiOS `cfg/*` (chconf.h, halconf.h,
mcuconf.h, portab.*), Zephyr `prj.conf` / `conf/*` / board overlay. CURRENT
notice status: only `system/stm32h7xx_it.c` carries an explicit
"configured/modified for the rtos-benchmark project by Chibilogic" note; the
others retain their upstream copyright but do NOT currently carry such a note.
Whether a modified-file notice must be ADDED to those upstream-owned files (and
which) is a LEGAL_REVIEW / policy decision -- they are NOT modified here without
counsel/user sign-off.

## Open items for counsel
1. Zephyr: full per-file Apache `SPDX-FileCopyrightText` attribution for the
   actually-linked objects (the release manifest pins the 68 west project
   commits; the per-file copyright harvest across them is LEGAL_REVIEW).
2. picolibc / newlib / libgcc: whether the statically-linked toolchain runtime
   copyrights must be reproduced, or are covered by the runtime exception / the
   ADR-009 libc disclaimer.
3. SLA0044 `.c/.h` + the `.ld` (TBD): see `legal/SLA0044-QUESTIONS.md`.
4. CMSIS Device: confirm whether the Arm CMSIS-Core copyright must accompany the
   linked CMSIS objects in addition to the ST copyright.

READY FOR LEGAL REVIEW — NOT LEGAL SIGN-OFF.
