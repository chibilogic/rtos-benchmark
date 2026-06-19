/**
  ******************************************************************************
  * @file    stm32h7xx_it.c
  * @author  MCD Application Team
  * @brief   Main Interrupt Service Routines.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2019 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  * Modified for the rtos-benchmark project by Chibilogic s.r.l.
  * (www.chibilogic.com): the exception and TIM2_IRQHandler bodies delegate to
  * FreeRTOS and the T1 test (bench_t1_isr). The file retains its original
  * STMicroelectronics license; only the application-specific handler bodies
  * were changed.
  ******************************************************************************
  */

#include "FreeRTOS.h"
#include "task.h"
#include "stm32h7xx_hal.h"
#include "stm32h7xx_it.h"

/* Defined by the T1 test (test_ctxsw_irq.c). */
extern void bench_t1_isr(void);

/* FreeRTOS port tick handler (port.c). */
extern void xPortSysTickHandler(void);

void NMI_Handler(void)        { while (1) { } }
void HardFault_Handler(void)  { while (1) { } }
void MemManage_Handler(void)  { while (1) { } }
void BusFault_Handler(void)   { while (1) { } }
void UsageFault_Handler(void) { while (1) { } }
void DebugMon_Handler(void)   { }

/* SVC_Handler / PendSV_Handler are mapped to the FreeRTOS handlers in
 * FreeRTOSConfig.h, so they are intentionally not defined here. */

void SysTick_Handler(void)
{
    HAL_IncTick();
    if (xTaskGetSchedulerState() != taskSCHEDULER_NOT_STARTED) {
        xPortSysTickHandler();
    }
}

void TIM2_IRQHandler(void)
{
    bench_t1_isr();
}
