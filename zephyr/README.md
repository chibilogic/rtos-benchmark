# Benchmark Zephyr

Zephyr RTOS port of the RTOS benchmark on STM32H750B-DK at 480 MHz.

## Setup

Zephyr uses **west** as workspace manager, NOT git submodules.

```cmd
cd zephyr
python -m venv .venv
.venv\Scripts\activate.bat
pip install west

REM Initialise the workspace pointing at our project manifest
west init -l benchmark_zephyr

REM Pull Zephyr and all modules (HAL, CMSIS, ...)
west update

REM Install Zephyr's Python requirements
pip install -r zephyr\scripts\requirements.txt
```

We use the local arm-none-eabi-gcc 14.2.Rel1 toolchain via
`ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb` (set by `env.bat`); no
Zephyr SDK is needed.

## Build

```cmd
cd benchmark_zephyr
make PROFILE=fair_perf
```

The Makefile wrapper invokes `west build -b stm32h750b_dk
benchmark_zephyr -d ../build/<profile> -- -DEXTRA_CONF_FILE=
conf/<profile>.conf`. The first invocation auto-runs `make
configure`; subsequent calls do incremental builds. Other
profiles: `realistic_tickless`, `debug_dev`.

Output: `zephyr/build/<profile>/zephyr/zephyr.elf`.

## Flash

```cmd
west flash --build-dir build/fair_perf
REM or manually
openocd -f interface/stlink.cfg -f target/stm32h7x.cfg ^
        -c "program build/fair_perf/zephyr/zephyr.elf verify reset exit"
```

## UART

Same as the other ports: USART3 -> ST-Link VCP at 115200 8N1.
Capture with `scripts/collect_results.py`.

## Zephyr-specific notes

- Device tree overlay: `benchmark_zephyr/boards/stm32h750b_dk.overlay`.
  Declares 5 GPIO aliases for the software-driven markers.
- **TIM2 is NOT bound to any Zephyr driver**: the counter
  driver is OFF in `prj.conf` (`CONFIG_COUNTER` disabled), so
  the TIM2 IRQ vector is free for our `IRQ_CONNECT(TIM2_IRQn,
  7, ...)` at file scope in `src/test_ctxsw_irq.c`.
- I+D cache enable is idempotent: Zephyr's SoC layer may
  already have enabled the cache by the time `main()` runs;
  `cache_enable()` checks `SCB->CCR` first.
- Main thread priority overridden to 6 via
  `CONFIG_MAIN_THREAD_PRIORITY=6`. This is required so test
  threads (target=1 for T2, etc.) can preempt main, since
  Zephyr's default main is at priority 0 (highest preemptible).
- TEST 4 elevates the runner to priority 2 for the duration of
  the 100 one-shot scenarios, then restores to 6.
- Zephyr priority numbering: numerically LOWER = HIGHER
  priority (opposite of ChibiOS / FreeRTOS).
- All benchmark allocations are static
  (`K_THREAD_STACK_DEFINE`, `struct k_thread/sem/mutex`).
  The Zephyr kernel heap pool (`CONFIG_HEAP_MEM_POOL_SIZE`)
  remains configured for kernel/driver convenience but is
  not exercised by the measured path.

For the full methodology see `docs/METHODOLOGY.md` at the repo root.
