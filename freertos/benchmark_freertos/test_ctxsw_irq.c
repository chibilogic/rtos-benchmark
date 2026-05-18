/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    test_ctxsw_irq.c
 * @brief   TEST 1 - IRQ -> thread latency (FreeRTOS), strada A1.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * FreeRTOS equivalent of the ChibiOS chThdSuspendS / chThdResumeI
 * pattern:
 *   target  : ulTaskNotifyTake(pdTRUE, portMAX_DELAY)
 *   ISR     : vTaskNotifyGiveFromISR(handle, &higher_woken)
 *
 * Strada A1 setup (refined 2026-05-05): TIM2 channel 1 in PWM mode 2
 * + CC1 interrupt as wakeup source. PA0 (alternate function AF1)
 * goes HIGH at the same compare match that fires the CC1 IRQ, so
 * PA0 rising edge and ISR vectoring derive from one single timer
 * event (no phase to calibrate).
 *
 * 6 marker pins (ADR-007 / ADR-014):
 *   A0_HW (PA0)  -> hardware-driven by TIM2 channel 1 PWM mode 2
 *                   at CNT==CCR1==1; same instant as CC1 IRQ.
 *   A1 (PH1)     -> first instruction of the ISR (ISR_ENTRY)
 *   A2 (PH4)     -> just before vTaskNotifyGiveFromISR
 *   A3 (PH8)     -> just after vTaskNotifyGiveFromISR (READY proxy)
 *   A4 (PH12)    -> first instruction of the resumed task (RUNNING)
 *
 * One DWT delta saved per iteration: t_running - t_isr_entry
 * (= software equivalent of LA's A4 - A1). The full 3-way LA
 * decomposition lives in the LA capture only.
 */

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "stm32h7xx_hal.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static TaskHandle_t       target_handle;
static TIM_HandleTypeDef  htim2;
static StaticSemaphore_t  completion_sem_storage;
static SemaphoreHandle_t  completion_sem;
static StaticSemaphore_t  target_ready_sem_storage;
static SemaphoreHandle_t  target_ready_sem;

/* Static storage for the target task (configSUPPORT_DYNAMIC_-
 * ALLOCATION=0 forces this). 4 KB stack matches the runner. */
#define T1_TARGET_STACK_WORDS  (4U * configMINIMAL_STACK_SIZE)
static StackType_t  t1_target_stack[T1_TARGET_STACK_WORDS];
static StaticTask_t t1_target_tcb;

static volatile uint32_t t_isr_entry;
static volatile uint32_t sample_idx;
static bench_sample_t   *current_samples;
static volatile bool     test_done;

/*===========================================================================*/
/* TIM2 IRQ bridge (called from TIM2_IRQHandler in stm32h7xx_it.c).         */
/*===========================================================================*/

void bench_t1_isr(void)
{
    /* PA0 (= A0_HW) was set HIGH in HARDWARE by TIM2 OC at the same
     * CC1 match that triggered this IRQ. We do NOT touch PA0. */

    /* A1 = ISR_ENTRY: first software-visible instant. */
    BENCH_SET_A1();
    t_isr_entry = dwt_get_cycles();

    /* Clear the CC1 flag (strada A1: CC1 IRQ source, not update). */
    TIM2->SR = ~TIM_FLAG_CC1;

    /* A2 = before wake primitive. */
    BENCH_SET_A2();

    BaseType_t higher_woken = pdFALSE;
    vTaskNotifyGiveFromISR(target_handle, &higher_woken);

    /* A3 = READY proxy: SET BEFORE portYIELD_FROM_ISR so the marker
     * captures only the wake primitive cost, not the dispatch
     * triggered by yield (ADR-014 A6 fix). */
    BENCH_SET_A3();

    portYIELD_FROM_ISR(higher_woken);
}

/*===========================================================================*/
/* Target task.                                                             */
/*===========================================================================*/

static void target_task(void *arg)
{
    (void)arg;

    /* Symmetry with the ChibiOS port (where the handshake is
     * mandatory): signal "I am about to block" before the first
     * ulTaskNotifyTake. The runner waits before starting TIM2. */
    xSemaphoreGive(target_ready_sem);

    while (!test_done) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        /* A4 = RUNNING. */
        BENCH_SET_A4();
        uint32_t now   = dwt_get_cycles();
        uint32_t delta = dwt_diff(t_isr_entry, now);

        /* Reset software markers for next iter (A0_HW is HW-driven). */
        BENCH_CLR_A1();
        BENCH_CLR_A2();
        BENCH_CLR_A3();
        BENCH_CLR_A4();

        if (sample_idx < BENCH_TOTAL_ITERATIONS) {
            current_samples[sample_idx].cycles = delta;
            sample_idx++;
        }
        if (sample_idx >= BENCH_TOTAL_ITERATIONS) {
            /* Stop TIM2 from thread context BEFORE leaving the loop
             * so no further IRQ can fire on a target that is about
             * to terminate. Order: stop counter, then output, then
             * IRQ enable. Avoids the previous UB where the ISR
             * could call vTaskNotifyGiveFromISR(target_handle)
             * after a vTaskDelete had freed the handle. */
            TIM2->CR1   &= ~TIM_CR1_CEN;
            TIM2->CCER  &= ~TIM_CCER_CC1E;
            TIM2->DIER   = 0U;
            test_done = true;
            xSemaphoreGive(completion_sem);
            /* Suspend self forever instead of vTaskDelete: keeps
             * target_handle valid in the unlikely case the NVIC
             * still vectors one pending IRQ before bench_t1_run
             * disables it. */
            vTaskSuspend(NULL);
        }
    }
}

