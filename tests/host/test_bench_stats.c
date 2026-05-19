/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    test_bench_stats.c
 * @brief   Host-build unit test for bench_compute_stats
 *          (round-8 Item 5).
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Links the SAME bench_compute_stats() that the firmware uses
 * (compiled from common/benchmark_stats.c with -DBENCH_HOST_BUILD)
 * and runs it against the three boundary datasets specified in
 * notes/ADR-013-statistical-methodology.md and reference/discuss.txt
 * round-8 sec. 4:
 *
 *   1. Increasing range  : range(1, 10001)
 *      expected n=10000, min=1, max=10000, jitter=9999,
 *               median=5001, p95=9501, p99=9901
 *
 *   2. Constant 1234     : [1234] * 10000
 *      expected min=max=mean=median=p95=p99=1234,
 *               jitter=0, stddev=0
 *
 *   3. Single spike      : [100]*9999 + [10000]
 *      expected min=100, max=10000, jitter=9900,
 *               median=p95=p99=100, stddev=99
 *
 * Exits 0 on full match, non-zero on the first failed assertion.
 *
 * Build:
 *   gcc -DBENCH_HOST_BUILD -DBENCH_RTOS_CHIBIOS \
 *       -DBENCH_PROFILE_FAIR_PERF -O2 -Wall -Wextra \
 *       -I ../../common -o test_bench_stats \
 *       ../../common/benchmark_stats.c test_bench_stats.c -lm
 */

#include "benchmark_api.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>


static int g_failed = 0;


/*===========================================================================*/
/* Assertion helper.                                                        */
/*===========================================================================*/

static void check_eq_u32(const char *dataset, const char *field,
                         uint32_t got, uint32_t want)
{
    if (got == want) {
        printf("  [%-12s] %-12s = %10u  OK\n", dataset, field, got);
    } else {
        printf("  [%-12s] %-12s = %10u  FAIL (expected %u)\n",
               dataset, field, got, want);
        g_failed++;
    }
}

static void check_in_range_u32(const char *dataset, const char *field,
                               uint32_t got, uint32_t lo, uint32_t hi)
{
    if (got >= lo && got <= hi) {
        printf("  [%-12s] %-12s = %10u  OK (in [%u..%u])\n",
               dataset, field, got, lo, hi);
    } else {
        printf("  [%-12s] %-12s = %10u  FAIL (expected in [%u..%u])\n",
               dataset, field, got, lo, hi);
        g_failed++;
    }
}


/*===========================================================================*/
/* Dataset builders.                                                         */
/*===========================================================================*/

static bench_sample_t g_buf[BENCH_VALID_ITERATIONS];

static void fill_increasing(void)
{
    /* values 1, 2, 3, ..., 10000 in production order. */
    for (uint32_t i = 0; i < BENCH_VALID_ITERATIONS; i++) {
        g_buf[i].cycles = i + 1U;
    }
}

static void fill_constant(uint32_t v)
{
    for (uint32_t i = 0; i < BENCH_VALID_ITERATIONS; i++) {
        g_buf[i].cycles = v;
    }
}

static void fill_spike(uint32_t base, uint32_t spike)
{
    /* 9999 samples = base, then 1 sample = spike. The spike lands
     * at the end of the production-order buffer; position relative
     * to sort order is what the percentile formula tests. */
    for (uint32_t i = 0; i < BENCH_VALID_ITERATIONS - 1U; i++) {
        g_buf[i].cycles = base;
    }
    g_buf[BENCH_VALID_ITERATIONS - 1U].cycles = spike;
}


/*===========================================================================*/
/* Test cases.                                                              */
/*===========================================================================*/

