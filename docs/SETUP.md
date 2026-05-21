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
is committed and unit-tested. The lock is populated (schema v2:
arm-gnu-toolchain 14.2.Rel1 + xPack OpenOCD 0.12.0-7 SHA-256-
pinned for both OSes; GNU Make stays as host prerequisite,
`managed: false`). Windows bootstrap is end-to-end validated;
Linux bootstrap is URL+SHA-pinned and archive-inspected but
the end-to-end clean-Ubuntu run is pending (ADR-021 patch set
3c). The canonical entry point is `scripts/setup.{sh,ps1}`
(see §2.0); manual install per §2 is the fallback. Only
`tools/TOOLCHAIN.lock` is committed.

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

## 2.0 One-command setup (canonical entry point)

`scripts/setup.{sh,ps1}` is a thin wrapper around `scripts/setup.py`
(single source of truth) that runs the full host preparation in one
command. It is idempotent: re-running on a populated tree skips work
already done.

```sh
./scripts/setup.sh                                              # Linux + WSL
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1    # Windows
```

Flags:

| Flag | Effect |
|---|---|
| `--check-only` | dry-run; print planned steps without side-effects |
| `--skip-tests` | omit the ~2 min offline host test suite |
| `--skip-zephyr` | skip Zephyr venv + west init/update (saves ~500 MB-1 GB) |
| `--use-current-python` | skip `.venv-host` creation; use `sys.executable` |

What it does, in order (Codex 2026-05-21-setup-orchestrator-plan-
review-001):

1. **Preflight**: require `git`, `python` (>= 3.10), `make` on PATH.
   GNU Make is a hard prereq because the script's contract is
   "ready to build immediately"; if missing, the error message
   explains per-OS install (see §2).
2. **Submodules**: `git submodule update --init --recursive`.
3. **Host venv**: if already inside a venv or `--use-current-python`,
   use that Python; else create/reuse `.venv-host` at the repo root.
   All subsequent pip and Python invocations use that interpreter.
4. **SSL trust**: if `SSL_CERT_FILE` / `SSL_CERT_DIR` is set in the
   environment, honor it; elif `truststore` is already importable,
   skip; else `pip install truststore` (de-facto standard Windows
   path, see §2bis SSL note).
5. **Toolchain bootstrap**: invoke `scripts/bootstrap_toolchain.py`.
6. **Host pipeline deps**: `pip install -r requirements.txt` into
   the host venv.
7. **Host test suite** (unless `--skip-tests`):
   `python -m unittest discover -s tests` (~2 min, all offline).
8. **Zephyr** (unless `--skip-zephyr`): create `zephyr/.venv`
   (separate from `.venv-host` by design, see §8); pip install west;
   `west init -l benchmark_zephyr`; `west update`. First-time
   `west update` downloads ~500 MB-1 GB of Zephyr modules
   (idempotent after).
9. **Banner**: print the activation + first-build commands.

TLS posture is preserved: no disabled verification, never. See the
`scripts/setup.py` docstring for the full design rationale and the
plan-data structure that the unit tests verify (`tests/test_setup.py`).

The sections below (§2, §2bis, §2ter) document the **manual
fallback** — what each step does under the hood. Use them for
troubleshooting, offline machines, corporate networks that block PyPI
or the Arm CDN, or audits.

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

## 2ter. Host test suite

The repo carries an offline host test suite that validates every
Python pipeline script and the toolchain bootstrap. It is pure
host Python: no board, no network, no ARM toolchain required.

```sh
python -m unittest discover -s tests -v
```

Expected after a fresh install of `requirements.txt`:
`Ran 216 tests in <2 min> OK (skipped=3)`. The 3 skips are
matplotlib / pyserial / reportlab optional paths that activate only
when those packages are installed (they are, after § 2bis).

The C side has a small RTOS-agnosticity unit test for
`common/benchmark_stats.c`. It builds with any host gcc/clang (no
ARM cross-toolchain needed) and is invoked via its own Makefile:

```sh
make -C tests/host
```

This is the same suite that gates every Codex review cycle (see
`notes/ai_handoff/`) and that the ADR-021 toolchain bootstrap
self-validates against. Running both before reporting an issue
helps triage host-pipeline vs firmware regressions.

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
