/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    test_mutex_pi.c
 * @brief   TEST 4 - Mutex contended + Priority Inheritance (Zephyr).
 *          One-shot per ChibiOS rt_test_008_002 pattern, repeated
 *          BENCH_T4_RUNS times.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Zephyr port of the ChibiOS rt_test_008_002 scenario. Three
 * autonomous threads + a runner that observes the outcome:
 *
 *   L (prio 5, lower=higher in Zephyr): lock mtx, busy 40 ms (CPU),
 *                                       unlock, busy 10 ms, emit 'C'.
 *   M (prio 4): sleep 20 ms, busy 40 ms (CPU) while pulsing
 *               MEDIUM_RUN, emit 'B'.
 *   H (prio 3): sleep 40 ms, lock mtx (blocks -> PI fires), busy
 *               10 ms while holding mtx, unlock, emit 'A'.
 *
 * Runner is the main thread. CONFIG_MAIN_THREAD_PRIORITY=6 makes
 * main numerically larger (= lower priority) than all 3 workers.
 * For the give-three-then-take-three pattern to be atomic w.r.t.
 * the workers, bench_t4_setup elevates the runner to priority 2
 * (above all workers) for the duration of the test, then restores.
 *
 * Zephyr k_mutex implements priority inheritance by default.
 */

#include <zephyr/kernel.h>
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

/*===========================================================================*/
/* Synchronisation objects.                                                 */
/*===========================================================================*/

static struct k_mutex pi_mtx;
static struct k_sem   go_l_sem, go_m_sem, go_h_sem;
static struct k_sem   done_sem_ctr;   /* counting, max 3 */

static volatile char     seq[3];
static volatile uint32_t seq_idx;
static volatile uint32_t t_unlock;
static volatile uint32_t t_acquire;
static volatile bool     run_flag;

static bench_sample_t *current_samples;
static uint8_t         pi_ok_array[BENCH_T4_RUNS];

#define T4_STACK_SIZE  2048

K_THREAD_STACK_DEFINE(l_stack, T4_STACK_SIZE);
K_THREAD_STACK_DEFINE(m_stack, T4_STACK_SIZE);
K_THREAD_STACK_DEFINE(h_stack, T4_STACK_SIZE);

static struct k_thread l_data, m_data, h_data;
static k_tid_t         l_tid, m_tid, h_tid;

/*===========================================================================*/
/* Sequence-token helper.                                                   */
/*===========================================================================*/

static void emit_token(char c)
{
    uint32_t pos = __atomic_fetch_add(&seq_idx, 1U, __ATOMIC_RELAXED);
    if (pos < 3U) {
        seq[pos] = c;
    }
}

/* Marker callbacks for dwt_busy_cpu_pulse_us_marker (used by M). */
static void medium_run_set(void) { BENCH_SET_MEDIUM_RUN(); }
static void medium_run_clr(void) { BENCH_CLR_MEDIUM_RUN(); }

/*===========================================================================*/
/* Worker threads.                                                          */
/*===========================================================================*/

static void l_thread_fn(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);
    while (true) {
        k_sem_take(&go_l_sem, K_FOREVER);
        if (!run_flag) {
            k_thread_suspend(k_current_get());
        }

        k_mutex_lock(&pi_mtx, K_FOREVER);
        BENCH_SET_LOW_LOCK();

        dwt_busy_cpu_pulse_us(40000U, BENCH_CPU_HZ);

        BENCH_SET_LOW_UNLOCK();
        t_unlock = dwt_get_cycles();
        k_mutex_unlock(&pi_mtx);

        dwt_busy_cpu_pulse_us(10000U, BENCH_CPU_HZ);

        emit_token('C');
        k_sem_give(&done_sem_ctr);
    }
}

static void m_thread_fn(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);
    while (true) {
        k_sem_take(&go_m_sem, K_FOREVER);
        if (!run_flag) {
            k_thread_suspend(k_current_get());
        }

        k_msleep(20);

        /* Pulses MEDIUM_RUN while M is on the CPU. Common helper
         * across the 3 ports per reviewer round-5 #5. */
        dwt_busy_cpu_pulse_us_marker(40000U, BENCH_CPU_HZ,
                                     medium_run_set, medium_run_clr);

        emit_token('B');
        k_sem_give(&done_sem_ctr);
    }
}

static void h_thread_fn(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);
    while (true) {
        k_sem_take(&go_h_sem, K_FOREVER);
        if (!run_flag) {
            k_thread_suspend(k_current_get());
        }

        k_msleep(40);

        BENCH_SET_HIGH_WAIT();
        k_mutex_lock(&pi_mtx, K_FOREVER);
        t_acquire = dwt_get_cycles();
        BENCH_SET_HIGH_ACQUIRE();

        dwt_busy_cpu_pulse_us(10000U, BENCH_CPU_HZ);

        k_mutex_unlock(&pi_mtx);
        emit_token('A');
        k_sem_give(&done_sem_ctr);
    }
}