static void test_increasing(void)
{
    printf("Dataset 1 - range(1, 10001):\n");
    fill_increasing();

    bench_stats_t s;
    bench_compute_stats(g_buf, BENCH_VALID_ITERATIONS, &s);

    check_eq_u32("increasing", "n",      s.n,             10000U);
    check_eq_u32("increasing", "min",    s.min_cycles,        1U);
    check_eq_u32("increasing", "max",    s.max_cycles,    10000U);
    check_eq_u32("increasing", "jitter", s.jitter_cycles,  9999U);
    check_eq_u32("increasing", "median", s.median_cycles,  5001U);
    check_eq_u32("increasing", "p95",    s.p95_cycles,     9501U);
    check_eq_u32("increasing", "p99",    s.p99_cycles,     9901U);

    /* Mean: integer-truncated mean of 1..10000 = floor(50005000/10000)
     * = 5000 (the .5 fraction is dropped). */
    check_eq_u32("increasing", "mean",   s.mean_cycles,    5000U);

    /* Stddev: sqrt(sum((i - 5000)^2 for i in 1..10000) / 10000)
     * = sqrt(83333335000 / 10000) = sqrt(8333333) ~= 2886.751.
     * Firmware casts the float result to uint32 (truncation), so
     * the legitimate range is {2886, 2887}. Allow a 2-cycle window. */
    check_in_range_u32("increasing", "stddev", s.stddev_cycles,
                       2885U, 2888U);
}

static void test_constant(void)
{
    printf("\nDataset 2 - constant 1234:\n");
    fill_constant(1234U);

    bench_stats_t s;
    bench_compute_stats(g_buf, BENCH_VALID_ITERATIONS, &s);

    check_eq_u32("constant",  "n",      s.n,             10000U);
    check_eq_u32("constant",  "min",    s.min_cycles,     1234U);
    check_eq_u32("constant",  "max",    s.max_cycles,     1234U);
    check_eq_u32("constant",  "mean",   s.mean_cycles,    1234U);
    check_eq_u32("constant",  "median", s.median_cycles,  1234U);
    check_eq_u32("constant",  "p95",    s.p95_cycles,     1234U);
    check_eq_u32("constant",  "p99",    s.p99_cycles,     1234U);
    check_eq_u32("constant",  "jitter", s.jitter_cycles,     0U);
    check_eq_u32("constant",  "stddev", s.stddev_cycles,     0U);
}

static void test_spike(void)
{
    printf("\nDataset 3 - [100]*9999 + [10000] (single spike):\n");
    fill_spike(100U, 10000U);

    bench_stats_t s;
    bench_compute_stats(g_buf, BENCH_VALID_ITERATIONS, &s);

    check_eq_u32("spike",     "n",      s.n,             10000U);
    check_eq_u32("spike",     "min",    s.min_cycles,      100U);
    check_eq_u32("spike",     "max",    s.max_cycles,    10000U);
    check_eq_u32("spike",     "jitter", s.jitter_cycles,  9900U);
    /* The spike at index 9999 of the sorted copy is past p99
     * (index 9900). p95 (index 9500) and p99 are both inside
     * the run of 100s; only max captures the spike. */
    check_eq_u32("spike",     "median", s.median_cycles,   100U);
    check_eq_u32("spike",     "p95",    s.p95_cycles,      100U);
    check_eq_u32("spike",     "p99",    s.p99_cycles,      100U);

    /* Mean: (9999*100 + 10000) / 10000 = 1009900 / 10000 = 100
     * (integer div drops .99). */
    check_eq_u32("spike",     "mean",   s.mean_cycles,     100U);

    /* Stddev: variance = (9999*0 + 9900^2) / 10000 = 9801
     * sqrt(9801) = 99 exactly. */
    check_eq_u32("spike",     "stddev", s.stddev_cycles,    99U);
}


/*===========================================================================*/
/* main.                                                                    */
/*===========================================================================*/

int main(void)
{
    printf("test_bench_stats - bench_compute_stats unit tests\n");
    printf("===================================================\n");

    test_increasing();
    test_constant();
    test_spike();

    printf("\n===================================================\n");
    if (g_failed == 0) {
        printf("ALL OK\n");
        return 0;
    } else {
        printf("FAIL: %d assertion(s) failed.\n", g_failed);
        return 1;
    }
}
