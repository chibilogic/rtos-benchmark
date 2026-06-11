# Gate C — Legal Review Packet (Phase 1)

Status: READY_FOR_LEGAL_REVIEW — NOT APPROVED / NOT LEGAL SIGN-OFF
Repository: chibilogic/rtos-benchmark, branch `develop` (commit = git HEAD at
review time; full provenance via `scripts/release_manifest.py`)
Publication tag: `phase1-v1.0` — NOT yet created (no public GitHub Release yet)
Raw-log archive: `published-logs/phase1/phase1-raw-logs-<digest>.zip` (+ `.sha256`)
PDF report: `docs/Phase1_Benchmark_Report.pdf` (PUBLICATION_STATUS = draft)
Date: <fill at review submission>

## 1. Scope
This packet covers the Phase 1 benchmark artefacts only: six publishable ELF
firmware images, their per-run map files, raw logs, SHA-256 manifests, source
references, and the third-party component inventory. It is engineering evidence
prepared for legal review; it is NOT a legal conclusion or sign-off.

## 2. Engineering evidence
- Six publishable ELFs:
  `{chibios,freertos,zephyr}_{fair_perf,realistic_tickless}_run01.elf`
- Per-ELF map files (`results/raw/*_run01.map`) — linked-object source of truth
- Raw logs + `*.validated.json` + SHA-256 manifests (campaign locks, ADR-025)
- Source provenance: root + submodule commits + 68 west projects
  (`scripts/release_manifest.py`)
- Third-party inventory: `THIRD_PARTY_NOTICES.md` (intro) + this packet

## 3. Licence matrix (per-ELF)
See `legal/NOTICE-INVENTORY-phase1.md` for the full per-ELF matrix with
normalised copyright notices, notice actions and status (OK / LEGAL_REVIEW /
TBD). Summary:
- ChibiOS ELFs: GPLv3 (kernel) + Apache-2.0 (HAL) + Chibilogic GPL/MIT.
- FreeRTOS ELFs: MIT (app/common/kernel) + BSD-3-Clause (HAL) + Apache-2.0
  (CMSIS) + SLA0044 (ST files) + TBD (`.ld`).
- Zephyr ELFs: Apache-2.0 + per-module + BSD-3-Clause/Apache-2.0 (HAL) + MIT
  (common).

## 4. ST / SLA0044 open questions
See `legal/SLA0044-QUESTIONS.md` (5 questions: `.ld` licence; GPL repo +
SLA0044; public ELF redistribution; per-ELF notice wording; SLA0044 condition 5;
plus condition 4 ST-device-only). References: `LICENSES/ST-SLA0044-reference.md`,
`LICENSES/SLA0044.txt`.

## 5. Apache NOTICE handling
Apache-2.0 components (ChibiOS cfg/HAL, CMSIS Device, Zephyr): `LICENSES/
Apache-2.0.txt` is shipped. CURRENT modified-file-notice status: only
`system/stm32h7xx_it.c` carries an explicit "configured/modified for this
project" note today; the other configured/modified files (`FreeRTOSConfig.h`,
`system_stm32h7xx.c`, `stm32h7xx_hal_conf.h`, ChibiOS `cfg/*`, Zephyr `conf/*`)
retain their upstream copyright but do NOT currently carry such a note. Whether
an Apache/MIT modified-file notice must be ADDED to those upstream-owned files
(and which) is a counsel/policy decision (see legal decisions requested) -- they
are NOT modified here without sign-off. Per-file Apache attribution for the
linked Zephyr objects is flagged LEGAL_REVIEW. Apache-2.0 does not license
trademarks.

## 6. MIT / FreeRTOS handling
`LICENSES/MIT-FreeRTOS.txt` now reproduces the copyright notices actually
present in the linked FreeRTOS sources (whitespace/line breaks normalised):
Amazon (2017 and 2021) and Arm (2026).
The Chibilogic MIT code (`common/`, FreeRTOS-port app) uses `LICENSES/MIT.txt`.

## 7. Comparative claims
See `legal/CLAIMS-POLICY.md` (allowed / forbidden / strictly-forbidden). The
repository public content conforms; external marketing copy requires
counsel/marketing approval scoped to board / version / profile / metric.

## 8. Legal decisions requested (counsel)
1. `.ld` applicable licence (SLA0044 / BSD-3-Clause basic-example / AS-IS / other).
2. SLA0044 condition 5 compatibility with the GPL/MIT/Apache/BSD repository.
3. Public redistribution of the FreeRTOS ELFs embedding SLA0044 object code.
4. Exact per-ELF NOTICE wording.
5. Approved comparative claims for external material.
6. Whether the toolchain-runtime (newlib/picolibc/libgcc) copyrights must be
   reproduced in addition to the disclaimer.

## Residual (NOT part of legal sign-off; Gate D / release)
- Create the `phase1-v1.0` tag + GitHub Release; fill the immutable URLs; flip
  `PUBLICATION_STATUS` to published; regenerate ZIP/PDF once.
- Run `scripts/release_gate.py` (git tag + GitHub Release exist; raw ZIP
  downloads and its sha256 == the committed sidecar; the published README names
  the ZIP; build_report PUBLICATION_STATUS == published + immutable URLs set).
- Validate a clean-venv install + report build from the publication dependency
  lock (`requirements.lock`).

READY FOR LEGAL REVIEW — NOT LEGAL SIGN-OFF.
