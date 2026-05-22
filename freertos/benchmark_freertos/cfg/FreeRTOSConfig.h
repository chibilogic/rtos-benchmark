/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 *
 * Customised for the rtos-benchmark from the FreeRTOS_Mail demo
 * template (STMicroelectronics). Upstream license: MIT (FreeRTOS).
 */

/**
 * @file    FreeRTOSConfig.h
 * @brief   FreeRTOS configuration for the rtos-benchmark project.
 *
 * Honours the constraints of ADR-009 (no asserts/checks/debug),
 * ADR-011 (profiles fair_perf / realistic_tickless),
 * ADR-013 (1000 Hz tick rate). Choices are motivated inline.
 */

#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#if defined(__ICCARM__) || defined(__CC_ARM) || defined(__GNUC__)
  #include <stdint.h>
  extern uint32_t SystemCoreClock;
#endif

/* ---- Core scheduler config (ADR-009) ---- */
#define configUSE_PREEMPTION                    1
#define configUSE_TIME_SLICING                  0   /* round-robin OFF */
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 1   /* uses CLZ on Cortex-M */
#define configCPU_CLOCK_HZ                      ( SystemCoreClock )
#define configTICK_RATE_HZ                      ( ( TickType_t ) 1000 )
#define configMAX_PRIORITIES                    ( 8 )
#define configMINIMAL_STACK_SIZE                ( ( uint16_t ) 256 )
/* Heap region. Unused at runtime: configSUPPORT_DYNAMIC_ALLOCATION=0
 * means no malloc path is reachable, and heap_4.c is intentionally
 * NOT included by the project CMakeLists.txt (it would otherwise
 * trigger its compile-time #error guard). The symbol is kept
 * defined here only because some FreeRTOS internals reference it
 * via the preprocessor; it has no runtime effect. */
#define configTOTAL_HEAP_SIZE                   ( ( size_t ) ( 1 * 1024 ) )
/* Lowered to 1 per ADR-022 (kernel feature equivalence): aligns RAM
 * footprint with Zephyr CONFIG_THREAD_NAME=n. FreeRTOS requires
 * configMAX_TASK_NAME_LEN >= 1 (the null terminator must fit in
 * pcTaskName[]); zero is not accepted. The 1-byte residual asymmetry
 * vs Zephyr (5 bytes total across the 5 tasks) is documented in
 * ADR-022 as acceptable. */
#define configMAX_TASK_NAME_LEN                 ( 1 )
#define configUSE_16_BIT_TICKS                  0
#define configIDLE_SHOULD_YIELD                 1

/* ---- Tickless, profile-aware (ADR-011) ---- */
#if defined(BENCH_PROFILE_REALISTIC_TICKLESS)
  #define configUSE_TICKLESS_IDLE               1
#else
  #define configUSE_TICKLESS_IDLE               0
#endif

/* ---- Hooks: all OFF (ADR-009 hard rule) ---- */
#define configUSE_IDLE_HOOK                     0
#define configUSE_TICK_HOOK                     0
#define configUSE_MALLOC_FAILED_HOOK            0
#define configCHECK_FOR_STACK_OVERFLOW          0

/* ---- Stats / trace / debug: all OFF (ADR-009) ---- */
#define configUSE_TRACE_FACILITY                0
#define configGENERATE_RUN_TIME_STATS           0
#define configRECORD_STACK_HIGH_ADDRESS         0
#define configUSE_STATS_FORMATTING_FUNCTIONS    0

/* ---- Primitives ---- */
#define configUSE_MUTEXES                       1   /* ADR-014 T3+T4 */
#define configUSE_RECURSIVE_MUTEXES             0
#define configUSE_COUNTING_SEMAPHORES           1   /* ADR-014 T4 done_sem */
#define configUSE_TASK_NOTIFICATIONS            1   /* ADR-014 T1 */
#define configTASK_NOTIFICATION_ARRAY_ENTRIES   1
#define configQUEUE_REGISTRY_SIZE               0

/* ---- Software timers OFF (not used by the benchmark) ---- */
#define configUSE_TIMERS                        0
#define configUSE_DAEMON_TASK_STARTUP_HOOK      0

/* ---- Co-routines OFF ---- */
#define configUSE_CO_ROUTINES                   0

/* ---- Memory allocation: ALL STATIC (matches ChibiOS / Zephyr).
 * Every TCB and synchronisation object is statically declared by
 * the application; no FreeRTOS heap path is reachable. heap_4.c
 * is intentionally NOT compiled into this build (see
 * CMakeLists.txt: configSUPPORT_DYNAMIC_ALLOCATION=0 makes
 * heap_4.c emit a compile-time #error, so it is excluded from
 * KERNEL_SRCS). main.c provides vApplicationGetIdleTaskMemory()
 * as required by configSUPPORT_STATIC_ALLOCATION=1. Timer task
 * callback not needed: configUSE_TIMERS=0. */
#define configSUPPORT_DYNAMIC_ALLOCATION        0
#define configSUPPORT_STATIC_ALLOCATION         1
#define configENABLE_BACKWARD_COMPATIBILITY     0

/* ---- Optional API includes ---- */
#define INCLUDE_vTaskPrioritySet                1
#define INCLUDE_uxTaskPriorityGet               1
#define INCLUDE_vTaskDelete                     1   /* used by tests on completion */
#define INCLUDE_vTaskCleanUpResources           0
#define INCLUDE_vTaskSuspend                    1   /* ADR-014 T2 */
#define INCLUDE_vTaskDelayUntil                 1
#define INCLUDE_vTaskDelay                      1
#define INCLUDE_xTaskGetSchedulerState          1
#define INCLUDE_xTaskGetCurrentTaskHandle       1
#define INCLUDE_xTaskAbortDelay                 0

/* ---- Cortex-M specific ---- */
#ifdef __NVIC_PRIO_BITS
  #define configPRIO_BITS                       __NVIC_PRIO_BITS
#else
  #define configPRIO_BITS                       4
#endif

#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY         0xf
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY    5

#define configKERNEL_INTERRUPT_PRIORITY \
    ( configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8 - configPRIO_BITS) )
#define configMAX_SYSCALL_INTERRUPT_PRIORITY \
    ( configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8 - configPRIO_BITS) )

/* ---- ASSERT: NO-OP (ADR-009 hard rule) ---- */
#define configASSERT( x )                       ((void)0)

/* ---- CMSIS handler mapping ---- */
#define vPortSVCHandler                         SVC_Handler
#define xPortPendSVHandler                      PendSV_Handler
/* SysTick_Handler is defined by HAL; stm32h7xx_it.c calls
 * xPortSysTickHandler from inside it. */

#endif /* FREERTOS_CONFIG_H */
