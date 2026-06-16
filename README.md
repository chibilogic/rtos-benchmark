# RTOS Benchmark — ChibiOS vs FreeRTOS vs Zephyr

A neutral, reproducible latency benchmark of three embedded RTOS on
identical hardware (STM32H750B-DK, Cortex-M7 @ 480 MHz), authored by
Chibilogic. Every methodological choice is documented in
`docs/METHODOLOGY.md` and this report, and every reported number is
reproducible and auditable (see **Reproducibility & verification**) from the
source tree at the `phase1-v1.0` tag and the published raw-log archive —
transparency over micro-optimisation.

> **Phase 1 — published at the immutable `phase1-v1.0` tag.** The numbers and
> artifacts are pinned to that tag and its GitHub Release. Validated
> publication host: Windows x86_64; Linux x86_64 is implemented but not yet
> publication-validated.

## Hardware

| Item       | Value                                              |
|------------|----------------------------------------------------|
| Board      | STM32H750B-DK (Discovery Kit)                      |
| MCU        | STM32H750XBH6 (Cortex-M7, silicon rev V required)  |
| CPU clock  | **480 MHz** (PLL1 from HSE 25 MHz, VOS0)           |
| Tick rate  | 1000 Hz                                            |
| Cache      | I+D **ON** (ADR-010)                               |
| Compiler   | arm-none-eabi-gcc 14.2.Rel1, **-O2**, no LTO       |

## RTOS versions

| RTOS     | Version           | Allocation    |
|----------|-------------------|---------------|
| ChibiOS  | 21.11.5 (tag ver21.11.5) | static  |
| FreeRTOS | V11.3.0           | static (configSUPPORT_STATIC_ALLOCATION=1, DYNAMIC=0) |
| Zephyr   | v4.4.0            | static        |

## Cross-RTOS fairness — mandatory identical constraints

These conditions are held IDENTICAL across the three RTOS so the measured
difference reflects the RTOS, not the environment (full rationale in
`docs/METHODOLOGY.md` and the ADRs):

| Constraint   | Value                                                       |
|--------------|-------------------------------------------------------------|
| CPU clock    | 480 MHz (PLL1 from HSE 25 MHz), VOS0, flash WS=4             |
| Caches       | I-Cache + D-Cache ON (ADR-010)                              |
| Tick rate    | 1000 Hz                                                     |
| Compiler     | arm-none-eabi-gcc 14.2.Rel1, -O2 (no -Os/-O3, no LTO)        |
| Measurement  | DWT->CYCCNT (Cortex-M hardware cycle counter)               |
| Markers      | 6 GPIO on STMod+ P1 (see Marker pins), BSRR-direct           |
| NVIC         | TIM2 IRQ at priority 7 on all three ports                   |
| Allocation   | static only — no malloc/free in benchmark code              |
| Output       | USART3 -> ST-Link VCP, 115200 8N1, CSV                      |

Per-RTOS kernel configuration is held at feature parity (kernel options,
hooks, assertions) and checked by `scripts/config_alignment_check.py`; the
per-test primitive mapping is in ADR-014.

## Tests (ADR-014)

| ID  | Test                                | Reference (ChibiOS RT)              |
|-----|-------------------------------------|-------------------------------------|
| T1  | IRQ -> thread wake-up latency       | `chThdSuspendS + chThdResumeI`      |
| T2  | Thread handoff (suspend/resume)     | `rt_test_012_004`                   |
| T3  | Mutex uncontended lock/unlock       | `rt_test_012_011`                   |
| T4  | Mutex contended + priority inheritance | `rt_test_008_002` (one-shot, repeated 100x) |

For each test, the FreeRTOS and Zephyr ports use the closest
semantic equivalent of the ChibiOS primitives. See ADR-014 for
the per-RTOS API mapping.

## Marker pins (ADR-007)

6 GPIO signals on the STMod+ **P1** connector:

| Pin   | P1 # | Role T1                | Role T4                        |
|-------|-----:|------------------------|--------------------------------|
| PA0   |   1  | A0_HW (TIM2 CH1 PWM)   | -                              |
| PH1   |  17  | A1 ISR_ENTRY           | LOW_LOCK                       |
| PH4   |  19  | A2 wake start          | HIGH_WAIT                      |
| PH8   |  20  | A3 wake done (READY)   | LOW_UNLOCK                     |
| PH12  |  11  | A4 thread RUNNING      | HIGH_ACQUIRE                   |
| PI11  |  18  | (unused)               | MEDIUM_RUN (PI proof)          |

