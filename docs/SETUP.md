# Setup guide

Procedure to bring the project from zero to "first benchmark run".

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

## 2. Local toolchain

The project pins the toolchain in `tools/`. `env.bat` activates
it for the current shell without touching the system PATH.

| Tool                    | Pinned version         | Path                           |
|-------------------------|------------------------|--------------------------------|
| arm-none-eabi-gcc       | 14.2.Rel1              | `tools/gcc-arm/bin/`           |
| GNU Make                | 4.3 (MSYS2)            | `tools/msys2/usr/bin/`         |
| OpenOCD                 | 0.12.0+dev (xPack)     | `tools/openocd/bin/`           |
| CMake                   | system or 3.21+        | system PATH                    |
| Eclipse + plugins       | optional, IDE only     | `tools/eclipse/`               |
| Zephyr west venv        | west 1.5.0, Python 3.12 | `zephyr/.venv/`                |

```cmd
cd D:\CHIBILOGIC\ChibiOS\rtos-benchmark
env.bat
```

The banner printed by `env.bat` lists the discovered tool
versions; if any line shows `[X]` the tool is missing in `tools/`.

## 3. Submodules

```cmd
git submodule update --init --recursive
```

The repo carries:
  - `chibios/ChibiOS`            — ChibiOS stable_21.11.x
  - `freertos/FreeRTOS-Kernel`   — FreeRTOS V11.3.0
  - `freertos/stm32_hal`         — STM32CubeH7 v1.12.1 (HAL + CMSIS)
  - `zephyr/zephyr`              — Zephyr v4.4.0 (west-managed)

## 4. Zephyr west tree

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

## 5. First build (per RTOS, default profile = `fair_perf`)

```cmd
REM --- ChibiOS ---
cd chibios\benchmark_chibios
make
REM Output: build/fair_perf/benchmark_chibios.elf

REM --- FreeRTOS ---
cd freertos\benchmark_freertos
make PROFILE=fair_perf
REM Output: build/fair_perf/benchmark_freertos.elf

REM --- Zephyr ---
cd zephyr\benchmark_zephyr
make PROFILE=fair_perf
REM Output: zephyr/build/fair_perf/zephyr/zephyr.elf
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

## 7. Lab validation flow

The active campaign is **Phase 1, DWT-only** (no logic analyzer,
no CAL-1; see METHODOLOGY "Publication modes"). The publication
standard requires, per (RTOS x profile):
  - at least 5 fresh firmware loads;
  - every run passing the `collect_results.py` fail-stop gate;
  - the aggregate built by `report_results.py`.

Numbers are NOT publishable until that standard is met. The
future Mode-LA flow (logic-analyzer capture, CAL-1 pin-skew
calibration) is out of scope for Phase 1.
