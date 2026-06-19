/* SPDX-License-Identifier: MIT */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    test_mutex_pi.c
 * @brief   TEST 4 - Mutex contended + Priority Inheritance (FreeRTOS).
 *          One-shot per ChibiOS rt_test_008_002 pattern, repeated
 *          BENCH_T4_RUNS times.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * FreeRTOS port of the ChibiOS rt_test_008_002 scenario. Three
 * autonomous tasks + a runner that observes the outcome:
 *
 *   L (prio 3): lock mtx, busy 40 ms (CPU), unlock, busy 10 ms,
 *               emit 'C'.
 *   M (prio 4): sleep 20 ms, busy 40 ms (CPU) while pulsing
 *               MEDIUM_RUN, emit 'B'.
 *   H (prio 5): sleep 40 ms, lock mtx (blocks -> PI fires), busy
 *               10 ms while holding mtx, unlock, emit 'A'.
 *
 * Runner (prio 6, configured in main.c) gives 3 go-semaphores per
 * iteration, takes 3 done-semaphore signals, verifies the
 * sequence, stores 1 latency sample + 1 pi_ok flag per run.
 *
 * FreeRTOS xSemaphoreCreateMutex enables priority inheritance by
 * default (do NOT use xSemaphoreCreateBinary as a mutex).
 */

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "stm32h7xx_hal.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

/*===========================================================================*/
/* Synchronisation objects (statically allocated).                          */
/*===========================================================================*/

static StaticSemaphore_t pi_mtx_storage;
static StaticSemaphore_t go_l_sem_storage, go_m_sem_storage, go_h_sem_storage;
static StaticSemaphore_t done_sem_ctr_storage;

static SemaphoreHandle_t pi_mtx;
static SemaphoreHandle_t go_l_sem, go_m_sem, go_h_sem;
static SemaphoreHandle_t done_sem_ctr;   /* counting, max 3 */

/* Per-iteration shared state. */
static volatile char     seq[3];
static volatile uint32_t seq_idx;
static volatile uint32_t t_unlock;
static volatile uint32_t t_acquire;
static volatile bool     run_flag;

static bench_sample_t *current_samples;
static uint8_t         pi_ok_array[BENCH_T4_RUNS];

/* Static task storage. */
#define T4_STACK_WORDS  (4 * configMINIMAL_STACK_SIZE)

static StackType_t l_stack[T4_STACK_WORDS];
static StackType_t m_stack[T4_STACK_WORDS];
static StackType_t h_stack[T4_STACK_WORDS];
static StaticTask_t l_tcb, m_tcb, h_tcb;
static TaskHandle_t l_handle, m_handle, h_handle;

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
/* Worker tasks.                                                            */
/*===========================================================================*/

static void l_task(void *arg)
{
    (void)arg;
    while (true) {
        xSemaphoreTake(go_l_sem, portMAX_DELAY);
        if (!run_flag) {
            vTaskSuspend(NULL);
        }

        /* Sleep 0 -> immediate. */
        xSemaphoreTake(pi_mtx, portMAX_DELAY);
        BENCH_SET_LOW_LOCK();

        dwt_busy_cpu_pulse_us(40000U, BENCH_CPU_HZ);

        BENCH_SET_LOW_UNLOCK();
        t_unlock = dwt_get_cycles();
        xSemaphoreGive(pi_mtx);

        dwt_busy_cpu_pulse_us(10000U, BENCH_CPU_HZ);

        emit_token('C');
        xSemaphoreGive(done_sem_ctr);
    }
}

static void m_task(void *arg)
{
    (void)arg;
    while (true) {
        xSemaphoreTake(go_m_sem, portMAX_DELAY);
        if (!run_flag) {
            vTaskSuspend(NULL);
        }

        vTaskDelay(pdMS_TO_TICKS(20));

        /* Pulses MEDIUM_RUN while M is on the CPU. Common helper
         * across the 3 ports per reviewer round-5 #5. */
        dwt_busy_cpu_pulse_us_marker(40000U, BENCH_CPU_HZ,
                                     medium_run_set, medium_run_clr);

        emit_token('B');
        xSemaphoreGive(done_sem_ctr);
    }
}

