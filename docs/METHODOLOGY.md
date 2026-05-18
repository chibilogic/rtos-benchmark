# Benchmark methodology

> Reference document for the equivalence criteria, measurement
> choices and limits of the comparison. Read this before
> interpreting or presenting any number from the benchmark.

This document is a high-level summary; the authoritative source is
the ADR set in `notes/ADR-001..015.md`. When a discrepancy arises,
the ADR wins.

## Guiding principle

> The measurement conditions must be **physically identical** for
> all 3 RTOS. Any difference in the published numbers must be
> attributable ONLY to the RTOS, not to differences in the setup.

## Identical-by-construction constraints

| Aspect                  | Value                          | ADR     |
|-------------------------|--------------------------------|---------|
| Board                   | STM32H750B-DK                  | ADR-001 |
| MCU                     | STM32H750XBH6 (Cortex-M7 r0p1) | ADR-001 |
| HSE                     | 25 MHz crystal X1              | ADR-001 |
| SYSCLK                  | **480 MHz** (PLL1, VOS0)       | ADR-006 / ADR-008 |
| Flash latency           | WS = 4                         | ADR-006 |
| I-Cache                 | **ON**                         | ADR-010 |
| D-Cache                 | **ON**                         | ADR-010 |
| Tick rate               | 1000 Hz                        | ADR-009 |
| Compiler                | arm-none-eabi-gcc 14.2.Rel1    | ADR-001 |
| Compiler flags          | **-O2**, no -Os, no -O3, no LTO | ADR-009 |
| FPU                     | hard, fpv5-d16                 | ADR-001 |
| Mutex with PI           | ON in all 3 RTOS               | ADR-014 |
| TIM2 IRQ NVIC priority  | **7** (uniform)                | ADR-014 |
| Marker SW path          | direct BSRR (uniform 3 cycles) | ADR-007 |
| Memory allocation       | Benchmark application code is fully static (no `malloc`/`free`). RTOS heap subsystems may remain configured but are not exercised by the measured path. | ADR-009 (FreeRTOS goes further: `configSUPPORT_DYNAMIC_ALLOCATION=0`) |

Three build profiles are produced (ADR-011):

  - `fair_perf`           : tickless OFF, no WFI in idle, "fastest possible"
  - `realistic_tickless`  : tickless ON, WFI in idle, real-world
  - `debug_dev`           : -Og -g3, NOT publishable (banner warns)

## Measurement primitive

### DWT->CYCCNT

The Cortex-M `DWT->CYCCNT` register increments once per CPU clock,
independently of any RTOS scheduler. At 480 MHz the resolution is
~2.08 ns. The 32-bit counter wraps every ~9 s, which is far longer
than any per-iteration interval in this benchmark. ADR-004.

### Publication modes (ADR-015)

The benchmark supports two publication modes; each run's
`publication_mode` field in `*.validated.json` declares which
mode applies, and the report-side gate enforces homogeneity
across the 5+ runs that make up a campaign.

- **Phase 1 — DWT-only** (active per user decision 2026-05-12).
  DWT is the sole source for all four tests. TEST 1 headline is
  `A4 - A1` (`ISR_ENTRY -> THREAD_RUNNING`,
  metric `dwt_a4_minus_a1`); the hardware-event-to-ISR-entry
  component is EXCLUDED. TEST 4 latency is a DWT accessory
  microbenchmark; the primary T4 result is the `pi_ok` boolean.
  No LA capture is required.

- **Mode LA — future scope.** Marker GPIOs are captured by an
  external logic analyzer with sub-ns timestamps. TEST 1
  headline becomes `A4 - A0_HW`; TEST 4 has the LA-confirmed PI
  window; DWT figures are carried as software validation. CAL-1
  cross-port calibration (`docs/lab_measurement_flow.md`) is
  required before any Mode LA campaign.

| Test | Source (Phase 1) | Headline (Phase 1)        | Source (Mode LA) | Headline (Mode LA)         |
|------|------------------|---------------------------|------------------|----------------------------|
| T1   | DWT              | `A4 - A1`                 | LA               | `A4 - A0_HW`               |
| T2   | DWT              | t_resume -> t_run         | DWT              | t_resume -> t_run          |
| T3   | DWT              | lock+unlock pair          | DWT              | lock+unlock pair           |
| T4   | DWT + PI         | `pi_ok` + DWT handoff     | LA + PI          | `pi_ok` + LA mutex handoff |

CSV column `metric` (added round-5) makes explicit which metric
each row represents. CSV column `source` carries the resolved
per-mode tag emitted by `scripts/report_results.py` (see
`SOURCE_BY_TEST_BY_MODE`).

## Tests (ADR-014)

### T1 — IRQ -> thread wake-up latency

**What**: time from a hardware compare event (TIM2 CH1 PWM mode 2,
PA0 rising edge) to the high-priority thread reaching its first
post-resume instruction.

**Implementation**: TIM2 PSC=239, ARR=999, CCR1=1, PWM mode 2,
CC1 IRQ at NVIC priority 7. The PWM rising edge at `CNT == CCR1`
sets PA0 (= A0_HW) AND raises the CC1 IRQ in the same cycle, so
the LA reference and the IRQ entry derive from one event.

**Headline (Phase 1, DWT-only)**: `A4 - A1`
(`ISR_ENTRY -> THREAD_RUNNING`, metric `dwt_a4_minus_a1`,
source `DWT`). HW-event-to-ISR-entry component EXCLUDED.

