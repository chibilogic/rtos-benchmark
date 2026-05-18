/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    test_ctxsw_irq.c
 * @brief   TEST 1 - IRQ -> thread latency (Zephyr), strada A1.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Zephyr equivalent of the ChibiOS chThdSuspendS / chThdResumeI
 * pattern:
 *   target  : k_sem_take(&sem, K_FOREVER)
 *   ISR     : k_sem_give(&sem)
 *
 * Strada A1 setup (refined 2026-05-05): TIM2 channel 1 in PWM mode 2
 * + CC1 interrupt as wakeup source. PA0 (alternate function AF1)
 * goes HIGH at the same compare match that fires the CC1 IRQ.
 *
 *   PSC=239, ARR=999  -> 1 kHz period at 1 us resolution
 *   CCR1=1            -> rising edge 1 us into each period
 *   CCMR1: OC1M=PWM2, OC1PE=1
 *   CCER : CC1E=1, polarity high
 *   DIER : CC1IE=1, UIE=0
 *
 * 6 marker pins (ADR-007 / ADR-014):
 *   A0_HW (PA0)  -> HW rising edge at the CC1 match (= IRQ instant)
 *   A1 (PH1)     -> first instruction of the ISR (ISR_ENTRY)
 *   A2 (PH4)     -> just before k_sem_give (wake primitive START)
 *   A3 (PH8)     -> just after k_sem_give (READY proxy, A6 fix)
 *   A4 (PH12)    -> first instruction of the resumed thread (RUNNING)
 *
 * One DWT delta saved per iteration: t_running - t_isr_entry
 * (= software equivalent of LA's A4 - A1).
 *
 * Implementation: TIM2 is fully driven via CMSIS register writes;
 * the Zephyr counter driver is disabled (overlay) so the TIM2 IRQ
 * vector is free for our IRQ_CONNECT() handler.
 */

#include <zephyr/kernel.h>
#include <zephyr/devicetree.h>
#include <zephyr/irq.h>
#include <soc.h>
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static struct k_sem bench_sem;
static struct k_sem completion_sem;
static struct k_sem target_ready_sem;
static volatile uint32_t t_isr_entry;
static volatile uint32_t sample_idx;
static bench_sample_t   *current_samples;
static volatile bool     test_done;

#define BENCH_THREAD_STACK_SIZE 2048
#define BENCH_THREAD_PRIORITY   2     /* high prio (lower numeric) */

K_THREAD_STACK_DEFINE(bench_thread_stack, BENCH_THREAD_STACK_SIZE);
static struct k_thread bench_thread_data;

/*===========================================================================*/
/* TIM2 IRQ handler (CC1 source, strada A1).                                */
/*===========================================================================*/

static void tim2_isr(const void *arg)
{
    ARG_UNUSED(arg);

    /* PA0 (= A0_HW) was set HIGH in HARDWARE by TIM2 OC at the same
     * CC1 match that triggered this IRQ. We do NOT touch PA0. */

    /* A1 = ISR_ENTRY: first software-visible instant. */
    BENCH_SET_A1();
    t_isr_entry = dwt_get_cycles();

    /* Clear the CC1 flag. */
    TIM2->SR = ~TIM_SR_CC1IF;

    /* A2 = before wake primitive. */
    BENCH_SET_A2();

    k_sem_give(&bench_sem);

    /* A3 = READY proxy: SET right after k_sem_give returns, before
     * the implicit ISR exit so the marker isolates the wake primitive
     * cost (ADR-014 A6 fix). */
    BENCH_SET_A3();
}

/*===========================================================================*/
/* Target thread.                                                           */
/*===========================================================================*/

static void bench_thread(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

    /* Symmetry with the ChibiOS port (where the handshake is
     * mandatory): signal "I am about to block" before the first
     * k_sem_take. The runner waits before starting TIM2. */
    k_sem_give(&target_ready_sem);

    while (!test_done) {
        if (k_sem_take(&bench_sem, K_FOREVER) == 0) {
            /* A4 = RUNNING. */
            BENCH_SET_A4();
            uint32_t now   = dwt_get_cycles();
            uint32_t delta = dwt_diff(t_isr_entry, now);

            /* Reset software markers (PA0/A0_HW is HW-driven). */
            BENCH_CLR_A1();
            BENCH_CLR_A2();
            BENCH_CLR_A3();
            BENCH_CLR_A4();

            if (sample_idx < BENCH_TOTAL_ITERATIONS) {
                current_samples[sample_idx].cycles = delta;
                sample_idx++;
            }
            if (sample_idx >= BENCH_TOTAL_ITERATIONS) {
                /* Stop TIM2 from thread context BEFORE leaving the
                 * loop so no further IRQ can fire on a target that
                 * is about to suspend. Order: stop counter, stop
                 * output, disable IRQ source. */
                TIM2->CR1   &= ~TIM_CR1_CEN;
                TIM2->CCER  &= ~TIM_CCER_CC1E;
                TIM2->DIER   = 0U;
                test_done = true;
                k_sem_give(&completion_sem);
                /* Suspend self forever to keep the thread object
                 * valid in case one pending IRQ still vectors
                 * before bench_t1_run disables the NVIC line. */
                k_thread_suspend(k_current_get());
            }
        }
    }
}

/*===========================================================================*/
/* PA0 = TIM2_CH1 alternate function setup (register-direct).               */
/*===========================================================================*/

static void pa0_af1_setup(void)
{
    /* Ensure GPIOA clock is on (overlay sets &gpioa "okay" but we
     * keep the bit explicit for safety). */
    RCC->AHB4ENR |= RCC_AHB4ENR_GPIOAEN;

    /* PA0 -> alternate function (MODER bits [1:0] = 0b10). */
    GPIOA->MODER = (GPIOA->MODER & ~GPIO_MODER_MODE0) |
                   (2U << GPIO_MODER_MODE0_Pos);

    /* PA0 -> AF1 (TIM2_CH1) in AFRL. */
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~(0xFU << 0)) | (1U << 0);

    /* PA0 OSPEED = very high (3). */
    GPIOA->OSPEEDR = (GPIOA->OSPEEDR & ~GPIO_OSPEEDR_OSPEED0) |
                     (3U << GPIO_OSPEEDR_OSPEED0_Pos);

    /* PA0 push-pull, no pull. */
    GPIOA->OTYPER &= ~GPIO_OTYPER_OT0;
    GPIOA->PUPDR  &= ~GPIO_PUPDR_PUPD0;
}

