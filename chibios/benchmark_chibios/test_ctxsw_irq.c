/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

/**
 * @file    test_ctxsw_irq.c
 * @brief   TEST 1 - IRQ -> thread latency (ChibiOS), strada A1.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Reference: documented ChibiOS chThdSuspendS + chThdResumeI pattern
 * (NOT in 12.x). Spec: ADR-014. Measurement: dual-source per ADR-015
 * with two publication modes:
 *   - Phase 1 (DWT-only, active): headline = DWT delta A4 - A1
 *     (ISR_ENTRY -> THREAD_RUNNING). HW-event-to-ISR-entry
 *     component is EXCLUDED.
 *   - Mode LA (future): headline = LA delta A4 - A0_HW (HW compare
 *     event -> thread RUNNING). DWT is carried as software
 *     validation.
 * The firmware toggles all marker pins unconditionally regardless
 * of the active publication mode (ADR-015 sec. "Consequences for code").
 *
 * Strada A1 setup (refined 2026-05-05):
 *   TIM2 channel 1 in PWM mode 2 + CC1 interrupt as wakeup source.
 *   PA0 (alternate function AF1) goes HIGH at the exact instant
 *   CNT == CCR1, which is the SAME timer event that fires the
 *   CC1 IRQ. So PA0 rising edge and ISR entry derive from one
 *   single hardware event (no phase to calibrate).
 *
 *   PSC=239, ARR=999  -> 1 kHz period at 1 us resolution.
 *   CCR1=1            -> rising edge 1 us into each period.
 *   CCMR1: OC1M=PWM2, OC1PE=1.
 *   CCER : CC1E=1, polarity high.
 *   DIER : CC1IE=1, UIE=0.
 *
 * 6 marker pins (ADR-007 / ADR-014):
 *   A0_HW (PA0)  -> HW rising edge AT the CC1 match (= IRQ instant)
 *   A1 (PH1)     -> first instruction of the ISR (ISR_ENTRY)
 *   A2 (PH4)     -> just before chThdResumeI (wake primitive START)
 *   A3 (PH8)     -> just after chThdResumeI returns, BEFORE
 *                   chSysUnlockFromISR (READY proxy, A6 fix)
 *   A4 (PH12)    -> first instruction of the resumed thread (RUNNING)
 *
 * One DWT delta per iteration: t_running - t_isr_entry
 * (= software end-to-end A4 - A1).
 * - In Phase 1 (active) this delta IS the published headline.
 * - In Mode LA (future) the LA captures A4 - A0_HW as the
 *   external headline; the cross-port skew A0_HW -> A1 is
 *   captured by CAL-1 and DWT is carried as software validation.
 */

#include "ch.h"
#include "hal.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static thread_reference_t trp = NULL;
static binary_semaphore_t completion_bsem;
static binary_semaphore_t target_ready_bsem;
static volatile uint32_t  t_isr_entry;
static volatile uint32_t  sample_idx;
static bench_sample_t    *current_samples;
static volatile bool      test_done;

static THD_WORKING_AREA(wa_target, 512);

/*===========================================================================*/
/* TIM2 IRQ handler.                                                        */
/* GPT_USE_TIM2 = FALSE in mcuconf.h leaves the TIM2 vector free for us.    */
/*===========================================================================*/

OSAL_IRQ_HANDLER(STM32_TIM2_HANDLER)
{
    OSAL_IRQ_PROLOGUE();

    /* PA0 (= A0_HW) was set HIGH in HARDWARE by TIM2 OC at the same
     * CC1 match that triggered this IRQ. We do NOT touch PA0. */

    /* A1 = ISR_ENTRY: first software-visible instant. */
    BENCH_SET_A1();
    t_isr_entry = dwt_get_cycles();

    /* Clear CC1 interrupt flag BEFORE the wake primitive (F1
     * hygiene fix per ADR-014). FreeRTOS and Zephyr clear the
     * source IRQ flag between A1 and A2; this brings ChibiOS in
     * line so that the LA A2 - A1 sub-interval includes the
     * peripheral ack on all three ports. Also matches the
     * conventional ARM Cortex-M "ack first, work next" pattern.
     * Phase 1 headline (A4 - A1) is unchanged: the clear stays
     * inside that interval. */
    TIM2->SR = ~TIM_SR_CC1IF;

    /* A2 = before wake primitive. */
    BENCH_SET_A2();

    chSysLockFromISR();
    chThdResumeI(&trp, MSG_OK);
    /* A3 = READY proxy: SET inside chSysLock so we measure ONLY the
     * cost of chThdResumeI, not the unlock+epilogue (ADR-014 A6 fix). */
    BENCH_SET_A3();
    chSysUnlockFromISR();

    OSAL_IRQ_EPILOGUE();
}

/*===========================================================================*/
/* Target thread.                                                           */
/*===========================================================================*/

