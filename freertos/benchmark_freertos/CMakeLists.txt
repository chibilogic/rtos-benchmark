# SPDX-License-Identifier: MIT
#
# RTOS Benchmark - FreeRTOS port build script.
#
# Build profiles (ADR-011):
#   cmake -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake \
#         -DBENCH_PROFILE=fair_perf -B build/fair_perf
#   cmake --build build/fair_perf
#
#   cmake -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake \
#         -DBENCH_PROFILE=realistic_tickless -B build/realistic_tickless
#   cmake --build build/realistic_tickless

cmake_minimum_required(VERSION 3.20)

# Export compile_commands.json for the ADR-009 effective-flag
# audit (scripts/cflags_audit.py --rtos freertos). Required so
# the post-build audit can read the exact GCC invocations cmake
# generated. No effect on the produced ELF/MAP.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ---- Profile selection (ADR-011) ----
if(NOT DEFINED BENCH_PROFILE)
    set(BENCH_PROFILE "fair_perf" CACHE STRING "Build profile")
endif()
if(BENCH_PROFILE STREQUAL "fair_perf")
    set(BENCH_PROFILE_DEFINE BENCH_PROFILE_FAIR_PERF=1)
    set(BENCH_OPT_LEVEL "-O2")
elseif(BENCH_PROFILE STREQUAL "realistic_tickless")
    set(BENCH_PROFILE_DEFINE BENCH_PROFILE_REALISTIC_TICKLESS=1)
    set(BENCH_OPT_LEVEL "-O2")
elseif(BENCH_PROFILE STREQUAL "debug_dev")
    # Development-only profile, NOT for publication.
    set(BENCH_PROFILE_DEFINE BENCH_PROFILE_DEBUG_DEV=1)
    set(BENCH_OPT_LEVEL "-Og")
else()
    message(FATAL_ERROR
        "Unknown BENCH_PROFILE '${BENCH_PROFILE}'. "
        "Use: fair_perf | realistic_tickless | debug_dev")
endif()

project(benchmark_freertos C ASM)

# ---- Repo paths ----
set(REPO_ROOT       ${CMAKE_CURRENT_SOURCE_DIR}/../..)
set(COMMON_DIR      ${REPO_ROOT}/common)
set(FREERTOS_DIR    ${REPO_ROOT}/freertos)
set(KERNEL_DIR      ${FREERTOS_DIR}/FreeRTOS-Kernel)
set(HAL_DIR         ${FREERTOS_DIR}/stm32_hal/Drivers/STM32H7xx_HAL_Driver)
set(CMSIS_DEV_DIR   ${FREERTOS_DIR}/stm32_hal/Drivers/CMSIS/Device/ST/STM32H7xx)
set(CMSIS_CORE_DIR  ${FREERTOS_DIR}/stm32_hal/Drivers/CMSIS/Core)

# ---- Common compile / link flags (ADR-009) ----
set(CPU_FLAGS
    -mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard)
if(BENCH_PROFILE STREQUAL "debug_dev")
    set(COMMON_FLAGS
        ${CPU_FLAGS}
        ${BENCH_OPT_LEVEL} -g3
        -ffunction-sections -fdata-sections
        -fno-common -fno-strict-aliasing
        -Wall -Wextra)
else()
    set(COMMON_FLAGS
        ${CPU_FLAGS}
        ${BENCH_OPT_LEVEL} -ggdb
        -fomit-frame-pointer -falign-functions=16
        -ffunction-sections -fdata-sections
        -fno-common -fno-strict-aliasing
        -Wall -Wextra)
endif()

add_compile_options(${COMMON_FLAGS})
add_compile_definitions(
    STM32H750xx
    USE_HAL_DRIVER
    BENCH_RTOS_FREERTOS
    ${BENCH_PROFILE_DEFINE})

# Optional: skip the B1 button gating between tests (ADR-016).
# Pass -DBENCH_AUTORUN=1 to cmake, e.g.:
#     cmake -B build -G "MinGW Makefiles" \
#           -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake \
#           -DBENCH_AUTORUN=1
# Default OFF (publishable flow uses B1 to avoid the LA-arm race).
option(BENCH_AUTORUN "Skip B1 button gating between tests" OFF)
if(BENCH_AUTORUN)
    add_compile_definitions(BENCH_AUTORUN=1)
