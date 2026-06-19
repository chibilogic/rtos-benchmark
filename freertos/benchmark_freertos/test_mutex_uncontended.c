/* SPDX-License-Identifier: MIT */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    test_mutex_uncontended.c
 * @brief   TEST 3 - Mutex uncontended lock/unlock (FreeRTOS).
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * FreeRTOS equivalent of rt_test_012_011 (chMtxLock/chMtxUnlock):
 *   xSemaphoreCreateMutex + Take/Give in a loop, single thread.
 *
 * DWT primary (ADR-015), 1 marker on PH1.
 *
 * NOTE on DWT overhead (reviewer round-5 #4 / ADR-013): each
 * sample includes ONE pair of dwt_get_cycles() reads (start +
 * end), ~3 cycles total. We do NOT subtract the overhead from
 * the published cycles -- the post-processor decides. The
 * banner reports the calibrated DWT overhead.
 */

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "stm32h7xx_hal.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static SemaphoreHandle_t mtx;
static StaticSemaphore_t mtx_storage;

void bench_t3_setup(void)
{
    mtx = xSemaphoreCreateMutexStatic(&mtx_storage);
}

void bench_t3_print_addresses(void)
{
    bench_print_addr("t3_mtx_storage", &mtx_storage);
}

void bench_t3_run(bench_sample_t *samples)
{
    for (uint32_t i = 0; i < BENCH_TOTAL_ITERATIONS; i++) {
        BENCH_SET_A1();
        uint32_t t_start = dwt_get_cycles();

        xSemaphoreTake(mtx, portMAX_DELAY);
        xSemaphoreGive(mtx);

        uint32_t t_end = dwt_get_cycles();
        BENCH_CLR_A1();

        samples[i].cycles = dwt_diff(t_start, t_end);
    }
}