PA0 is hardware-driven by TIM2 channel 1 in PWM mode 2 with
CCR1=1 and CC1 IRQ enabled (strada A1, ADR-014). The other 5
are software-driven via direct BSRR writes (~3 cycles per
SET/CLR, identical across the 3 ports).

## Quick start

Reproducible build from a clean clone (Windows x86_64 is the validated
publication host; Linux x86_64 is implemented but not yet
publication-validated; macOS not supported this phase). Toolchain binaries are
NOT in git: they are fetched and checksum-verified per ADR-021.

**Prerequisites (host):** git, Python 3 (3.14.3 on the validated host), GNU
Make, and ~2 GB free disk for the fetched toolchain + Zephyr tree. Building
the host tooling and running the unit suite need neither the ARM toolchain
nor the board; flashing/measurement need the STM32H750B-DK + ST-Link. See
`docs/SETUP.md` §2.

1. Clone:

```sh
git clone <repo> && cd <repo-root>
```

2. One-command setup (~10 min first run; idempotent on re-runs):

```sh
./scripts/setup.sh                                              # Linux
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1    # Windows
```

   The orchestrator runs: `git submodule update` + SSL trust adapter
   (`truststore` on Windows) + toolchain bootstrap (~300 MB
   arm-none-eabi-gcc 14.2.Rel1 + xPack OpenOCD 0.12.0-7 into
   `tools/<platform>/`) + host pipeline deps (in repo-local
   `.venv-host`) + offline test suite + Zephyr venv + `west update`
   (~500 MB-1 GB additional). Flags: `--skip-tests`, `--skip-zephyr`,
   `--check-only` (dry-run). **GNU Make is a host prerequisite**
   (preflight refuses to run if missing). See `docs/SETUP.md` §2.0
   for the full breakdown and manual fallback.

3. Activate venv + toolchain env (shell-export — cannot be automated):

```cmd
.venv-host\Scripts\activate.bat
env.bat
```
```sh
. .venv-host/bin/activate
. ./env.sh
```

4. Build (any/all of the 3 RTOS):

```sh
make -C chibios/benchmark_chibios
make -C freertos/benchmark_freertos PROFILE=fair_perf
make -C zephyr/benchmark_zephyr     PROFILE=fair_perf
```

For flashing + collecting on the board, use the canonical
orchestrators (see `docs/SETUP.md` §6.3): `scripts/lab_smoke.ps1`
/ `scripts/lab_campaign.ps1` on Windows, `scripts/lab_smoke.sh`
/ `scripts/lab_campaign.sh` on Linux. Both call the same
platform-neutral `scripts/lab_runner.py`.

Profiles (ADR-011): `fair_perf`, `realistic_tickless`,
`debug_dev` (dev only, NOT publishable). Flashing and
measurement need the STM32H750B-DK + ST-Link and are a
separate, host-dependent step (see `docs/SETUP.md`).
Host pipeline Python deps (pyserial, matplotlib, reportlab)
are listed in `requirements.txt`; see SETUP §2bis. Toolchain
binaries are NOT committed: `scripts/setup.{sh,ps1}` runs
`scripts/bootstrap_toolchain.py` against `tools/TOOLCHAIN.lock`
(schema v2, SHA-256-pinned). Windows bootstrap is end-to-end
validated; Linux bootstrap is URL+SHA-pinned and archive-inspected
but end-to-end Ubuntu HW validation is pending (ADR-021 patch
set 3c). On Linux you can either let `setup.sh` run the bootstrap
(likely works, treat as unvalidated) or install the 3 binary tools
manually per SETUP §2.

## Run the benchmark

After *Quick start* the firmware is built. Connect the
**STM32H750B-DK** via the ST-Link USB-C port and identify the
serial device (`COM<n>` on Windows, `/dev/ttyACM*` on Linux).

### Smoke test (1 run, ~5 min) - sanity check

Verifies that the toolchain, board, serial, and pipeline all
work together on a single capture. Use a throwaway `RunId 99`:

```cmd
scripts\lab_smoke.ps1 -Rtos chibios -Profile fair_perf -Port COM5 -RunId 99
```
```sh
scripts/lab_smoke.sh --rtos chibios --profile fair_perf --port /dev/ttyACM0 --run-id 99
```

Expected: `=== BENCHMARK COMPLETE ===` + `Smoke completed.` and
exit 0. Artefacts in `results/raw/chibios_fair_perf_run99.*`
(CSV / banner / validated manifest / collector log).

### Publication campaign (~75 min per profile)

