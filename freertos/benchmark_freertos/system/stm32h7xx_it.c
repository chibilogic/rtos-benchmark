/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 *
 * Derived from the ST stm32h7xx_it.c template (BSD/Apache style).
 * Customised for the rtos-benchmark project:
 *   - SVC_Handler / PendSV_Handler delegated to FreeRTOS
 *   - SysTick_Handler calls HAL + FreeRTOS
 *   - TIM2_IRQHandler delegated to bench_t1_isr() (defined by the T1 test)
 */

/**
 * @file    stm32h7xx_it.c
 * @brief   Interrupt service routines for the rtos-benchmark FreeRTOS port.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 */

#include "FreeRTOS.h"
#include "task.h"
#include "stm32h7xx_hal.h"
#include "stm32h7xx_it.h"

/* Forward declared by the T1 test (test_ctxsw_irq.c). */
extern void bench_t1_isr(void);

/* FreeRTOS port-specific tick handler, defined in port.c. */
extern void xPortSysTickHandler(void);

/*===========================================================================*/
/* Cortex-M7 exceptions.                                                    */
/*===========================================================================*/

void NMI_Handler(void)            { while (1) { } }
void HardFault_Handler(void)      { while (1) { } }
void MemManage_Handler(void)      { while (1) { } }
void BusFault_Handler(void)       { while (1) { } }
void UsageFault_Handler(void)     { while (1) { } }
void DebugMon_Handler(void)       { }

/* SVC and PendSV mapped to FreeRTOS via FreeRTOSConfig.h
 * (#define vPortSVCHandler SVC_Handler, etc.). */

void SysTick_Handler(void)
{
    HAL_IncTick();
    if (xTaskGetSchedulerState() != taskSCHEDULER_NOT_STARTED) {
        xPortSysTickHandler();
    }
}

/*===========================================================================*/
/* Peripheral handlers used by the benchmark.                               */
/*===========================================================================*/

/* TIM2 update event -> T1 test ISR (IRQ -> thread wakeup). */
void TIM2_IRQHandler(void)
{
    bench_t1_isr();
}