**Headline (Mode LA, future)**: `A4 - A0_HW` (HW compare event
-> thread RUNNING, source `LA`). The DWT figure (`A4 - A1`) is
then carried as software validation. LA falling edge of PA0 is
the PWM update event and MUST be filtered out by the LA parser.

### T2 — Thread handoff latency

**What**: cost of a high-priority thread resuming via the RTOS's
suspend/resume primitive.

**Cross-RTOS mapping**:
  - ChibiOS: `chSchGoSleepS(CH_STATE_SUSPENDED)` / `chSchWakeupS`
  - FreeRTOS: `vTaskSuspend(NULL)` / `vTaskResume(handle)`
  - Zephyr: `k_thread_suspend(self)` / `k_thread_resume(tid)`

DWT primary, single PH1 marker pulse around the measured region.
Target priority above runner; `target_ready` handshake before the
loop ensures the target reached its first suspend.

### T3 — Mutex uncontended

**What**: cost of one `lock + unlock` pair on a free mutex,
single thread.

**Cross-RTOS mapping**:
  - ChibiOS: `chMtxLock` / `chMtxUnlock`
  - FreeRTOS: `xSemaphoreCreateMutexStatic` + `Take` / `Give`
  - Zephyr: `k_mutex_lock` / `k_mutex_unlock`

DWT primary. Each sample includes ONE pair of `dwt_get_cycles()`
reads (~3 cycles); the firmware does NOT subtract this overhead
(the banner reports the calibrated value, the post-processor can
choose). ADR-013.

### T4 — Mutex contended + Priority Inheritance

**What**: behavioural test based on ChibiOS `rt_test_008_002`
(8.2 "Priority inheritance, simple case"), repeated 100 times
per firmware load.

Three autonomous threads with precise sleep offsets:
```
L (low):  lock(mtx), busy 40 ms (CPU), unlock, busy 10 ms, emit 'C'
M (mid):  sleep 20 ms, busy 40 ms (CPU) pulsing MEDIUM_RUN, emit 'B'
H (high): sleep 40 ms, lock(mtx) -> blocks (PI fires), busy 10 ms,
          unlock, emit 'A'
```

**Headline (correctness)**:
  - `pi_ok` per run = (sequence == "ABC") ? 1 : 0
  - `MEDIUM_RUN` flat in the **PI proof window** `[HIGH_WAIT,
    LOW_UNLOCK]` (when L holds the mutex with PI-boosted priority
    and M is ready but trapped). Any pulse = PI failed.

**Accessory (microbenchmark)**:
  - **Phase 1 (DWT-only)**: `dwt(t_unlock, t_acquire)` is the
    accessory handoff microbenchmark (mutex handoff cost),
    source tag `DWT`. Reported alongside `pi_ok`; does NOT
    replace an LA measurement of the same window.
  - **Mode LA (future)**: `LOW_UNLOCK -> HIGH_ACQUIRE` LA delta
    becomes the accessory handoff number; DWT is carried as
    software validation.

T4 is exempt from the warmup/valid scheme of T1/T2/T3 (PI is
deterministic, not statistical). ADR-013 carve-out.

## Statistical methodology (T1/T2/T3)

  - 1000 warmup iterations (discarded -- cache cold start, UART
    settling).
  - 10000 valid iterations -> min / median / mean / p95 / p99 /
    max / jitter / stddev. ADR-013.
  - **At least 5 firmware loads** per (RTOS x profile) before any
    number is published. Each loading is a fresh power-cycle; the
    aggregate statistic is computed across the 5+ runs.

## What we do NOT measure

| Not measured            | Why                                      |
|-------------------------|------------------------------------------|
| Memory / RAM footprint  | Different topic, separate report         |
| Throughput msg/s        | T1/T2 already capture context-switch cost|
| Power consumption       | Needs PPK2 or equivalent                 |
| Boot time               | Not representative of run-time           |
| Scheduling overhead %   | Hard to compare apples-to-apples         |

## Stated limits

1. **One board, one MCU**. Numbers do not auto-transfer to STM32F4,
   STM32G4, nRF52, etc.
2. **"Reasonable defaults"**, not maximum-tuning. Each RTOS can be
   pushed further by an expert; we did not.
3. **Cache ON** is realistic; cache OFF would isolate scheduling
   cost more cleanly but is not what users run in production
   (ADR-010 supersedes the earlier cache-OFF plan).
4. **Synthetic micro-tests**. Real applications mix all four
   patterns plus much more. The numbers are indicative.
5. **Specific versions**: ChibiOS stable_21.11.x, FreeRTOS V11.3.0,
   Zephyr v4.4.0. Future versions may shift numbers.

## Reproducibility

Everything required to reproduce the published numbers:

  - Code: this repo (all 3 ports, common, scripts).
  - Toolchain: pinned in `tools/` (gcc 14.2.Rel1, msys2 make,
    openocd, west venv).
  - Configuration: per-RTOS config files (`chconf.h`,
    `FreeRTOSConfig.h`, `prj.conf` + per-profile overrides).
  - Boot banner: dumps RCC/PWR/FLASH/SCB->CCR/TIM2 register state
    at runtime so each captured CSV is self-describing.
  - Per-run manifest: `scripts/manifest_from_banner.py` parses the
    banner into a JSON manifest. Each published CSV has a paired
    manifest.
  - 5+ runs per (RTOS x profile) per the publication standard.

A future operator with this repo, the toolchain, and the board
should be able to reproduce within the natural statistical
variance documented in the lab session results.