Drives the full publication-gated flow: build-once per RTOS,
run00 warmup + run01..run05 per RTOS, ELF/MAP SHA pinning,
publication gate, plots, inventory. Repeat for each profile:

```cmd
scripts\lab_campaign.ps1 -Profile fair_perf          -Port COM5
scripts\lab_campaign.ps1 -Profile realistic_tickless -Port COM5
```
```sh
scripts/lab_campaign.sh --profile fair_perf          --port /dev/ttyACM0
scripts/lab_campaign.sh --profile realistic_tickless --port /dev/ttyACM0
```

Each profile invocation flashes 18 firmware images (3 RTOS *
6 runs) and captures ~33k CSV samples per run. Total wall-clock
~150 min for both profiles.

### Generate the synthesis PDF

After the publication campaign has produced
`results/summary/*` and `results/plots/*`, regenerate the
synthesis report with **your** captured data:

```sh
# 1. (re)generate the publication assets the report consumes:
#    aggregates, firmware-footprint indicators (ADR-023) and the
#    resolved Zephyr Kconfig snapshot (Appendix C).
python scripts/report_results.py --publication-gate --footprint
# 2. render the PDF from those assets.
python scripts/build_report.py
```

This overwrites `docs/Phase1_Benchmark_Report.pdf` — a single,
self-contained PDF (methodology + per-test numbers + cross-RTOS
plots + signed publication-gate manifests). `build_report.py`
takes no arguments but requires the assets produced by the
`report_results.py --footprint` step above. Idempotent: re-run
any time after a fresh campaign to refresh the numbers.

### Publish the raw logs (reviewer item #1)

So an external reviewer can recompute the published medians and verify the
firmware identity, the curated raw-log subset is committed in-repo under
`published-logs/phase1/`, paired with the publication tag:

```sh
python scripts/make_raw_logs_archive.py \
  --source-ref https://github.com/<org>/rtos-benchmark/tree/<tag> \
  --publish-dir published-logs/phase1
```

This whitelists exactly the publishable matrix (3 RTOSes x 2 profiles x
run01..05 + run01 ELF + locks + summary; the `.map` files are not shipped,
their SHA-256 stay in the campaign locks) and fails fast on any missing
or unexpected file. It stages `dist/phase1-raw-logs-<digest>.{tar.gz,zip}`
(gitignored) and copies only the `.zip` + a `.zip.sha256` sidecar into the
tracked `published-logs/phase1/`. Then set `PUBLIC_REPOSITORY_URL` and
`PUBLIC_RAW_LOGS_URL` (immutable tag/commit URLs — never a branch) and
`PUBLICATION_STATUS = "published"` in `scripts/build_report.py`, and
regenerate the PDF for the published state. The
full 828 MB `results/` tree stays gitignored; only the curated ZIP ships.

### Read the results

```text
results/summary/<profile>_aggregate.{md,csv}    cross-RTOS aggregate
                                                 (median across the
                                                 5 publishable runs)
results/summary/<profile>_compare.md             cross-RTOS comparison
results/summary/<rtos>_<profile>_run<NN>_summary.{md,csv}
                                                 per-run details
results/plots/<profile>_<test>_*.png             9 charts per profile
                                                 (aggregate + per-run
                                                 + T4 PI)
```

### Subcommands (for power users)

All four orchestrators are thin wrappers around the same
`scripts/lab_runner.py`:

```sh
python scripts/lab_runner.py --help
# build-only    Build one (rtos, profile); compute SHA; no flash.
# smoke         Build + flash + collect ONE run; optional report/plot.
# campaign      Build-once per RTOS + warmup + run01..05 + gate + plots.
# only-report   Re-run report + plot from existing results/raw (no HW).
```

See `docs/SETUP.md` sections 6-7 for the canonical orchestrators
table, troubleshooting, and the host-vs-Zephyr-venv discipline.

## Running the test suite

The repo carries an offline host test suite (~380 unit tests) that
validates every Python pipeline script and the toolchain bootstrap.
No board, no network, no ARM toolchain required — pure host Python.

```sh
python -m unittest discover -s tests -v
```

Expected: `OK (skipped=3)`. The 3 skips are optional paths that
activate only when matplotlib / pyserial / reportlab are installed
(see `requirements.txt` § 2bis of `docs/SETUP.md`).

There is also a small C unit test that proves `benchmark_stats.c` is
RTOS-agnostic; it builds with any host gcc/clang (no ARM toolchain):

```sh
make -C tests/host
```

## Repository layout