static THD_FUNCTION(target_thread, arg)
{
    (void)arg;
    /* Thread naming removed per ADR-022 (CH_CFG_USE_REGISTRY=FALSE
     * for feature parity with FreeRTOS/Zephyr footprint scope). */

    /* Signal "I am about to block" BEFORE the first chThdSuspendS,
     * so the runner waits on target_ready_bsem before starting TIM2.
     * Without this, in ChibiOS the very first CC1 IRQ could fire
     * with trp==NULL and chThdResumeI would silently drop the wake. */
    chBSemSignal(&target_ready_bsem);

    while (!test_done) {
        chSysLock();
        chThdSuspendS(&trp);
        chSysUnlock();

        /* A4 = RUNNING: first instant after resume. */
        BENCH_SET_A4();
        uint32_t now   = dwt_get_cycles();
        uint32_t delta = dwt_diff(t_isr_entry, now);

        /* Reset all software markers (PA0 hardware-driven, untouched). */
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
             * IRQ enable. A late ISR slipping through this window
             * would just give an extra completion_bsem signal,
             * which is capped by the binary semaphore. */
            TIM2->CR1   &= ~TIM_CR1_CEN;
            TIM2->CCER  &= ~TIM_CCER_CC1E;
            TIM2->DIER   = 0U;
            test_done = true;
            chBSemSignal(&completion_bsem);
        }
    }
}

/*===========================================================================*/
/* Public API.                                                              */
/*===========================================================================*/

void bench_t1_setup(void)
{
    trp        = NULL;
    sample_idx = 0;
    test_done  = false;

    /* Both semaphores start taken; the target gives target_ready
     * before suspending, the runner waits, then starts TIM2. */
    chBSemObjectInit(&completion_bsem, true);
    chBSemObjectInit(&target_ready_bsem, true);

    chThdCreateStatic(wa_target, sizeof(wa_target),
                      HIGHPRIO - 1, target_thread, NULL);

    /* Block until the target has reached its first chThdSuspendS.
     * Without this barrier, the first CC1 IRQ could land while
     * trp == NULL and the wake event would be silently dropped. */
    chBSemWait(&target_ready_bsem);

    /* Enable TIM2 clock + reset to a known state. */
    rccEnableTIM2(TRUE);
    rccResetTIM2();

    /* Stop the timer while we configure it. */
    TIM2->CR1 = 0U;

    /* PSC = 239, ARR = 999  -> 1 kHz update rate, 1 us tick.
     * CCR1 = 1 -> rising edge 1 us into the period. */
    TIM2->PSC = 239U;
    TIM2->ARR = 999U;
    TIM2->CCR1 = 1U;

    /* CCMR1: channel 1 as output, PWM mode 2 (OC1M = 0b111),
     * OC1PE = 1 (preload enable for clean PWM). */
    TIM2->CCMR1 = (TIM2->CCMR1 & ~(TIM_CCMR1_OC1M | TIM_CCMR1_CC1S |
                                   TIM_CCMR1_OC1PE)) |
                  (7U << TIM_CCMR1_OC1M_Pos) |
                  TIM_CCMR1_OC1PE;

    /* CCER: enable CH1 output, active polarity high. */
    TIM2->CCER = (TIM2->CCER & ~(TIM_CCER_CC1P)) | TIM_CCER_CC1E;

    /* Latch preload registers via update event. */
    TIM2->EGR = TIM_EGR_UG;
    TIM2->SR  = 0U;     /* clear all flags after EGR.UG */

    /* Enable CC1 IRQ only (no UIE). */
    TIM2->DIER = TIM_DIER_CC1IE;

    /* Install NVIC entry. CORTEX_PRIO_MASK() takes a logical priority and
     * encodes it to the hardware NVIC form; the configured logical
     * priority is STM32_IRQ_TIM2_PRIORITY = 7, uniform across the three
     * ports (ADR-014). */
    nvicEnableVector(STM32_TIM2_NUMBER,
                     CORTEX_PRIO_MASK(STM32_IRQ_TIM2_PRIORITY));
}

void bench_t1_print_addresses(void)
{
    bench_print_addr("t1_wa_target",       wa_target);
    bench_print_addr("t1_completion_bsem", &completion_bsem);
    bench_print_addr("t1_target_ready",    &target_ready_bsem);
    bench_print_addr("t1_t_isr_entry",     (const void *)&t_isr_entry);
    bench_print_addr("t1_trp",             (const void *)&trp);
}

void bench_t1_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx      = 0;
    test_done       = false;

    /* Start the timer: PA0 starts pulsing and CC1 IRQs start firing. */
    TIM2->CR1 |= TIM_CR1_CEN;

    /* Block here until the target thread has collected all samples
     * AND has stopped TIM2 from its own context. No 50 ms polling
     * window in which the timer could keep firing on a dying target. */
    chBSemWait(&completion_bsem);

    nvicDisableVector(STM32_TIM2_NUMBER);
}
