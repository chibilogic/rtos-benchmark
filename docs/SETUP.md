# Setup guide

Procedure to bring the project from zero to "first benchmark run".

## 0. Supported platforms (ADR-021)

| Platform | Build | Flash / collect |
|---|---|---|
| Windows x86_64 | supported | primary supported path |
| Linux x86_64 | supported (build / flash / collect / report) | implemented, publication campaign pending Ubuntu HW validation |
| macOS | not supported this phase | - |

RTOS sources come from git (submodules + west). The ~3 GB
toolchain is NOT committed: `tools/TOOLCHAIN.lock` pins exact
versions + SHA-256, and `scripts/bootstrap_toolchain.py`
is committed and unit-tested. `TOOLCHAIN.lock` is still
placeholder (ADR-021 patch set 3 pending: clean Windows +
Linux + network validation). Meanwhile install the 3 binary
tools (Arm GNU Toolchain 14.2.Rel1, GNU Make 4.3, xPack
OpenOCD 0.12.0+dev) manually under the layout described in
section 2. Only `tools/TOOLCHAIN.lock` is committed.

## 1. Hardware

- **STM32H750B-DK** (Discovery Kit, silicon rev V required for
  480 MHz support). Connect to the host via the ST-Link USB-C
  port. The board enumerates as a USB CDC device (`COMn` on
  Windows, `/dev/ttyACMn` on Linux) used as the CSV output path.
- **Logic analyzer** (Zeroplus LAP-C or any 6-channel >=100 MS/s)
  — only for the future Mode-LA campaign, NOT required for the
  Phase 1 DWT-only flow. Wiring is on the **STMod+ P1** connector
  pins 1, 11, 17, 18, 19, 20 (per ADR-007).
- **VAL-008 prerequisite**: validate that P1 pin 1 follows PA0
  (and not PA15) on this physical board before publishing any
  TEST 1 number. UM2488 documents the pin as `SS/CTS = PA15/PA0`
  selectable via solder bridge.

## 2. Toolchain (ADR-021)

Toolchain binaries are NOT committed (~300 MB total). `tools/TOOLCHAIN.lock`
(committed) pins, per platform, the exact version + official upstream
URL + SHA-256 + archive inspection report for each managed component.

On **Windows x86_64** the bootstrap is fully operational:

```cmd
python scripts\bootstrap_toolchain.py
```

which downloads, SHA-256-verifies, and extracts arm-none-eabi-gcc and
xPack OpenOCD into `tools/windows-x86_64/` (~5 min on a typical
broadband link).

On **Windows** the bootstrap requires the standard Python system-
trust adapter so that `urllib` HTTPS validation uses the native
Schannel store (CPython stdlib `ssl` does not consume Schannel
directly). One-time, ~50 KB:

```cmd
python -m pip install truststore
```

If your organisation provides a custom CA bundle, set
`SSL_CERT_FILE` (PEM file) or `SSL_CERT_DIR` (hashed OpenSSL CA
directory) before running the bootstrap; these are honored on
Windows, Linux, and macOS and take precedence over truststore.
`truststore` is also listed in the host pipeline `requirements.txt`,
so `pip install -r requirements.txt` (section 2bis) also pulls it
in. The bootstrap NEVER disables TLS verification.

On **Linux x86_64** the lock entries are URL+SHA pinned and archive-
inspected (52 hardlinks in arm tar.xz, 4 symlinks in openocd tar.gz,
all safe + within-tree), but end-to-end bootstrap has not yet been
clean-machine validated (ADR-021 patch set 3c pending). Until then,
Linux users can:

- run `python3 scripts/bootstrap_toolchain.py` (will likely work given
  the inspection results, but treat as unvalidated), OR
- install the 3 binary tools manually per the table below.

**GNU Make is a host prerequisite** on both OSes (NOT managed by the
lock; the lock declares it as `managed: false`): on Linux
`sudo apt install make`; on Windows install MSYS2 and
`pacman -S mingw-w64-x86_64-make`, or use the ChibiStudio bundle.