```
rtos-benchmark/
  common/                 RTOS-agnostic code: DWT, stats, banner, CSV
  chibios/                ChibiOS port (submodule + benchmark_chibios/)
  freertos/               FreeRTOS port (submodule + STM32 HAL + benchmark_freertos/)
  zephyr/                 Zephyr workspace (west tree + benchmark_zephyr/)
  docs/                   Published synthesis: METHODOLOGY, SETUP, Phase1 report (PDF)
  scripts/                Python tooling (collect, analyze, report, plot, build_report, bootstrap)
  published-logs/         Curated raw-log publication asset (ZIP + sha256), reviewer item #1
  tools/                  Local toolchain (gcc-arm + make + openocd + Zephyr venv); only TOOLCHAIN.lock committed (ADR-021)
```

## Methodology

The full methodology is in `docs/METHODOLOGY.md` and this report
(`docs/Phase1_Benchmark_Report.pdf`). Highlights:

- **Same hardware, same NVIC priorities, same clocks** across the 3
  ports. TIM2 IRQ is at NVIC priority 7 in all 3 RTOS (ADR-014).
- **DWT->CYCCNT** at 480 MHz is the neutral measurement primitive.
  Every iteration also drives marker GPIO pins so a logic analyzer
  can cross-validate (ADR-015).
- **Statistical methodology** (ADR-013): 1000 warmup + 10000 valid
  iterations per test for T1/T2/T3; 100 one-shot scenarios for T4
  (PI is deterministic). 5 firmware loads minimum per (RTOS x
  profile) before any number is published.
- **Marker overhead** is uniform across the 3 ports (BSRR-direct)
  so any cross-RTOS systematic bias is bounded by GPIO pad / port
  skew, not by software path differences.

## Reproducibility & verification

Every reported number is intended to be auditable from this repo plus the
raw-log archive once the immutable `phase1-v1.0` tag and archive are
published. Note that the **unit tests do NOT regenerate measurements** —
they validate the pipeline scripts on synthetic fixtures; the
per-iteration data comes only from running the firmware on the physical
board. What an external reviewer can check:

1. **Firmware identity.** Rebuild any published image and confirm the
   *loadable firmware image* reproduces byte-for-byte. Build through
   `env.bat` / `env.sh` (the ADR-021 official toolchain) with the
   publication-mode `AUTORUN` (`dwt_only` → `AUTORUN=1`), then compare the
   loadable image (`arm-none-eabi-objcopy -O binary`, SHA-256) to
   `loadable_image_sha256` in `results/manifest/<profile>_campaign.lock.json`
   (`scripts/loadable_image.py --verify`). All six publishable images
   (3 RTOS × 2 profiles) reproduce byte-for-byte from this repository's pinned source tree. The
   `elf_sha256` / `map_sha256` in the lock pin the *originally measured*
   ELF/MAP artifacts; the full ELF additionally hashes DWARF/debug metadata,
   so it may differ after source comment or license-header edits even though
   the executed firmware is identical (ADR-025).
2. **Recompute the medians (no board, no rebuild).** The raw per-iteration
   CSVs and the aggregate tables both ship in the raw-log archive, so the
   published medians can be re-derived end-to-end. After downloading the
   archive and its `.sha256` sidecar from the GitHub Release (or the raw URL
   printed in the report), one command runs the full reviewer check — archive
   checksum, the in-archive `MANIFEST.sha256`, the six firmware ELFs against
   the campaign lock, and the recomputed medians vs the shipped aggregate:

   ```sh
   python scripts/verify_published_archive.py phase1-raw-logs-<digest>.zip
   # -> RESULT: ALL CHECKS PASSED   (exit 0; non-zero on the first failure)
   ```

   It is portable (Python standard library only, no NumPy). The same checks
   by hand:

   ```sh
   sha256sum -c phase1-raw-logs-<digest>.zip.sha256     # archive intact
   unzip phase1-raw-logs-<digest>.zip && cd phase1-raw-logs-<digest>
   awk '{print $1 "  " $2}' MANIFEST.sha256 | sha256sum -c   # payload intact
   python <repo>/scripts/report_results.py \
       --input-dir results/raw --output-dir /tmp/recomputed --profile fair_perf
   diff results/summary/fair_perf_aggregate.csv \
        /tmp/recomputed/fair_perf_aggregate.csv          # medians reproduced
   ```

   `analyze_results.py` / `report_results.py` use the exact sorted-index
   percentile of ADR-013 (no NumPy), so the medians reproduce bit-for-bit.
   (On Windows PowerShell use `Get-FileHash` / `Expand-Archive`.)
