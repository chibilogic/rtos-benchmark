cmake_minimum_required(VERSION 3.20)

# Toolchain ARM
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR ARM)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_CXX_COMPILER arm-none-eabi-g++)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_OBJCOPY arm-none-eabi-objcopy)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

project(benchmark_freertos C ASM)

set(CMAKE_C_STANDARD 11)

# Flag MCU comuni — IDENTICI a ChibiOS e Zephyr
set(MCU_FLAGS
    -mcpu=cortex-m7
    -mthumb
    -mfloat-abi=hard
    -mfpu=fpv5-d16
)

set(COMPILE_FLAGS
    ${MCU_FLAGS}
    -O2
    -ggdb
    -Wall -Wextra -Wundef
    -fdata-sections
    -ffunction-sections
    -DSTM32H743xx
    -DUSE_HAL_DRIVER
    -DBENCH_RTOS_FREERTOS
)

set(LINKER_FLAGS
    ${MCU_FLAGS}
    -T${CMAKE_SOURCE_DIR}/STM32H743ZITx_FLASH.ld
    -Wl,--gc-sections
    -Wl,-Map=${PROJECT_NAME}.map
    --specs=nano.specs
    --specs=nosys.specs
    -lm
)

# Path ai submodule
set(FREERTOS_DIR    ${CMAKE_SOURCE_DIR}/../FreeRTOS-Kernel)
set(STM32_HAL_DIR   ${CMAKE_SOURCE_DIR}/../stm32_hal)
set(CMSIS_DIR       ${STM32_HAL_DIR}/Drivers/CMSIS)
set(HAL_DRIVERS_DIR ${STM32_HAL_DIR}/Drivers/STM32H7xx_HAL_Driver)
set(COMMON_DIR      ${CMAKE_SOURCE_DIR}/../../common)

# ---------- Sorgenti FreeRTOS ----------
set(FREERTOS_SOURCES
    ${FREERTOS_DIR}/tasks.c
    ${FREERTOS_DIR}/queue.c
    ${FREERTOS_DIR}/list.c
    ${FREERTOS_DIR}/timers.c
    ${FREERTOS_DIR}/event_groups.c
    ${FREERTOS_DIR}/stream_buffer.c
    ${FREERTOS_DIR}/portable/GCC/ARM_CM7/r0p1/port.c
    ${FREERTOS_DIR}/portable/MemMang/heap_4.c
)

# ---------- Sorgenti STM32 HAL (minimi) ----------
set(HAL_SOURCES
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_cortex.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_rcc.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_rcc_ex.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_gpio.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_uart.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_uart_ex.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_tim.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_tim_ex.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_pwr.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_pwr_ex.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_dma.c
    ${HAL_DRIVERS_DIR}/Src/stm32h7xx_hal_dma_ex.c
)

# ---------- Sorgenti applicativi ----------
set(APP_SOURCES
    main.c
    test_ctxsw_irq.c
    test_ctxsw_mutex.c
    stm32h7xx_it.c
    stm32h7xx_hal_msp.c
    system_stm32h7xx.c
    startup_stm32h743xx.s
    ${COMMON_DIR}/dwt_cycle_counter.c
    ${COMMON_DIR}/benchmark_stats.c
)

add_executable(${PROJECT_NAME}.elf
    ${APP_SOURCES}
    ${FREERTOS_SOURCES}
    ${HAL_SOURCES}
)

target_include_directories(${PROJECT_NAME}.elf PRIVATE
    ${CMAKE_SOURCE_DIR}
    ${COMMON_DIR}
    ${FREERTOS_DIR}/include
    ${FREERTOS_DIR}/portable/GCC/ARM_CM7/r0p1
    ${HAL_DRIVERS_DIR}/Inc
    ${CMSIS_DIR}/Include
    ${CMSIS_DIR}/Device/ST/STM32H7xx/Include
)

target_compile_options(${PROJECT_NAME}.elf PRIVATE ${COMPILE_FLAGS})
target_link_options(${PROJECT_NAME}.elf PRIVATE ${LINKER_FLAGS})

# Genera .bin e .hex
add_custom_command(TARGET ${PROJECT_NAME}.elf POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:${PROJECT_NAME}.elf>
                                         ${PROJECT_NAME}.bin
    COMMAND ${CMAKE_OBJCOPY} -O ihex   $<TARGET_FILE:${PROJECT_NAME}.elf>
                                         ${PROJECT_NAME}.hex
    COMMAND arm-none-eabi-size $<TARGET_FILE:${PROJECT_NAME}.elf>
)
