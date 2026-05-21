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

### 1. Toolchain auto-bootstrap: Windows operational, Linux pending Ubuntu validation

`scripts/bootstrap_toolchain.py` is operational on **Windows x86_64**:
`python scripts/bootstrap_toolchain.py` downloads, SHA-256-verifies, and
extracts arm-none-eabi-gcc 14.2.Rel1 + xPack OpenOCD 0.12.0-7 into
`tools/windows-x86_64/` (~300 MB download, ~1 GB extracted). The archive
inspection has been recorded in `tools/TOOLCHAIN.lock` (`inspection`
block per entry; symlinks/hardlinks/abs/special counts; SHA cross-check
vs upstream where available).

On Windows the bootstrap requires `truststore` in the host Python
(one-time `python -m pip install truststore`) so that `urllib`
HTTPS validation uses the native Schannel store; CPython stdlib
`ssl` does not consume Schannel by itself. If a corporate CA bundle
is provided via `SSL_CERT_FILE` / `SSL_CERT_DIR`, that takes
precedence and `truststore` is not required. TLS verification is
always enforced — never disabled. See `docs/SETUP.md` section 2.

On **Linux x86_64**, the same archives (arm-gnu-toolchain Linux x86_64
tar.xz + xPack OpenOCD linux-x64 tar.gz) are URL+SHA pinned and
archive-inspected (52 hardlinks in the arm tarball; 4 symlinks in the
openocd tarball; both safe + within-tree), but the end-to-end bootstrap
has not yet been executed on a clean Ubuntu host with ST-Link +
STM32H750B-DK; this is ADR-021 patch set 3c, pending.

**GNU Make is a host prerequisite** on both OSes (bootstrap does not
manage it). On Linux: `sudo apt install make` (or your distro's
equivalent). On Windows: install MSYS2 + `pacman -S
mingw-w64-x86_64-make`, or use the ChibiStudio bundle.

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
