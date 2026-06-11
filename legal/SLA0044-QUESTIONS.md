# SLA0044 / linker-script — questions for counsel

> READY FOR LEGAL REVIEW — NOT LEGAL SIGN-OFF.

## Context
The FreeRTOS-port firmware links a small number of STMicroelectronics "STM32
Projects" files provisionally treated as SLA0044 (see
`LICENSES/ST-SLA0044-reference.md`; authoritative text in
`LICENSES/SLA0044.txt`). The top-level repository licence is GPL-3.0-or-later;
per-port Chibilogic application code is GPL (ChibiOS) / MIT (FreeRTOS) /
Apache-2.0 (Zephyr); upstream components keep their own licences. The six
publishable ELFs are redistributed in the raw-log archive.

## Questions for the lawyer (engineering recommendation in italics; NOT a legal
## conclusion)

1. **Linker-script licence.** Is `STM32H750XBHX_FLASH.ld` (STM32CubeIDE-generated,
   `Copyright (c) 2022 STMicroelectronics`) SLA0044, BSD-3-Clause ("basic
   example" per the STM32CubeH7 `LICENSE.md` taxonomy), AS-IS, or other?
   *Keep the original ST notice; comply conservatively with SLA0044 without
   asserting it as proven until ST/counsel confirms.*

2. **GPL repo + SLA0044 files.** Is publicly distributing this repository
   (top-level GPL-3.0) while it contains SLA0044 files compatible, given the
   FreeRTOS-port Chibilogic code is MIT (permissive, no copyleft over the ST
   portions)?
   *Approve if per-component terms do not subject the ST software to Open Source
   Terms; do NOT relabel/relicense the ST files.*

3. **Public redistribution of the FreeRTOS ELFs.** May the prebuilt FreeRTOS ELFs
   that embed SLA0044-derived object code be distributed publicly as benchmark
   artefacts, with the ST-device-only restriction stated?
   *Approve subject to all SLA0044 conditions (the licence grants source + binary
   redistribution); keep the ST-device-only restriction prominent.*

4. **Notice wording per ELF.** What exact copyright / licence / attribution /
   modification / disclaimer / source-access notices must accompany each of the
   six ELFs? (Draft in `legal/NOTICE-INVENTORY-phase1.md`.)
   *Require a counsel-approved per-ELF notice; ship all complete licence texts +
   a verified immutable Corresponding-Source URL.*

5. **SLA0044 condition 5.** Does the presence of MIT/Apache/BSD/GPL in the same
   repository risk triggering SLA0044 condition 5 (no "Open Source Terms")?
   *Approve if counsel agrees that combining separately licensed portions in one
   repository/firmware does not "subject" the ST software to those terms
   (permissive components carry no whole-work copyleft).*

## Condition 4 — ST-device-only
The benchmark targets an STM32H750 (an ST device); the notices state that the
ELFs embedding ST portions are for use/execution on ST devices only. Counsel to
confirm whether a public download breaches condition 4, or only non-ST-device
use/execution.

This is engineering evidence for legal review. Do NOT treat the recommendations
as a legal conclusion.

READY FOR LEGAL REVIEW — NOT LEGAL SIGN-OFF.