/*===========================================================================*/
/* TIM2 setup: 1 kHz periodic, CH1 PWM mode 2 on PA0, CC1 IRQ enabled.      */
/*===========================================================================*/

static void tim2_init(void)
{
    __HAL_RCC_TIM2_CLK_ENABLE();

    /* TIM2 kernel clock = 240 MHz (= 2 x APB1 at 120 MHz, ADR-008).
     * Prescaler 239 -> 1 MHz; period 999 -> 1 kHz IRQ. */
    htim2.Instance = TIM2;
    htim2.Init.Prescaler         = 239U;
    htim2.Init.CounterMode       = TIM_COUNTERMODE_UP;
    htim2.Init.Period            = 999U;
    htim2.Init.ClockDivision     = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    HAL_TIM_Base_Init(&htim2);

    /* ADR-014 strada A1: PWM mode 2 with Pulse=1.
     * PA0 goes HIGH at CNT == CCR1 == 1, the SAME timer event that
     * fires CC1IF. The IRQ source for the wakeup is therefore the
     * exact compare match, not the update event. */
    TIM_OC_InitTypeDef oc = {0};
    oc.OCMode     = TIM_OCMODE_PWM2;
    oc.Pulse      = 1U;
    oc.OCPolarity = TIM_OCPOLARITY_HIGH;
    oc.OCFastMode = TIM_OCFAST_DISABLE;
    oc.OCIdleState = TIM_OCIDLESTATE_RESET;
    HAL_TIM_PWM_ConfigChannel(&htim2, &oc, TIM_CHANNEL_1);

    /* Arm CC1 output (CCER.CC1E = 1) and CC1 IRQ source
     * (DIER.CC1IE = 1) here in setup, so the after_t1_setup
     * banner dump shows TIM2 ready to fire (DIER=0x2, CCER=0x1).
     * The counter itself stays stopped (CR1.CEN = 0); bench_t1_run
     * only sets CEN to start the actual run. This makes the
     * manifest symmetric with the ChibiOS and Zephyr ports
     * (reviewer round-8 / ADR-014). HAL_TIM_PWM_Start_IT is NOT
     * used because it bundles CCER + DIER + CEN in one call,
     * which would leave CCER=0/DIER=0 in the after_t1_setup dump. */
    TIM2->CCER |= TIM_CCER_CC1E;
    __HAL_TIM_ENABLE_IT(&htim2, TIM_IT_CC1);

    /* NVIC priority 7 (uniform across the 3 RTOS ports per
     * reviewer round-5: same hardware = same NVIC priority).
     * Must be >= configMAX_SYSCALL_INTERRUPT_PRIORITY (=5) to use
     * FromISR FreeRTOS APIs; 7 satisfies that. */
    HAL_NVIC_SetPriority(TIM2_IRQn, 7, 0);
    HAL_NVIC_EnableIRQ(TIM2_IRQn);
}

/*===========================================================================*/
/* Public API.                                                              */
/*===========================================================================*/

void bench_t1_setup(void)
{
    sample_idx = 0;
    test_done  = false;

    completion_sem    = xSemaphoreCreateBinaryStatic(&completion_sem_storage);
    target_ready_sem  = xSemaphoreCreateBinaryStatic(&target_ready_sem_storage);

    /* Target at prio max-1; runner is at max-2. IRQ NotifyGive sets
     * higher_woken=true and preempts the runner. Static TCB+stack
     * (configSUPPORT_DYNAMIC_ALLOCATION=0). */
    target_handle = xTaskCreateStatic(target_task, "bench_t1",
                                      T1_TARGET_STACK_WORDS,
                                      NULL,
                                      configMAX_PRIORITIES - 1,
                                      t1_target_stack,
                                      &t1_target_tcb);

    /* Block until the target has reached its first
     * ulTaskNotifyTake. Symmetry with the ChibiOS port. */
    xSemaphoreTake(target_ready_sem, portMAX_DELAY);

    tim2_init();
}

void bench_t1_print_addresses(void)
{
    bench_print_addr("t1_target_tcb",      &t1_target_tcb);
    bench_print_addr("t1_target_stack",    t1_target_stack);
    bench_print_addr("t1_completion_sem",  &completion_sem_storage);
    bench_print_addr("t1_target_ready",    &target_ready_sem_storage);
    bench_print_addr("t1_t_isr_entry",     (const void *)&t_isr_entry);
}

void bench_t1_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx      = 0;
    test_done       = false;

    /* Start the counter. CCER and DIER were already armed in
     * bench_t1_setup so that the after_t1_setup manifest dump
     * is symmetric with the ChibiOS / Zephyr ports. From this
     * point: CNT increments, at CNT==CCR1==1 PA0 goes HIGH and
     * CC1IF triggers tim2_isr (= the measured event). */
    __HAL_TIM_ENABLE(&htim2);

    /* Block until the target task has collected all samples AND has
     * stopped TIM2 from its own context. No 50 ms polling window in
     * which the timer could keep firing on a dying target. */
    xSemaphoreTake(completion_sem, portMAX_DELAY);

    HAL_NVIC_DisableIRQ(TIM2_IRQn);
}
