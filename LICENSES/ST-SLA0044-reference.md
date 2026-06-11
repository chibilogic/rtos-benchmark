# STMicroelectronics SLA0044 — reference note

> READY FOR LEGAL REVIEW — NOT LEGAL SIGN-OFF.
> This note summarises how the project treats the STMicroelectronics files it
> redistributes. The authoritative licence text is `LICENSES/SLA0044.txt`
> (copied verbatim from the STM32CubeH7 distribution). Per-file header notices
> are authoritative. This note is engineering evidence for legal review, not a
> legal conclusion.

## Files provisionally treated as SLA0044

Linked into / redistributed with the FreeRTOS port firmware:

| File | Verbatim copyright | Treatment |
|------|--------------------|-----------|
| `freertos/benchmark_freertos/system/stm32h7xx_it.c` | Copyright (c) 2019 STMicroelectronics. All rights reserved. | SLA0044 (ST "STM32 Projects"); handler bodies configured for this project |
| `freertos/benchmark_freertos/cfg/stm32h7xx_it.h` | Copyright (c) 2019 STMicroelectronics. All rights reserved. | SLA0044 |
| `freertos/benchmark_freertos/cfg/stm32h7xx_hal_conf.h` | Copyright (c) 2019 STMicroelectronics. All rights reserved. | SLA0044; module selection / oscillator values configured |
| `freertos/benchmark_freertos/startup/STM32H750XBHX_FLASH.ld` | Copyright (c) 2022 STMicroelectronics. All rights reserved. | **TBD** — STM32CubeIDE-generated; applicable licence unconfirmed, conservatively treated as SLA0044 |

The `.ld` header itself states only "licensed under terms that can be found in
the LICENSE file in the root directory of this software component"; that LICENSE
file is not identified for a CubeIDE-generated script, so the applicable licence
is undeclared and treated conservatively as SLA0044 until ST or counsel
confirms (it may instead be a BSD-3-Clause "basic example", per the STM32CubeH7
`LICENSE.md` taxonomy).

## Key SLA0044 conditions relevant to publication (see SLA0044.txt for the
## authoritative text)

- Redistribution and use in source and binary forms, with or without
  modification, are permitted subject to the licence conditions.
- Use and execution are permitted only on or with STMicroelectronics devices.
- The ST name/trademarks may not be used for endorsement without permission.
- The software may not be used or redistributed in a way that subjects it to
  any "Open Source Terms" (the licence names GPL/LGPL/MIT/BSD/Apache, etc.).

## Open questions for counsel

These are NOT resolved here; see `legal/SLA0044-QUESTIONS.md`.