Activate the toolchain for the current shell only (never the system
PATH):

```sh
env.bat            # Windows x86_64
. ./env.sh         # Linux x86_64
```

`env.bat` prefers the `tools/windows-x86_64/` bootstrap layout
and falls back to the legacy `tools/` layout if not bootstrapped
yet, so an already-provisioned machine keeps working.

| Component         | Pinned version              | Managed by                        |
|-------------------|-----------------------------|-----------------------------------|
| arm-none-eabi-gcc | 14.2.Rel1                   | TOOLCHAIN.lock (bootstrap)        |
| GNU Make          | 4.3+                        | host prerequisite (unmanaged)     |
| OpenOCD           | 0.12.0-7 (xPack)            | TOOLCHAIN.lock (hardware flow)    |
| CMake / Ninja     | host prerequisite (>= 3.21) | host (documented, not bundled)    |
| Python + west     | host prerequisite           | host venv (sec. 4), not committed |

Run `env.bat` / `env.sh` from the repository root (no absolute
user paths in committed files).

## 2bis. Host Python prerequisites

The project pipeline scripts (collect / analyze / report / plot /
build_report) need a few non-stdlib packages. Use a host venv
(or your active Python) and install them from `requirements.txt`:

```sh
python -m venv .venv-host
. .venv-host/Scripts/activate     # Windows
# or:  . .venv-host/bin/activate  # Linux
pip install -r requirements.txt
```

This installs `pyserial` (serial collector), `matplotlib`
(plots), and `reportlab` (PDF report). The Zephyr venv is
SEPARATE (see section 4) and has its own
`zephyr/scripts/requirements.txt` — do not mix them; in
particular, when running the post-processing scripts make sure
`python` resolves to the host venv, not to the Zephyr one
(the Zephyr venv does not have matplotlib / reportlab).

## 3. Submodules

```sh
git submodule update --init --recursive
```

The repo carries:
  - `chibios/ChibiOS`            — ChibiOS stable_21.11.x
  - `freertos/FreeRTOS-Kernel`   — FreeRTOS V11.3.0
  - `freertos/stm32_hal`         — STM32CubeH7 v1.12.1 (HAL + CMSIS)
  - `zephyr/zephyr`              — Zephyr v4.4.0 (west-managed)

## 4. Zephyr west tree

### Windows (cmd)
```cmd
cd zephyr
.venv\Scripts\activate.bat
west update
```

If `.venv` does not yet exist:

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install west
west init -l benchmark_zephyr
west update
pip install -r zephyr\scripts\requirements.txt
```

### Linux (bash)
```sh
cd zephyr
. .venv/bin/activate
west update
```

If `.venv` does not yet exist:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install west
west init -l benchmark_zephyr
west update
pip install -r zephyr/scripts/requirements.txt
```

## 5. First build (per RTOS, default profile = `fair_perf`)

The `make -C <dir>` form works from the repository root on both
OSes — no need to `cd` between RTOS dirs.

### Windows (cmd)
```cmd
make -C chibios\benchmark_chibios
REM Output: chibios\benchmark_chibios\build\fair_perf\benchmark_chibios.elf

make -C freertos\benchmark_freertos PROFILE=fair_perf
REM Output: freertos\benchmark_freertos\build\fair_perf\benchmark_freertos.elf

make -C zephyr\benchmark_zephyr     PROFILE=fair_perf
REM Output: zephyr\build\fair_perf\zephyr\zephyr.elf
```

### Linux (bash)
```sh
make -C chibios/benchmark_chibios
# Output: chibios/benchmark_chibios/build/fair_perf/benchmark_chibios.elf

make -C freertos/benchmark_freertos PROFILE=fair_perf
# Output: freertos/benchmark_freertos/build/fair_perf/benchmark_freertos.elf

make -C zephyr/benchmark_zephyr     PROFILE=fair_perf
# Output: zephyr/build/fair_perf/zephyr/zephyr.elf
```

