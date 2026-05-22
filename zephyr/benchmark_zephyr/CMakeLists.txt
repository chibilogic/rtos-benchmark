# SPDX-License-Identifier: GPL-3.0-or-later
#
# RTOS Benchmark - Zephyr port build script.
#
# Build profiles (ADR-011):
#   west build -b stm32h750b_dk benchmark_zephyr -d build/fair_perf \
#              --pristine -- -DEXTRA_CONF_FILE=conf/fair_perf.conf
#
#   west build -b stm32h750b_dk benchmark_zephyr -d build/realistic_tickless \
#              --pristine -- -DEXTRA_CONF_FILE=conf/realistic_tickless.conf

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(benchmark_zephyr C)

# ---- Profile -> compile-time macro injection (ADR-011) --------------
if(CONFIG_BENCH_PROFILE_FAIR_PERF)
    set(BENCH_PROFILE_DEFINE BENCH_PROFILE_FAIR_PERF=1)
elseif(CONFIG_BENCH_PROFILE_REALISTIC_TICKLESS)
    set(BENCH_PROFILE_DEFINE BENCH_PROFILE_REALISTIC_TICKLESS=1)
elseif(CONFIG_BENCH_PROFILE_DEBUG_DEV)
    set(BENCH_PROFILE_DEFINE BENCH_PROFILE_DEBUG_DEV=1)
else()
    message(FATAL_ERROR
        "No build profile selected. Pass "
        "-DEXTRA_CONF_FILE=conf/fair_perf.conf, "
        "conf/realistic_tickless.conf or conf/debug_dev.conf "
        "to west build.")
endif()

# ---- Sources --------------------------------------------------------
set(REPO_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../..)

target_sources(app PRIVATE
    src/main.c
    src/test_ctxsw_irq.c
    src/test_thread_handoff.c
    src/test_mutex_uncontended.c
    src/test_mutex_pi.c
    # ADR-024: z_arm_on_enter_cpu_idle() suppresses WFI in idle for
    # fair_perf and debug_dev (parity with ChibiOS / FreeRTOS).
    # Defined unconditionally; referenced by the kernel only when
    # CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK=y.
    src/idle_policy.c
    ${REPO_ROOT}/common/dwt_cycle_counter.c
    ${REPO_ROOT}/common/benchmark_stats.c
    ${REPO_ROOT}/common/bench_button.c)

target_include_directories(app PRIVATE
    src
    ${REPO_ROOT}/common)

target_compile_definitions(app PRIVATE
    BENCH_RTOS_ZEPHYR
    ${BENCH_PROFILE_DEFINE})

# ---- ADR-009 cross-RTOS effective-flag contract ---------------------
# Lab-session bug fix 2026-05-14: Zephyr's default Kconfig + CMake
# flow does NOT pass -fomit-frame-pointer / -falign-functions=16 to
# the application sources. The C3 cflags_audit (cross-RTOS read-back
# of compile_commands.json) flagged this as a real ADR-009 violation
# on Zephyr only - ChibiOS and FreeRTOS already inject the flags via
# UDEFS / add_compile_options. Apply them explicitly here so the
# Zephyr app objects carry the same contract as the other two ports.
# Scoped to the `app` target only (Zephyr kernel / HAL stay
# untouched, which is also what ADR-009 says).
target_compile_options(app PRIVATE
    -fomit-frame-pointer
    -falign-functions=16)

# Optional: skip the B1 button gating between tests (ADR-016).
# Pass -DBENCH_AUTORUN=1 to west build, e.g.:
#     west build -b stm32h750b_dk benchmark_zephyr -p always \
#                -- -DEXTRA_CONF_FILE=conf/fair_perf.conf \
#                   -DBENCH_AUTORUN=1
# Default OFF (publishable flow uses B1 to avoid the LA-arm race).
option(BENCH_AUTORUN "Skip B1 button gating between tests" OFF)
if(BENCH_AUTORUN)
    target_compile_definitions(app PRIVATE BENCH_AUTORUN=1)
endif()
