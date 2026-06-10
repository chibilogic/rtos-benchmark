/* SPDX-License-Identifier: Apache-2.0 */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    test_thread_handoff.c
 * @brief   TEST 2 - Thread handoff latency (Zephyr).
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Zephyr equivalent of rt_test_012_004 (chSchGoSleepS+chSchWakeupS):
 *   target  : k_thread_suspend(k_current_get())
 *   tester  : k_thread_resume(target_tid)
 *
 * DWT primary (ADR-015), 1 marker on PH1.
 */

#include <zephyr/kernel.h>
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static volatile uint32_t handoff_t_send;
static volatile uint32_t sample_idx;
static bench_sample_t   *current_samples;
static volatile bool     run_flag;

#define TARGET_STACK_SIZE   2048
#define TARGET_PRIORITY     1     /* high prio (lower numeric > main) */

K_THREAD_STACK_DEFINE(target_stack, TARGET_STACK_SIZE);
static struct k_thread target_data;
static k_tid_t          target_tid;
static struct k_sem     target_ready_sem;

static void target_thread(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

    /* Symmetry with T1: signal "I am about to suspend" before
     * the first k_thread_suspend(self). */
    k_sem_give(&target_ready_sem);

    while (run_flag) {
        k_thread_suspend(k_current_get());

        uint32_t now   = dwt_get_cycles();
        uint32_t delta = dwt_diff(handoff_t_send, now);
        BENCH_CLR_A1();

        if (sample_idx < BENCH_TOTAL_ITERATIONS) {
            current_samples[sample_idx].cycles = delta;
            sample_idx++;
        }
        if (sample_idx >= BENCH_TOTAL_ITERATIONS) {
            run_flag = false;
        }
    }
}

void bench_t2_setup(void)
{
    handoff_t_send = 0;
    sample_idx     = 0;
    run_flag       = true;
    k_sem_init(&target_ready_sem, 0, 1);

    target_tid = k_thread_create(&target_data, target_stack,
                                 K_THREAD_STACK_SIZEOF(target_stack),
                                 target_thread, NULL, NULL, NULL,
                                 TARGET_PRIORITY, 0, K_NO_WAIT);

    /* Block until the target has reached its first
     * k_thread_suspend(self). Replaces the previous "let it
     * run, then suspend itself" sleep-based assumption. */
    k_sem_take(&target_ready_sem, K_FOREVER);
}

void bench_t2_print_addresses(void)
{
    bench_print_addr("t2_target_data",   &target_data);
    bench_print_addr("t2_target_stack",  target_stack);
    bench_print_addr("t2_target_ready",  &target_ready_sem);
    bench_print_addr("t2_handoff_t_send", (const void *)&handoff_t_send);
}

void bench_t2_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx      = 0;
    run_flag        = true;

    while (sample_idx < BENCH_TOTAL_ITERATIONS) {
        BENCH_SET_A1();
        handoff_t_send = dwt_get_cycles();
        k_thread_resume(target_tid);
        /* Target has higher prio than the main thread, so resume
         * preempts immediately. When target re-suspends, control
         * returns here. */
    }
}