To build the other profiles, replace `fair_perf` with
`realistic_tickless` or `debug_dev`. ADR-011.

## 6. Flash and collect

OpenOCD command for flashing. The `srst_*` reset config is needed
because the firmware-under-flash typically already runs at 480 MHz
and ST-Link cannot SWD-attach without asserting SRST first:

```cmd
openocd -f interface/stlink.cfg -f target/stm32h7x.cfg ^
        -c "reset_config srst_only srst_nogate connect_assert_srst" ^
        -c "program chibios/benchmark_chibios/build/fair_perf/benchmark_chibios.elf verify reset exit"
```

The firmware emits the CSV stream on USART3 / ST-Link VCP at
**115200 8N1**. Capture it with the collector script. The
`--output` argument is a **prefix**, not a file — the script
appends `.csv`, `.t4_pi.csv`, `.banner.txt`, `.stdout.txt`, and
optionally `.map` (with `--map-file`):

```cmd
python scripts\collect_results.py ^
    --port COM<n> ^
    --rtos chibios ^
    --profile fair_perf ^
    --run-id 01 ^
    --output results\raw\chibios_fair_perf_run01 ^
    --map-file chibios\benchmark_chibios\build\fair_perf\benchmark_chibios.map ^
    --timeout 600
```

On Linux x86_64, the same commands with forward-slash paths and
bash line-continuation:

```sh
openocd -f interface/stlink.cfg -f target/stm32h7x.cfg \
        -c "reset_config srst_only srst_nogate connect_assert_srst" \
        -c "program chibios/benchmark_chibios/build/fair_perf/benchmark_chibios.elf verify reset exit"

python3 scripts/collect_results.py \
    --port /dev/ttyACM0 \
    --rtos chibios \
    --profile fair_perf \
    --run-id 01 \
    --output results/raw/chibios_fair_perf_run01 \
    --map-file chibios/benchmark_chibios/build/fair_perf/benchmark_chibios.map \
    --timeout 600
```

`collect_results.py` is **fail-stop**: any of (banner missing,
`BENCHMARK COMPLETE` missing, sequence iterations not 1..N, banner
manifest fields wrong, TIM2 dump not armed, memory placement
violation, `cycles*1e6/clock` mismatch with reported microseconds,
…) makes it exit non-zero with no `.csv` written. The `.stdout.txt`
raw log is always preserved for post-mortem.

For headless / CI captures the firmware can be built with
`-DBENCH_AUTORUN=1` (see `chibios/benchmark_chibios/Makefile`,
`freertos/benchmark_freertos/CMakeLists.txt`,
`zephyr/benchmark_zephyr/CMakeLists.txt`). The default `BENCH_AUTORUN=0`
build gates each test on a USER button (B1, PC13) press+release
to give the operator time to arm the logic analyzer.

### 6.1 Cross-check (optional, recommended)

`analyze_results.py` re-computes the stats offline with the same
sorted-index formula the firmware uses and diffs them against the
`=== Stats for ... ===` blocks captured in the raw log:

```cmd
python scripts\analyze_results.py results\raw\chibios_fair_perf_run01
```

It exits non-zero if any of `n / min / max / jitter / median / p95 /
p99` disagree, or if `mean / stddev` disagree by more than ±1 cycle.

### 6.2 Generate summary tables

After at least one run is captured, `report_results.py` produces
per-run + aggregate + cross-RTOS summary tables under
`results/summary/`:

```cmd
python scripts\report_results.py --profile fair_perf
```

The aggregate is a **median across the N runs** per stat field
(ADR-013 multi-run rule, robust to a single bad run).

### 6.3 Canonical orchestrators (cross-platform)