/*===========================================================================*/
/* TIM2 setup (PWM mode 2 + CC1 IRQ, strada A1).                            */
/*===========================================================================*/

static void tim2_setup(void)
{
    /* Enable TIM2 clock + reset. */
    RCC->APB1LENR |= RCC_APB1LENR_TIM2EN;
    RCC->APB1LRSTR |= RCC_APB1LRSTR_TIM2RST;
    RCC->APB1LRSTR &= ~RCC_APB1LRSTR_TIM2RST;

    TIM2->CR1 = 0U;

    TIM2->PSC  = 239U;
    TIM2->ARR  = 999U;
    TIM2->CCR1 = 1U;

    /* CCMR1: CH1 output, PWM mode 2 (OC1M=0b111), preload enabled. */
    TIM2->CCMR1 = (TIM2->CCMR1 & ~(TIM_CCMR1_OC1M | TIM_CCMR1_CC1S |
                                   TIM_CCMR1_OC1PE)) |
                  (7U << TIM_CCMR1_OC1M_Pos) |
                  TIM_CCMR1_OC1PE;

    /* CCER: enable CH1 output, polarity high. */
    TIM2->CCER = (TIM2->CCER & ~TIM_CCER_CC1P) | TIM_CCER_CC1E;

    /* Latch preload via UG. */
    TIM2->EGR = TIM_EGR_UG;
    TIM2->SR  = 0U;

    /* Enable CC1 IRQ only. */
    TIM2->DIER = TIM_DIER_CC1IE;
}

/*===========================================================================*/
/* Public API.                                                              */
/*===========================================================================*/

void bench_t1_setup(void)
{
    k_sem_init(&bench_sem, 0, 1);
    k_sem_init(&completion_sem, 0, 1);
    k_sem_init(&target_ready_sem, 0, 1);
    sample_idx = 0;
    test_done  = false;

    k_thread_create(&bench_thread_data, bench_thread_stack,
                    K_THREAD_STACK_SIZEOF(bench_thread_stack),
                    bench_thread, NULL, NULL, NULL,
                    BENCH_THREAD_PRIORITY, 0, K_NO_WAIT);

    /* Block until the bench thread has reached its first
     * k_sem_take. Symmetry with the ChibiOS port. */
    k_sem_take(&target_ready_sem, K_FOREVER);

    pa0_af1_setup();
    tim2_setup();

    /* IRQ_CONNECT must stay inside a function in Zephyr 4.4: the
     * macro expands to compound-statement code with both compile-
     * time .intList section data and a runtime branch, which
     * cannot live at file scope (verified by the round-5 build
     * attempt: "expected identifier or '(' before '{' token").
     * Priority 7 = uniform across ChibiOS / FreeRTOS / Zephyr
     * ports per reviewer round-5 #1. */
    IRQ_CONNECT(TIM2_IRQn, 7, tim2_isr, NULL, 0);
    irq_enable(TIM2_IRQn);
}

void bench_t1_print_addresses(void)
{
    bench_print_addr("t1_thread_data",  &bench_thread_data);
    bench_print_addr("t1_thread_stack", bench_thread_stack);
    bench_print_addr("t1_bench_sem",    &bench_sem);
    bench_print_addr("t1_completion",   &completion_sem);
    bench_print_addr("t1_target_ready", &target_ready_sem);
    bench_print_addr("t1_t_isr_entry",  (const void *)&t_isr_entry);
}

void bench_t1_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx      = 0;
    test_done       = false;

    /* Start the timer: PA0 starts pulsing and CC1 IRQs start firing. */
    TIM2->CR1 |= TIM_CR1_CEN;

    /* Block until the bench thread has collected all samples AND has
     * stopped TIM2 from its own context. No 50 ms polling window in
     * which the timer could keep firing on a dying target. */
    k_sem_take(&completion_sem, K_FOREVER);

    irq_disable(TIM2_IRQn);
}
