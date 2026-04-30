/**
 * @file    FreeRTOSConfig.h
 * @brief   Configurazione FreeRTOS per il benchmark.
 *
 * I parametri sono scelti per essere il piu' possibile equivalenti
 * a quelli di ChibiOS e Zephyr, in modo da garantire un confronto
 * equo. Vedi CLAUDE.md per i vincoli identici.
 */

#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#include <stdint.h>

/* SYSCLK = 480 MHz (HSE 8 MHz x PLL) */
#define configCPU_CLOCK_HZ              ( ( uint32_t ) 480000000 )

/* Tick rate IDENTICO agli altri RTOS */
#define configTICK_RATE_HZ              ( ( TickType_t ) 1000 )

/* Tickless idle DISABILITATO per il primo scenario di benchmark */
#define configUSE_TICKLESS_IDLE         0

/* Scheduler preemptivo standard */
#define configUSE_PREEMPTION            1
#define configUSE_TIME_SLICING          1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 1

/* Priorita' max — 32 livelli come ChibiOS */
#define configMAX_PRIORITIES            ( 32 )
#define configMINIMAL_STACK_SIZE        ( ( uint16_t ) 256 )

/* Heap: 32 KB sufficienti per il benchmark */
#define configTOTAL_HEAP_SIZE           ( ( size_t ) ( 32 * 1024 ) )

/* Mutex con priority inheritance — IDENTICO a ChibiOS */
#define configUSE_MUTEXES               1
#define configUSE_RECURSIVE_MUTEXES     1
#define configUSE_COUNTING_SEMAPHORES   1

/* Stats DISABILITATE durante benchmark (overhead non voluto) */
#define configUSE_TRACE_FACILITY        0
#define configGENERATE_RUN_TIME_STATS   0
#define configCHECK_FOR_STACK_OVERFLOW  0
#define configUSE_MALLOC_FAILED_HOOK    0
#define configUSE_IDLE_HOOK             0
#define configUSE_TICK_HOOK             0
#define configUSE_DAEMON_TASK_STARTUP_HOOK 0

/* Hook necessari (vuoti) */
#define configRECORD_STACK_HIGH_ADDRESS 0
#define configUSE_QUEUE_SETS            0
#define configUSE_TASK_NOTIFICATIONS    1
#define configTASK_NOTIFICATION_ARRAY_ENTRIES 1

/* API includes */
#define INCLUDE_vTaskPrioritySet        1
#define INCLUDE_uxTaskPriorityGet       1
#define INCLUDE_vTaskDelete             1
#define INCLUDE_vTaskCleanUpResources   0
#define INCLUDE_vTaskSuspend            1
#define INCLUDE_vTaskDelayUntil         1
#define INCLUDE_vTaskDelay              1
#define INCLUDE_xTaskGetSchedulerState  1
#define INCLUDE_uxTaskGetStackHighWaterMark 0
#define INCLUDE_xTaskGetIdleTaskHandle  0
#define INCLUDE_eTaskGetState           0
#define INCLUDE_xTimerPendFunctionCall  0
#define INCLUDE_xTaskAbortDelay         0
#define INCLUDE_xTaskGetHandle          0

/* ARM Cortex-M7 specifico */
#define configPRIO_BITS                 4
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY     15
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY 5

#define configKERNEL_INTERRUPT_PRIORITY \
    ( configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8 - configPRIO_BITS) )
#define configMAX_SYSCALL_INTERRUPT_PRIORITY \
    ( configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8 - configPRIO_BITS) )

/* Mappatura ISR (IDENTICA al port ARM_CM7) */
#define vPortSVCHandler         SVC_Handler
#define xPortPendSVHandler      PendSV_Handler
#define xPortSysTickHandler     SysTick_Handler

/* Assert: spegnamo durante benchmark per non avere overhead */
#define configASSERT( x )

#endif /* FREERTOS_CONFIG_H */