/*===========================================================================*/
/* Public API.                                                              */
/*===========================================================================*/

static int saved_runner_prio;

void bench_t4_setup(void)
{
    k_mutex_init(&pi_mtx);
    k_sem_init(&go_l_sem, 0, 1);
    k_sem_init(&go_m_sem, 0, 1);
    k_sem_init(&go_h_sem, 0, 1);
    k_sem_init(&done_sem_ctr, 0, 3);
    run_flag = true;

    /* Elevate the runner above all workers so the give-three pattern
     * is atomic. Workers at 5/4/3, set runner to 2. */
    saved_runner_prio = k_thread_priority_get(k_current_get());
    k_thread_priority_set(k_current_get(), 2);

    l_tid = k_thread_create(&l_data, l_stack, K_THREAD_STACK_SIZEOF(l_stack),
                            l_thread_fn, NULL, NULL, NULL,
                            5, 0, K_NO_WAIT);
    m_tid = k_thread_create(&m_data, m_stack, K_THREAD_STACK_SIZEOF(m_stack),
                            m_thread_fn, NULL, NULL, NULL,
                            4, 0, K_NO_WAIT);
    h_tid = k_thread_create(&h_data, h_stack, K_THREAD_STACK_SIZEOF(h_stack),
                            h_thread_fn, NULL, NULL, NULL,
                            3, 0, K_NO_WAIT);
}

void bench_t4_run(bench_sample_t *samples)
{
    current_samples = samples;

    for (uint32_t iter = 0U; iter < BENCH_T4_RUNS; iter++) {
        seq[0] = seq[1] = seq[2] = '\0';
        __atomic_store_n(&seq_idx, 0U, __ATOMIC_RELAXED);
        t_unlock  = 0U;
        t_acquire = 0U;

        BENCH_CLR_LOW_LOCK();
        BENCH_CLR_HIGH_WAIT();
        BENCH_CLR_LOW_UNLOCK();
        BENCH_CLR_HIGH_ACQUIRE();
        BENCH_CLR_MEDIUM_RUN();

        k_sem_give(&go_l_sem);
        k_sem_give(&go_m_sem);
        k_sem_give(&go_h_sem);

        k_sem_take(&done_sem_ctr, K_FOREVER);
        k_sem_take(&done_sem_ctr, K_FOREVER);
        k_sem_take(&done_sem_ctr, K_FOREVER);

        bool pi_ok = (seq[0] == 'A' && seq[1] == 'B' && seq[2] == 'C');
        pi_ok_array[iter] = pi_ok ? 1U : 0U;

        /* dwt_diff handles unsigned wrap-around; no guard
         * needed (Codex round-2 I1). */
        samples[iter].cycles = dwt_diff(t_unlock, t_acquire);
    }

    run_flag = false;
    k_sem_give(&go_l_sem);
    k_sem_give(&go_m_sem);
    k_sem_give(&go_h_sem);

    /* Restore runner priority. */
    k_thread_priority_set(k_current_get(), saved_runner_prio);

    /* PI summary is printed by main AFTER stats+CSV so the output
     * stream stays linear (see bench_t4_get_pi_ok). */

    BENCH_CLR_LOW_LOCK();
    BENCH_CLR_HIGH_WAIT();
    BENCH_CLR_LOW_UNLOCK();
    BENCH_CLR_HIGH_ACQUIRE();
    BENCH_CLR_MEDIUM_RUN();
}

const uint8_t *bench_t4_get_pi_ok(void)
{
    return pi_ok_array;
}

void bench_t4_print_addresses(void)
{
    bench_print_addr("t4_l_data",       &l_data);
    bench_print_addr("t4_m_data",       &m_data);
    bench_print_addr("t4_h_data",       &h_data);
    bench_print_addr("t4_l_stack",      l_stack);
    bench_print_addr("t4_m_stack",      m_stack);
    bench_print_addr("t4_h_stack",      h_stack);
    bench_print_addr("t4_pi_mtx",       &pi_mtx);
    bench_print_addr("t4_go_l_sem",     &go_l_sem);
    bench_print_addr("t4_go_m_sem",     &go_m_sem);
    bench_print_addr("t4_go_h_sem",     &go_h_sem);
    bench_print_addr("t4_done_sem",     &done_sem_ctr);
    bench_print_addr("t4_pi_ok_array",  pi_ok_array);
    bench_print_addr("t4_seq",          (const void *)seq);
}