endif()

# ---- HAL drivers list (only what we actually use) ----
set(HAL_SRCS
    ${HAL_DIR}/Src/stm32h7xx_hal.c
    ${HAL_DIR}/Src/stm32h7xx_hal_cortex.c
    ${HAL_DIR}/Src/stm32h7xx_hal_pwr.c
    ${HAL_DIR}/Src/stm32h7xx_hal_pwr_ex.c
    ${HAL_DIR}/Src/stm32h7xx_hal_rcc.c
    ${HAL_DIR}/Src/stm32h7xx_hal_rcc_ex.c
    ${HAL_DIR}/Src/stm32h7xx_hal_gpio.c
    ${HAL_DIR}/Src/stm32h7xx_hal_uart.c
    ${HAL_DIR}/Src/stm32h7xx_hal_uart_ex.c
    ${HAL_DIR}/Src/stm32h7xx_hal_tim.c
    ${HAL_DIR}/Src/stm32h7xx_hal_tim_ex.c)

# ---- FreeRTOS kernel + Cortex-M7 port ----
# heap_4.c is intentionally NOT included: configSUPPORT_DYNAMIC_-
# ALLOCATION=0 makes heap_4.c emit a #error at the top of the file.
# Static allocation is used everywhere (round-5).
set(KERNEL_SRCS
    ${KERNEL_DIR}/tasks.c
    ${KERNEL_DIR}/queue.c
    ${KERNEL_DIR}/list.c
    ${KERNEL_DIR}/timers.c
    ${KERNEL_DIR}/event_groups.c
    ${KERNEL_DIR}/stream_buffer.c
    ${KERNEL_DIR}/portable/GCC/ARM_CM7/r0p1/port.c)

# ---- Application sources ----
set(APP_SRCS
    main.c
    test_ctxsw_irq.c
    test_thread_handoff.c
    test_mutex_uncontended.c
    test_mutex_pi.c
    system/system_stm32h7xx.c
    system/stm32h7xx_it.c
    system/syscalls_stubs.c
    ${COMMON_DIR}/dwt_cycle_counter.c
    ${COMMON_DIR}/benchmark_stats.c
    ${COMMON_DIR}/bench_button.c)

# ---- Startup ASM ----
set(STARTUP_SRC startup/startup_stm32h750xbhx.s)
set_property(SOURCE ${STARTUP_SRC} PROPERTY LANGUAGE ASM)

# ---- Linker script ----
set(LINKER_SCRIPT ${CMAKE_CURRENT_SOURCE_DIR}/startup/STM32H750XBHX_FLASH.ld)

# ---- Target ----
add_executable(${PROJECT_NAME}.elf
    ${KERNEL_SRCS}
    ${HAL_SRCS}
    ${APP_SRCS}
    ${STARTUP_SRC})

target_include_directories(${PROJECT_NAME}.elf PRIVATE
    .
    cfg
    system
    ${COMMON_DIR}
    ${KERNEL_DIR}/include
    ${KERNEL_DIR}/portable/GCC/ARM_CM7/r0p1
    ${HAL_DIR}/Inc
    ${CMSIS_DEV_DIR}/Include
    ${CMSIS_CORE_DIR}/Include)

target_link_options(${PROJECT_NAME}.elf PRIVATE
    ${CPU_FLAGS}
    -T${LINKER_SCRIPT}
    -Wl,--gc-sections
    -Wl,--cref
    -Wl,--print-memory-usage
    -Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}.map
    --specs=nano.specs
    --specs=nosys.specs)

# ---- Post-build: hex / bin / size ----
find_program(ARM_OBJCOPY arm-none-eabi-objcopy)
find_program(ARM_SIZE    arm-none-eabi-size)

add_custom_command(TARGET ${PROJECT_NAME}.elf POST_BUILD
    COMMAND ${ARM_OBJCOPY} -Oihex
            $<TARGET_FILE:${PROJECT_NAME}.elf>
            ${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}.hex
    COMMAND ${ARM_OBJCOPY} -Obinary
            $<TARGET_FILE:${PROJECT_NAME}.elf>
            ${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}.bin
    COMMAND ${ARM_SIZE} $<TARGET_FILE:${PROJECT_NAME}.elf>)
