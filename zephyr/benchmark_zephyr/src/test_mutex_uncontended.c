/* SPDX-License-Identifier: Apache-2.0 */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    test_mutex_uncontended.c
 * @brief   TEST 3 - Mutex uncontended lock/unlock (Zephyr).
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Zephyr equivalent of rt_test_012_011 (chMtxLock/chMtxUnlock):
 *   k_mutex_init + k_mutex_lock/k_mutex_unlock in a loop, single thread.
 *
 * DWT primary (ADR-015), 1 marker on PH1.
 *
 * NOTE on DWT overhead (reviewer round-5 #4 / ADR-013): each
 * sample includes ONE pair of dwt_get_cycles() reads (start +
 * end), ~3 cycles total. We do NOT subtract the overhead from
 * the published cycles -- the post-processor decides. The
 * banner reports the calibrated DWT overhead.
 */

#include <zephyr/kernel.h>
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static struct k_mutex mtx;

void bench_t3_setup(void)
{
    k_mutex_init(&mtx);
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

        k_mutex_lock(&mtx, K_FOREVER);
        k_mutex_unlock(&mtx);

        uint32_t t_end = dwt_get_cycles();
        BENCH_CLR_A1();

        samples[i].cycles = dwt_diff(t_start, t_end);
    }
}
