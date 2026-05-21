# RTOS Benchmark — ChibiOS vs FreeRTOS vs Zephyr

Comparison of three embedded RTOS on identical hardware,
designed as a marketing demo for Chibilogic. Every methodological
choice is documented in `notes/ADR-*.md` and is intentionally
biased towards transparency over micro-optimisation.

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
| ChibiOS  | stable_21.11.x    | static        |
| FreeRTOS | V11.3.0           | static (configSUPPORT_STATIC_ALLOCATION=1, DYNAMIC=0) |
| Zephyr   | v4.4.0            | static        |

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

Reproducible build from a clean clone (Windows x86_64 or Linux
x86_64; macOS not supported this phase). Toolchain binaries are
NOT in git: they are fetched and checksum-verified per ADR-021.

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

After step 6 of *Quick start* the firmware is built. Connect the
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

To regenerate the synthesis PDF with **your** captured data
(overwrites `docs/Phase1_Benchmark_Report.pdf`):

```sh
python scripts/build_report.py
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

The repo carries an offline host test suite (~216 unit tests) that
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
  notes/                  ADRs (ADR-*), VALIDATION, TODO, WORKLOG, INDEX
  docs/                   Published synthesis: METHODOLOGY, SETUP, Phase1 report (PDF)
  scripts/                Python tooling (collect, analyze, report, plot, build_report, bootstrap)
  reference/              ChibiOS reference test sequences (rt_test_sequence_*.c)
  tools/                  Local toolchain (gcc-arm + make + openocd + Zephyr venv); only TOOLCHAIN.lock committed (ADR-021)
```

## Methodology

The full methodology lives in `notes/ADR-*.md` (read `notes/INDEX.md`
for the index). Highlights:

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

## Status

Phase 1 (DWT-only) HW-validated 2026-05-20: official campaign
passed `report_results.py --publication-gate` on both publishable
profiles (`fair_perf` + `realistic_tickless`), 30/30 runs
validated across the 3 RTOS, VAL-007 PI = 3000/3000 scenarios
correct, `run_spread = 0 cycles` on every test/RTOS/profile.
The synthesis PDF `docs/Phase1_Benchmark_Report.pdf` carries
the publication-gated numbers but is still marked **draft**
pending final legal review before external distribution.
Mode-LA items (VAL-002 / VAL-004 / VAL-005 / VAL-006) belong
to Phase 2 and are not required for Phase 1.
