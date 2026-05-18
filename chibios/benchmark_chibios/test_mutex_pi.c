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
 * @file    test_mutex_pi.c
 * @brief   TEST 4 - Mutex contended + Priority Inheritance (ChibiOS).
 *          One-shot per ChibiOS rt_test_008_002 pattern, repeated
 *          BENCH_T4_RUNS times.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Reference: rt_test_008_002 (ChibiOS RT 8.2 "Priority inheritance,
 * simple case"). The test set is the official suite, the priority
 * scheme and timing are identical, the busy_pulse equivalent is
 * dwt_busy_cpu_pulse_us. Three autonomous threads + a runner that
 * just observes the outcome:
 *
 *   L (NORMALPRIO+1): lock mtx, busy 40 ms (CPU), unlock, busy 10 ms,
 *                     emit 'C'.
 *   M (NORMALPRIO+2): sleep 20 ms, busy 40 ms (CPU) while pulsing
 *                     MEDIUM_RUN, emit 'B'.
 *   H (NORMALPRIO+3): sleep 40 ms, lock mtx (blocks -> PI fires),
 *                     busy 10 ms while holding the mtx, unlock,
 *                     emit 'A'.
 *
 * With PI: L gets H's priority while H waits, so M cannot preempt L.
 * Sequence is A,B,C and total time ~100 ms. Without PI: M preempts
 * L throughout, sequence becomes B,A,C.
 *
 * Per-run output:
 *   sample.cycles = dwt_diff(t_unlock, t_acquire)
 *                 = LOW_UNLOCK -> HIGH_ACQUIRE handoff latency.
 *   pi_ok         = 1 iff seq == "ABC".
 *
 * Markers (used as LA primary in Mode LA per ADR-015; the
 * firmware toggles them unconditionally regardless of the
 * active publication mode, see ADR-015 §"Consequences for
 * code"):
 *   LOW_LOCK     (PH1)   set by L on chMtxLock
 *   HIGH_WAIT    (PH4)   set by H just before chMtxLock
 *   LOW_UNLOCK   (PH8)   set by L just before chMtxUnlock
 *   HIGH_ACQUIRE (PH12)  set by H just after chMtxLock returns
 *   MEDIUM_RUN   (PI11)  pulsed by M inside its busy loop
 *
 * The runner orchestrates BENCH_T4_RUNS one-shot iterations using
 * three binary semaphores (go_l/go_m/go_h) and one counting
 * semaphore (done_sem_ctr). Threads are created once and reused
 * across iterations via the go-semaphore pattern.
 */

#include "ch.h"
#include "hal.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

/*===========================================================================*/
/* Synchronisation objects.                                                 */
/*===========================================================================*/

static mutex_t            pi_mtx;
static binary_semaphore_t go_l_sem, go_m_sem, go_h_sem;
static semaphore_t        done_sem_ctr;

/* Per-iteration shared state. */
static volatile char      seq[3];
static volatile uint32_t  seq_idx;
static volatile uint32_t  t_unlock;
static volatile uint32_t  t_acquire;
static volatile bool      run_flag;

/* Runtime sample storage. pi_ok_array is file-scope so the PI
 * summary can be printed without changing bench_t4_run's signature. */
static bench_sample_t *current_samples;
static uint8_t         pi_ok_array[BENCH_T4_RUNS];

/* Worker stacks. */
static THD_WORKING_AREA(wa_L, 1024);
static THD_WORKING_AREA(wa_M, 1024);
static THD_WORKING_AREA(wa_H, 1024);

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

static THD_FUNCTION(l_thread, arg)
{
    (void)arg;
    chRegSetThreadName("bench_t4_L");
    while (true) {
        chBSemWait(&go_l_sem);
        if (!run_flag) {
            chThdSleep(TIME_INFINITE);
        }

        /* Sleep 0 -> immediate. */
        chMtxLock(&pi_mtx);
        BENCH_SET_LOW_LOCK();

        dwt_busy_cpu_pulse_us(40000U, BENCH_CPU_HZ);

        BENCH_SET_LOW_UNLOCK();
        t_unlock = dwt_get_cycles();
        chMtxUnlock(&pi_mtx);

        dwt_busy_cpu_pulse_us(10000U, BENCH_CPU_HZ);

        emit_token('C');
        chSemSignal(&done_sem_ctr);
    }
}

static THD_FUNCTION(m_thread, arg)
{
    (void)arg;
    chRegSetThreadName("bench_t4_M");
    while (true) {
        chBSemWait(&go_m_sem);
        if (!run_flag) {
            chThdSleep(TIME_INFINITE);
        }

        chThdSleepMilliseconds(20U);

        /* Pulses MEDIUM_RUN while M is on the CPU (flat when M
         * is preempted -- the PI proof). Common helper across the
         * 3 RTOS ports per reviewer round-5 #5. */
        dwt_busy_cpu_pulse_us_marker(40000U, BENCH_CPU_HZ,
                                     medium_run_set, medium_run_clr);

        emit_token('B');
        chSemSignal(&done_sem_ctr);
    }
}

static THD_FUNCTION(h_thread, arg)
{
    (void)arg;
    chRegSetThreadName("bench_t4_H");
    while (true) {
        chBSemWait(&go_h_sem);
        if (!run_flag) {
            chThdSleep(TIME_INFINITE);
        }

        chThdSleepMilliseconds(40U);

        BENCH_SET_HIGH_WAIT();
        chMtxLock(&pi_mtx);
        t_acquire = dwt_get_cycles();
        BENCH_SET_HIGH_ACQUIRE();

        dwt_busy_cpu_pulse_us(10000U, BENCH_CPU_HZ);

        chMtxUnlock(&pi_mtx);
        emit_token('A');
        chSemSignal(&done_sem_ctr);
    }
}

/*===========================================================================*/
/* Public API.                                                              */
/*===========================================================================*/

static tprio_t saved_runner_prio;

void bench_t4_setup(void)
{
    chMtxObjectInit(&pi_mtx);
    chBSemObjectInit(&go_l_sem, true);   /* taken */
    chBSemObjectInit(&go_m_sem, true);
    chBSemObjectInit(&go_h_sem, true);
    chSemObjectInit(&done_sem_ctr, 0);   /* counting at 0 */
    run_flag = true;

    /* Elevate the calling (runner) thread above all 3 worker threads
     * so the give-three-then-take-three pattern is not preempted by
     * a worker between gives. Restored at the end of bench_t4_run. */
    saved_runner_prio = chThdSetPriority(HIGHPRIO);

    chThdCreateStatic(wa_L, sizeof(wa_L), NORMALPRIO + 1, l_thread, NULL);
    chThdCreateStatic(wa_M, sizeof(wa_M), NORMALPRIO + 2, m_thread, NULL);
    chThdCreateStatic(wa_H, sizeof(wa_H), NORMALPRIO + 3, h_thread, NULL);
}

void bench_t4_run(bench_sample_t *samples)
{
    current_samples = samples;

    for (uint32_t iter = 0U; iter < BENCH_T4_RUNS; iter++) {
        /* Reset per-iter shared state. */
        seq[0] = seq[1] = seq[2] = '\0';
        __atomic_store_n(&seq_idx, 0U, __ATOMIC_RELAXED);
        t_unlock  = 0U;
        t_acquire = 0U;

        /* Clear all 5 software markers. */
        BENCH_CLR_LOW_LOCK();
        BENCH_CLR_HIGH_WAIT();
        BENCH_CLR_LOW_UNLOCK();
        BENCH_CLR_HIGH_ACQUIRE();
        BENCH_CLR_MEDIUM_RUN();

        /* Release the 3 workers (runner is HIGHPRIO so the give
         * sequence is atomic w.r.t. workers). */
        chBSemSignal(&go_l_sem);
        chBSemSignal(&go_m_sem);
        chBSemSignal(&go_h_sem);

        /* Wait for all 3 to complete this iter. */
        chSemWait(&done_sem_ctr);
        chSemWait(&done_sem_ctr);
        chSemWait(&done_sem_ctr);

        /* Verify PI sequence. */
        bool pi_ok = (seq[0] == 'A' && seq[1] == 'B' && seq[2] == 'C');
        pi_ok_array[iter] = pi_ok ? 1U : 0U;

        /* Compute handoff latency from the DWT timestamps.
         * dwt_diff handles unsigned wrap-around; no guard
         * needed (Codex round-2 I1). */
        samples[iter].cycles = dwt_diff(t_unlock, t_acquire);
    }

    /* Tell the workers to park. They will wake from the next
     * chBSemWait, see run_flag=false, and chThdSleep(TIME_INFINITE). */
    run_flag = false;
    chBSemSignal(&go_l_sem);
    chBSemSignal(&go_m_sem);
    chBSemSignal(&go_h_sem);

    /* Restore runner priority. */
    (void)chThdSetPriority(saved_runner_prio);

    /* PI summary is printed by main AFTER stats+CSV so the output
     * stream stays linear (see bench_t4_get_pi_ok). */

    /* Final marker reset. */
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
    bench_print_addr("t4_wa_L",        wa_L);
    bench_print_addr("t4_wa_M",        wa_M);
    bench_print_addr("t4_wa_H",        wa_H);
    bench_print_addr("t4_pi_mtx",      &pi_mtx);
    bench_print_addr("t4_go_l_sem",    &go_l_sem);
    bench_print_addr("t4_go_m_sem",    &go_m_sem);
    bench_print_addr("t4_go_h_sem",    &go_h_sem);
    bench_print_addr("t4_done_sem",    &done_sem_ctr);
    bench_print_addr("t4_pi_ok_array", pi_ok_array);
    bench_print_addr("t4_seq",         (const void *)seq);
}