For the routine flow (build + flash + collect + analyze +
report + plot) prefer the pre-wired orchestrator scripts
instead of stitching the commands above manually. They wrap
`scripts/lab_runner.py` (pure Python, cross-platform).

| Action | Windows | Linux |
|---|---|---|
| Single smoke run | `scripts\lab_smoke.ps1 -Rtos chibios -Profile fair_perf -Port COM5` | `scripts/lab_smoke.sh --rtos chibios --profile fair_perf --port /dev/ttyACM0` |
| Publication campaign | `scripts\lab_campaign.ps1 -Profile fair_perf -Port COM5` | `scripts/lab_campaign.sh --profile fair_perf --port /dev/ttyACM0` |
| Build-only (no HW) | `python scripts\lab_runner.py build-only --rtos chibios --profile fair_perf` | `python3 scripts/lab_runner.py build-only --rtos chibios --profile fair_perf` |
| Re-report only | `python scripts\lab_runner.py only-report --profile fair_perf` | `python3 scripts/lab_runner.py only-report --profile fair_perf` |

All four entry points are thin wrappers around the same
`scripts/lab_runner.py` (pure-Python, cross-platform). The
runner owns the contract on both OSes (run00 warmup, ELF/MAP
SHA-256 lock, `collector-before-reset` ordering,
publication-gate driving); the wrappers only translate
platform-style options to the runner CLI and exec it. The
Windows `.ps1` wrappers were full implementations before
Commit 4 (2026-05-20).

## 7. Lab validation flow

The active campaign is **Phase 1, DWT-only** (no logic analyzer,
no CAL-1; see METHODOLOGY "Publication modes"). The publication
standard requires, per (RTOS x profile):
  - at least 5 fresh firmware loads;
  - every run passing the `collect_results.py` fail-stop gate;
  - the aggregate built by `report_results.py`.

The canonical way to satisfy the standard end-to-end is the
campaign orchestrator (see section 6.3): `lab_campaign.ps1`
on Windows or `lab_campaign.sh` on Linux. Both drive
build-once-per-RTOS, write `results/manifest/<profile>_campaign.lock.json`,
run run00 warmup + run01..run05 per RTOS with ELF/MAP SHA
pinning, then invoke `report_results.py --publication-gate`
and `plot_results.py`. Numbers are NOT publishable until that
gate passes. The
future Mode-LA flow (logic-analyzer capture, CAL-1 pin-skew
calibration) is out of scope for Phase 1.

## 8. Troubleshooting

- **Checksum mismatch** (bootstrap): the upstream artifact
  changed or is corrupt - do NOT bypass; re-download, and if it
  persists report it (the lock pins an exact SHA-256).
- **Upstream URL unavailable**: a pinned URL rotted; report it
  (a documented mirror policy is deferred, ADR-021). Never
  substitute "latest".
- **Missing Python / west**: host prerequisites are not
  bundled; install Python 3.x and create the Zephyr venv
  (sec. 4).
- **ST-Link permissions on Linux**: add the udev rule for the
  ST-Link VID/PID and add your user to the `plugdev` /
  `dialout` group; otherwise OpenOCD and the serial port fail
  without root.
- **Serial device**: Windows `COM<n>` vs Linux
  `/dev/ttyACM*`; pass the right value to
  `collect_results.py --port`.
- **Hardware required**: flash + measurement cannot be
  reproduced without the STM32H750B-DK + ST-Link; the build
  steps are fully reproducible without hardware.
- **`python` resolves to the Zephyr venv**: when `zephyr/.venv`
  is on PATH first (env scripts add it for `west`), `python`
  may resolve to the Zephyr venv which does NOT have
  `matplotlib` / `reportlab`. `plot_results.py` and
  `build_report.py` will fail with `ERROR: missing dependency
  matplotlib` even though `pip install -r requirements.txt`
  succeeded in the host venv. Workaround: invoke them with the
  host venv `python`, or install the host requirements into the
  Zephyr venv too.
