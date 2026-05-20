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

```sh
git clone <repo> && cd <repo-root>
git submodule update --init --recursive          # ChibiOS/FreeRTOS/HAL
python scripts/bootstrap_toolchain.py            # pinned toolchain (ADR-021)
env.bat              # Windows   (or:  . ./env.sh   on Linux)
# Zephyr sources via west:
cd zephyr && python -m venv .venv
.venv\Scripts\activate.bat   # Windows  (.venv/bin/activate on Linux)
pip install west && west init -l benchmark_zephyr && west update && cd ..
# Build the publishable firmware (per RTOS, default fair_perf):
make -C chibios/benchmark_chibios
make -C freertos/benchmark_freertos PROFILE=fair_perf
make -C zephyr/benchmark_zephyr   PROFILE=fair_perf
```

Profiles (ADR-011): `fair_perf`, `realistic_tickless`,
`debug_dev` (dev only, NOT publishable). Flashing and
measurement need the STM32H750B-DK + ST-Link and are a
separate, host-dependent step (see `docs/SETUP.md`).
Host pipeline Python deps (pyserial, matplotlib, reportlab)
are listed in `requirements.txt`; see SETUP §2bis. Toolchain
binaries are NOT committed: `scripts/bootstrap_toolchain.py`
is committed and unit-tested, but `tools/TOOLCHAIN.lock` is
still placeholder pending ADR-021 patch set 3 (clean
Windows + Linux + network validation). Until then, install
the 3 binary tools manually at the exact versions documented
in SETUP §2 (Arm GNU Toolchain 14.2.Rel1, GNU Make 4.3,
xPack OpenOCD 0.12.0+dev).

## Repository layout

```
rtos-benchmark/
  common/                 RTOS-agnostic code: DWT, stats, banner, CSV
  chibios/                ChibiOS port (submodule + benchmark_chibios/)
  freertos/               FreeRTOS port (submodule + STM32 HAL + benchmark_freertos/)
  zephyr/                 Zephyr workspace (west tree + benchmark_zephyr/)
  notes/                  ADRs (ADR-*), VALIDATION, TODO, WORKLOG, INDEX
  docs/                   Published synthesis: METHODOLOGY, SETUP, Phase1 report (PDF)
  scripts/                Python tooling (collect_results, manifest_from_banner, plot_results)
  reference/              ChibiOS reference test sequences (rt_test_sequence_*.c)
  tools/                  Local toolchain (gcc-arm, msys2, openocd, eclipse, west venv)
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
