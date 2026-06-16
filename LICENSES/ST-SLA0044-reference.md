# STMicroelectronics SLA0044 — reference note

> This note summarises how the project treats the STMicroelectronics files it
> redistributes. The authoritative licence text is `LICENSES/SLA0044.txt`
> (copied verbatim from the STM32CubeH7 distribution). Per-file header notices
> are authoritative.

## Files treated as SLA0044

Linked into / redistributed with the FreeRTOS port firmware:

| File | Verbatim copyright | Treatment |
|------|--------------------|-----------|
| `freertos/benchmark_freertos/system/stm32h7xx_it.c` | Copyright (c) 2019 STMicroelectronics. All rights reserved. | SLA0044 (ST "STM32 Projects"); handler bodies configured for this project |
| `freertos/benchmark_freertos/cfg/stm32h7xx_it.h` | Copyright (c) 2019 STMicroelectronics. All rights reserved. | SLA0044 |
| `freertos/benchmark_freertos/cfg/stm32h7xx_hal_conf.h` | Copyright (c) 2019 STMicroelectronics. All rights reserved. | SLA0044; module selection / oscillator values configured |
| `freertos/benchmark_freertos/startup/STM32H750XBHX_FLASH.ld` | Copyright (c) 2022 STMicroelectronics. All rights reserved. | SLA0044 — STM32CubeIDE-generated |

The `.ld` is a CubeIDE-generated linker script carrying an ST copyright notice;
the project treats it as SLA0044, consistent with the other ST "STM32 Projects"
files.

## Key SLA0044 conditions relevant to publication (see SLA0044.txt for the
## authoritative text)

- Redistribution and use in source and binary forms, with or without
  modification, are permitted subject to the licence conditions.
- Use and execution are permitted only on or with STMicroelectronics devices.
- The ST name/trademarks may not be used for endorsement without permission.
- The software may not be used or redistributed in a way that subjects it to
  any "Open Source Terms" (the licence names GPL/LGPL/MIT/BSD/Apache, etc.).

## Treatment

The project treats these files as SLA0044, retaining the ST-device-only use
restriction; the per-file ST notices are preserved.
