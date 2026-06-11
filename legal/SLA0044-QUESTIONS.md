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

## Reading of the linker-script licence clause (factual; NOT a conclusion)
The `.ld` header (`Copyright (c) 2022 STMicroelectronics. All rights
reserved.`) carries no SPDX tag. It states the licence "can be found in the
LICENSE file in the root directory of this software component" and, failing
that, "it is provided AS-IS". Factual observations only (engineering, not a
legal determination):
- The header points to a component-root LICENSE file that is NOT identified in,
  and does not travel with, the generated file as committed here; the explicit
  fallback in the same clause is AS-IS.
- The plausible originating ST package (STM32CubeH7 / STM32CubeIDE device
  support) ships a root `LICENSE.md` that is a MIXED manifest mapping NAMED
  components to licences — CMSIS Apache-2.0, STM32 HAL BSD-3-Clause, "STM32
  Projects" SLA0044, with a BSD-3-Clause carve-out for basic examples. That
  manifest has no category for a CubeIDE-GENERATED linker script and does not by
  itself identify which row (if any) governs this file.
- The project therefore treats the file PROVISIONALLY as SLA0044 for
  conservative compliance only: the original ST notice is preserved and
  `LICENSES/SLA0044.txt` is bundled and cited in `NOTICE.txt`. Bundling a
  conservative candidate licence text is a PRECAUTION, not evidence that SLA0044
  is the applicable licence, and does not select the upstream licence.
- The applicable treatment — SLA0044, BSD-3-Clause/basic-example, AS-IS, or
  other — remains UNCONFIRMED and is for ST or counsel to determine (Q1).

This engineering note does not treat the `AS-IS` wording alone as an
affirmative redistribution grant; counsel must determine its legal effect.

## Questions for the lawyer (engineering recommendation in italics; NOT a legal
## conclusion)

1. **Linker-script licence.** The `.ld` header references an unidentified
   component-root LICENSE and otherwise states AS-IS (see the reading above).
   Which treatment applies to this CubeIDE-GENERATED linker script: SLA0044
   ("STM32 Projects"), BSD-3-Clause ("basic example" carve-out), AS-IS, or
   other?
   *Keep the original ST notice; comply conservatively with SLA0044 (the
   stricter candidate) WITHOUT asserting it as proven, until ST/counsel
   confirms; if counsel determines the BSD-3 "basic example" carve-out applies,
   the ST-device restriction would not arise from the linker script —
   restrictions applicable to the other SLA0044 portions remain.*

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