3. **Re-measure (optional).** With the board, re-flash the SHA-locked ELF
   and re-run the campaign; `run_spread = 0` across the published runs
   means the per-run medians were bit-identical.

The ChibiOS source is pinned to the named release tag `ver21.11.5`
(= RT 7.0.6); it differs from the prior branch commit only by a
non-compiled SBOM file, so the firmware is byte-identical (ADR-002).

## Status

Phase 1 (DWT-only) — published. The publication campaign passed locally
`report_results.py --publication-gate` on both publishable profiles
(`fair_perf` + `realistic_tickless`): 30/30 runs validated across the 3
RTOS, T4 priority inheritance 3000/3000 scenarios correct,
`run_spread = 0 cycles` on every test/RTOS/profile. All six publishable
loadable firmware images rebuild byte-for-byte from this repository's pinned
source tree (loadable-image identity, ADR-025; see above). The synthesis PDF
`docs/Phase1_Benchmark_Report.pdf` carries the publication-gated numbers.
External hardware-event latency (Mode-LA)
is Phase 2 (ADR-015) — see Roadmap.

## Roadmap (planned)

- **NuttX** — add Apache NuttX as a fourth RTOS in the same
  scenario-equivalent comparison.
- **Phase 2 — logic-analyzer end-to-end T1** (ADR-015): publish the
  external hardware-event → thread latency (`A4 - A0_HW`, captured on the
  STMod+ marker pins) to complement the Phase 1 DWT `A4 - A1` metric.
- **Per-archive footprint breakdown** (ADR-023 `--by-archive`): split the
  code-size indicator into kernel / HAL / libc / application.

The four-test set is frozen for Phase 1; new RTOSes and the
external-latency metric are additive, not a redesign.

## License

The Chibilogic-authored benchmark application code is licensed **per port,
matching the license of the RTOS it runs on** (per-file `SPDX-License-Identifier`
headers are authoritative):
- ChibiOS port — `chibios/benchmark_chibios/` sources: **GPL-3.0-or-later**
  (the pinned ChibiOS RT kernel is GPLv3);
- FreeRTOS port — `freertos/benchmark_freertos/` Chibilogic sources: **MIT**;
- Zephyr port — `zephyr/benchmark_zephyr/` Chibilogic sources: **Apache-2.0**;
- shared `common/` measurement layer: **MIT** (composes with all three ports);
- host tooling `scripts/` and `tests/`: **GPL-3.0-or-later** (not part of any
  firmware).

The top-level `LICENSE` is GPL-3.0-or-later and is the default for Chibilogic
files that carry no other per-file license. Complete license texts are bundled
under `LICENSES/`.

Application-tree files derived from upstream keep their ORIGINAL licenses (NOT
relicensed):
- ChibiOS `cfg/*.h` and `cfg/portab.*` — Apache-2.0 (ChibiOS);
- `cfg/FreeRTOSConfig.h` — MIT (FreeRTOS kernel, Amazon.com);
- FreeRTOS-port `system/system_stm32h7xx.c`, `startup/startup_stm32h750xbhx.s`
  — Apache-2.0 (CMSIS Device, ARM/ST);
- FreeRTOS-port `cfg/stm32h7xx_hal_conf.h`, `cfg/stm32h7xx_it.h`,
  `system/stm32h7xx_it.c` — STMicroelectronics, SLA0044 (STM32CubeH7
  example templates);
- FreeRTOS-port `startup/STM32H750XBHX_FLASH.ld` — STM32CubeIDE linker
  script; treated as SLA0044.

Resulting per-firmware terms: the **ChibiOS** image is a GPLv3 work (it links the
GPLv3 kernel); the **FreeRTOS** image is a combination of its components' terms
(MIT app/kernel, BSD-3 HAL, Apache CMSIS, ST SLA0044) and must be used and
described with the SLA0044 ST-device restriction intact — it is NOT offered as a
single MIT/Apache work; the **Zephyr** image follows Apache-2.0 + per-module
terms. The full RTOS / HAL trees keep their own upstream licenses, mixed
per-component / per-file (ChibiOS: this firmware links the GPLv3 RT kernel —
this pinned build selects `CH_LICENSE_GPL` — and the Apache-2.0 HAL, while the
complete upstream tree also contains components under other terms;
FreeRTOS-Kernel MIT; Zephyr primarily Apache-2.0 with bundled third-party
modules under their own terms, not a pure-Apache tree; STM32 HAL + CMSIS
Apache-2.0 / BSD-3-Clause) and are referenced as git submodules / a west tree.
See `THIRD_PARTY_NOTICES.md`.
