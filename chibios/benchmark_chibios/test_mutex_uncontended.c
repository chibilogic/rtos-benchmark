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
 * @file    test_mutex_uncontended.c
 * @brief   TEST 3 - Mutex uncontended lock/unlock (ChibiOS).
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Reference: rt_test_012_011 (12.11 Mutexes lock/unlock performance),
 * adapted to per-iteration latency via DWT. Spec: ADR-014.
 *
 * Single thread, initialised mutex, no contender.
 * Measure: time per lock+unlock pair.
 *
 * NOTE on DWT overhead (reviewer round-5 #4 / ADR-013): each
 * sample includes ONE pair of dwt_get_cycles() reads (start +
 * end). On Cortex-M7 at 480 MHz this is ~3 cycles total. We do
 * NOT subtract the overhead from the published cycles -- the
 * banner reports the calibrated value (`DWT overhead`), and the
 * post-processor can choose to subtract or not. Subtracting
 * inside the firmware would add another bias source (the
 * calibration itself drifts).
 */

#include "ch.h"
#include "hal.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

/* TEST 3: DWT primary (ADR-015). Single marker on PH1 = BENCH_PIN_A1
 * around the DWT region for LA sanity-check. */

static mutex_t mtx;

void bench_t3_setup(void)
{
    chMtxObjectInit(&mtx);
}

void bench_t3_print_addresses(void)
{
    bench_print_addr("t3_mtx", &mtx);
}

void bench_t3_run(bench_sample_t *samples)
{
    for (uint32_t i = 0; i < BENCH_TOTAL_ITERATIONS; i++) {
        BENCH_SET_A1();
        uint32_t t_start = dwt_get_cycles();

        chMtxLock(&mtx);
        chMtxUnlock(&mtx);

        uint32_t t_end = dwt_get_cycles();
        BENCH_CLR_A1();

        samples[i].cycles = dwt_diff(t_start, t_end);
    }
}