static void h_task(void *arg)
{
    (void)arg;
    while (true) {
        xSemaphoreTake(go_h_sem, portMAX_DELAY);
        if (!run_flag) {
            vTaskSuspend(NULL);
        }

        vTaskDelay(pdMS_TO_TICKS(40));

        BENCH_SET_HIGH_WAIT();
        xSemaphoreTake(pi_mtx, portMAX_DELAY);
        t_acquire = dwt_get_cycles();
        BENCH_SET_HIGH_ACQUIRE();

        dwt_busy_cpu_pulse_us(10000U, BENCH_CPU_HZ);

        xSemaphoreGive(pi_mtx);
        emit_token('A');
        xSemaphoreGive(done_sem_ctr);
    }
}

/*===========================================================================*/
/* Public API.                                                              */
/*===========================================================================*/

void bench_t4_setup(void)
{
    pi_mtx       = xSemaphoreCreateMutexStatic(&pi_mtx_storage);   /* PI ON */
    go_l_sem     = xSemaphoreCreateBinaryStatic(&go_l_sem_storage);
    go_m_sem     = xSemaphoreCreateBinaryStatic(&go_m_sem_storage);
    go_h_sem     = xSemaphoreCreateBinaryStatic(&go_h_sem_storage);
    /* Max count = 3: at most one done from each of L/M/H per iteration. */
    done_sem_ctr = xSemaphoreCreateCountingStatic(3U,
                                                  0U,
                                                  &done_sem_ctr_storage);
    run_flag = true;

    /* Runner is at configMAX_PRIORITIES-2 = 6 (set in main.c). Workers
     * at 3/4/5 are all below it, so the give sequence is not preempted
     * mid-way. No priority change needed here. */

    l_handle = xTaskCreateStatic(l_task, "bench_t4_L", T4_STACK_WORDS,
                                 NULL, 3, l_stack, &l_tcb);
    m_handle = xTaskCreateStatic(m_task, "bench_t4_M", T4_STACK_WORDS,
                                 NULL, 4, m_stack, &m_tcb);
    h_handle = xTaskCreateStatic(h_task, "bench_t4_H", T4_STACK_WORDS,
                                 NULL, 5, h_stack, &h_tcb);
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

        xSemaphoreGive(go_l_sem);
        xSemaphoreGive(go_m_sem);
        xSemaphoreGive(go_h_sem);

        xSemaphoreTake(done_sem_ctr, portMAX_DELAY);
        xSemaphoreTake(done_sem_ctr, portMAX_DELAY);
        xSemaphoreTake(done_sem_ctr, portMAX_DELAY);

        bool pi_ok = (seq[0] == 'A' && seq[1] == 'B' && seq[2] == 'C');
        pi_ok_array[iter] = pi_ok ? 1U : 0U;

        /* dwt_diff handles unsigned wrap-around; no guard
         * needed (Codex round-2 I1). */
        samples[iter].cycles = dwt_diff(t_unlock, t_acquire);
    }

    run_flag = false;
    xSemaphoreGive(go_l_sem);
    xSemaphoreGive(go_m_sem);
    xSemaphoreGive(go_h_sem);

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
    bench_print_addr("t4_l_tcb",        &l_tcb);
    bench_print_addr("t4_m_tcb",        &m_tcb);
    bench_print_addr("t4_h_tcb",        &h_tcb);
    bench_print_addr("t4_l_stack",      l_stack);
    bench_print_addr("t4_m_stack",      m_stack);
    bench_print_addr("t4_h_stack",      h_stack);
    bench_print_addr("t4_pi_mtx",       &pi_mtx_storage);
    bench_print_addr("t4_go_l_sem",     &go_l_sem_storage);
    bench_print_addr("t4_go_m_sem",     &go_m_sem_storage);
    bench_print_addr("t4_go_h_sem",     &go_h_sem_storage);
    bench_print_addr("t4_done_sem",     &done_sem_ctr_storage);
    bench_print_addr("t4_pi_ok_array",  pi_ok_array);
    bench_print_addr("t4_seq",          (const void *)seq);
}
