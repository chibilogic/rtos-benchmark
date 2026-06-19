/* SPDX-License-Identifier: MIT */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    test_thread_handoff.c
 * @brief   TEST 2 - Thread handoff latency (FreeRTOS).
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * FreeRTOS equivalent of rt_test_012_004 (chSchGoSleepS+chSchWakeupS):
 *   target  : vTaskSuspend(NULL)
 *   tester  : vTaskResume(target_handle)
 *
 * DWT primary (ADR-015), 1 marker on PH1.
 */

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "stm32h7xx_hal.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static volatile uint32_t handoff_t_send;
static volatile uint32_t sample_idx;
static bench_sample_t   *current_samples;
static volatile bool     run_flag;

static TaskHandle_t target_handle;

/* Static storage for the target task (configSUPPORT_DYNAMIC_-
 * ALLOCATION=0). */
#define T2_TARGET_STACK_WORDS  (4U * configMINIMAL_STACK_SIZE)
static StackType_t  t2_target_stack[T2_TARGET_STACK_WORDS];
static StaticTask_t t2_target_tcb;

static StaticSemaphore_t target_ready_sem_storage;
static SemaphoreHandle_t target_ready_sem;

static void target_task(void *arg)
{
    (void)arg;

    /* Symmetry with T1: signal "I am about to suspend" before the
     * first vTaskSuspend(NULL). The runner waits before the first
     * vTaskResume. */
    xSemaphoreGive(target_ready_sem);

    while (run_flag) {
        vTaskSuspend(NULL);

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
    vTaskDelete(NULL);
}

void bench_t2_setup(void)
{
    handoff_t_send = 0;
    sample_idx     = 0;
    run_flag       = true;
    target_ready_sem = xSemaphoreCreateBinaryStatic(&target_ready_sem_storage);

    /* Target at prio max-1 (= 7), runner at max-2 (= 6). Resume
     * preempts the runner immediately -> measured ctxsw. Static
     * TCB+stack (configSUPPORT_DYNAMIC_ALLOCATION=0). */
    target_handle = xTaskCreateStatic(target_task, "bench_t2",
                                      T2_TARGET_STACK_WORDS,
                                      NULL,
                                      configMAX_PRIORITIES - 1,
                                      t2_target_stack,
                                      &t2_target_tcb);

    /* Block until the target has reached its first vTaskSuspend(NULL). */
    xSemaphoreTake(target_ready_sem, portMAX_DELAY);
}

void bench_t2_print_addresses(void)
{
    bench_print_addr("t2_target_tcb",     &t2_target_tcb);
    bench_print_addr("t2_target_stack",   t2_target_stack);
    bench_print_addr("t2_target_ready",   &target_ready_sem_storage);
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
        vTaskResume(target_handle);
        /* Target has prio max-1, runner max-2: Resume preempts.
         * When target re-suspends, ctxsw returns here. */
    }
}
