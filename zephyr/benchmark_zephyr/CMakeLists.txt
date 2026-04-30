cmake_minimum_required(VERSION 3.20.0)

# Find Zephyr (esegue $ZEPHYR_BASE/share/zephyr-package/cmake/ZephyrConfig.cmake)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

project(benchmark_zephyr LANGUAGES C)

# Path al codice condiviso
set(COMMON_DIR ${CMAKE_SOURCE_DIR}/../../common)

# Sorgenti applicativi
target_sources(app PRIVATE
    src/main.c
    src/test_ctxsw_irq.c
    src/test_ctxsw_mutex.c
    ${COMMON_DIR}/dwt_cycle_counter.c
    ${COMMON_DIR}/benchmark_stats.c
)

target_include_directories(app PRIVATE
    ${COMMON_DIR}
    src
)

# Define per identificare l'RTOS
target_compile_definitions(app PRIVATE BENCH_RTOS_ZEPHYR)

# Flag IDENTICI agli altri progetti
target_compile_options(app PRIVATE -O2 -Wall -Wextra)
