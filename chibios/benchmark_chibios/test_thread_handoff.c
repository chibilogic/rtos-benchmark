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
 * @file    test_thread_handoff.c
 * @brief   TEST 2 - Thread handoff latency (ChibiOS).
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Reference: rt_test_012_004 (12.4 Context Switch performance),
 * adapted to per-iteration latency via DWT instead of throughput.
 * Spec: ADR-014.
 *
 * ChibiOS primitives verbatim from 12.4:
 *   target  : chSchGoSleepS(CH_STATE_SUSPENDED) inside chSysLock
 *   tester  : chSchWakeupS(target_tp, MSG_OK)   inside chSysLock
 *
 * Topology: tester (NORMALPRIO) + target (NORMALPRIO+1, HIGHER).
 * Continuous loop, no IRQ, hot cache.
 */

#include "ch.h"
#include "hal.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

/* TEST 2: DWT primary (ADR-015). Single marker on PH1 = BENCH_PIN_A1
 * enclosing the DWT region, for LA sanity-check. */

/* Shared variable tester -> target. Atomic on Cortex-M7
 * (32-bit aligned LDR/STR is single-instruction). */
static volatile uint32_t handoff_t_send;

static volatile uint32_t sample_idx;
static bench_sample_t   *current_samples;
static volatile bool     run_flag;

static thread_t           *target_tp;
static binary_semaphore_t  target_ready_bsem;

static THD_WORKING_AREA(wa_target, 512);

/*===========================================================================*/
/* Target thread (high prio).                                               */
/*===========================================================================*/

static THD_FUNCTION(target_thread, arg)
{
    (void)arg;
    chRegSetThreadName("bench_t2_target");

    /* Symmetry with T1: signal "I am about to suspend" before the
     * first chSchGoSleepS, so the runner waits before issuing the
     * first chSchWakeupS. Without this, the first wakeup could
     * land while target is not yet in the sleep queue. */
    chBSemSignal(&target_ready_bsem);

    chSysLock();
    while (true) {
        /* S-locked sleep; tester wakes us via chSchWakeupS. */
        chSchGoSleepS(CH_STATE_SUSPENDED);

        /* On wake: read DWT immediately. */
        uint32_t now   = dwt_get_cycles();
        uint32_t delta = dwt_diff(handoff_t_send, now);
        BENCH_CLR_A1();

        if (!run_flag) {
            /* End-of-test: leave the loop outside sysLock. */
            break;
        }

        if (sample_idx < BENCH_TOTAL_ITERATIONS) {
            current_samples[sample_idx].cycles = delta;
            sample_idx++;
        }
    }
    chSysUnlock();

    chThdExit(MSG_OK);
}

/*===========================================================================*/
/* Public API.                                                              */
/*===========================================================================*/

void bench_t2_setup(void)
{
    handoff_t_send = 0;
    sample_idx     = 0;
    run_flag       = true;
    chBSemObjectInit(&target_ready_bsem, true);   /* taken */

    /* Target at NORMALPRIO+1 (preempts the tester on wake).
     * Created above the caller priority (= main thread, NORMALPRIO),
     * so it starts and immediately blocks on chSchGoSleepS. */
    target_tp = chThdCreateStatic(wa_target, sizeof(wa_target),
                                  NORMALPRIO + 1, target_thread, NULL);

    /* Block until the target has reached its first chSchGoSleepS. */
    chBSemWait(&target_ready_bsem);
}

void bench_t2_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx      = 0;
    run_flag        = true;

    /* Wakeup loop. Each iteration = 1 measured ctxsw. */
    while (sample_idx < BENCH_TOTAL_ITERATIONS) {
        chSysLock();
        BENCH_SET_A1();
        handoff_t_send = dwt_get_cycles();
        chSchWakeupS(target_tp, MSG_OK);
        /* chSchWakeupS inside sysLock + reschedule -> ctxsw to target.
         * When target re-suspends, control returns here. */
        chSysUnlock();
    }

    /* Terminate target: clear flag and final wakeup. */
    run_flag = false;
    chSysLock();
    chSchWakeupS(target_tp, MSG_OK);
    chSysUnlock();
    chThdWait(target_tp);
}

void bench_t2_print_addresses(void)
{
    bench_print_addr("t2_wa_target",      wa_target);
    bench_print_addr("t2_handoff_t_send", (const void *)&handoff_t_send);
    bench_print_addr("t2_target_ready",   &target_ready_bsem);
}
