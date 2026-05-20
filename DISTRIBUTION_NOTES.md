# Distribution notes

This package bundles the source of the **RTOS Benchmark on STM32H750B-DK**
project (ChibiOS vs FreeRTOS vs Zephyr) plus its tooling and a gold-reference
synthesis report. Read this file before extracting / building / distributing.

## What you receive

- 95 source / config / script / doc files (this archive).
- Three RTOS source trees are NOT bundled (size and license hygiene); they
  are fetched on-demand:
  - `chibios/ChibiOS` (git submodule, branch `stable_21.11.x`)
  - `freertos/FreeRTOS-Kernel` (git submodule, tag `V11.3.0`)
  - `freertos/stm32_hal` (git submodule, tag `v1.12.1`)
  - `zephyr/zephyr` (west workspace, tag `v4.4.0`)
- The toolchain binaries (~3 GB: arm-none-eabi-gcc, GNU Make, xPack OpenOCD)
  are NOT bundled. See caveat 1 below.

## Quick start (full details in `docs/SETUP.md`)

```sh
git submodule update --init --recursive
. ./env.sh                          # Linux       (or  env.bat  on Windows)
pip install -r requirements.txt     # host Python deps (host venv, NOT Zephyr)
cd zephyr && python3 -m venv .venv && . .venv/bin/activate
pip install west && west init -l benchmark_zephyr && west update && cd ..
make -C chibios/benchmark_chibios
make -C freertos/benchmark_freertos PROFILE=fair_perf
make -C zephyr/benchmark_zephyr     PROFILE=fair_perf
```

For the publication-grade campaign (build-once + run00 warmup + run01..05
per RTOS, with publication gate), use the canonical orchestrator:

```sh
scripts/lab_campaign.sh --profile fair_perf --port /dev/ttyACM0    # Linux
scripts\lab_campaign.ps1 -Profile fair_perf -Port COM5             # Windows
```

## 3 explicit caveats - read before distributing further

### 1. Toolchain auto-bootstrap NOT yet operational

`scripts/bootstrap_toolchain.py` is committed and unit-tested (20 cases),
but `tools/TOOLCHAIN.lock` is still a placeholder (ADR-021 patch set 3
pending: clean-machine archive inspection + URL+SHA-256 population).

**You must install the 3 binary tools manually at the exact versions:**

- arm-none-eabi-gcc 14.2.Rel1 (Arm GNU Toolchain)
- GNU Make 4.3
- xPack OpenOCD 0.12.0+dev

Place them under the layout documented in `docs/SETUP.md` section 2 (or
ensure they are on `PATH` before sourcing `env.bat` / `env.sh`).

### 2. Synthesis report `docs/Phase1_Benchmark_Report.pdf` is DRAFT

The numbers in the PDF are hardware-validated (publication gate passed on
2026-05-20: 30 runs * 3 RTOS * 2 profiles, VAL-007 PI 3000/3000 correct,
run-to-run spread 0 cycles). But the PDF carries an explicit banner:

> *Draft - final legal review required before external publication.*

The draft is suitable for **internal review, NDA-bound partner sharing, and
technical preview**. Do NOT publish externally (web, marketing, comparative
advertising) until legal review is complete.

### 3. Linux pipeline IMPLEMENTED, publication campaign pending Ubuntu HW validation

`scripts/lab_runner.py` is cross-platform; bit-identical ELF SHA-256 has
been confirmed on the Windows path (PowerShell wrapper + direct invocation
+ `-OnlyBuild`). The Linux bash wrappers (`lab_smoke.sh`, `lab_campaign.sh`)
share the same `lab_runner.py` and are syntactically validated, but no
Ubuntu + ST-Link + STM32H750B-DK system has yet physically executed the
campaign. `docs/SETUP.md` section 0 reflects this honestly.

Linux users can build, flash, collect, and report; the cross-target
deterministic GCC build makes byte-identical ELF on both OSes very likely.
But until an Ubuntu host run passes `report_results.py --publication-gate`,
the publication-grade claim is Windows-only.

## Where to go next

- Build / flash / collect / report details: `docs/SETUP.md`
- Methodology, statistics, contractual constraints: `docs/METHODOLOGY.md`
- Per-test RTOS implementation notes: `docs/REPORT_DWT.md`
- Headline numbers + plots + cross-RTOS conclusions:
  `docs/Phase1_Benchmark_Report.pdf`

See `README.md` for the repository contact information.
