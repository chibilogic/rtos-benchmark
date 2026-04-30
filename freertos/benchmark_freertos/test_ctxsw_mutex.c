/**
 * @file    test_ctxsw_mutex.c
 * @brief   T2 — Context switch via mutex contention (FreeRTOS).
 *
 * Replica funzionale del test ChibiOS, usando xSemaphoreCreateMutex()
 * che implementa Priority Inheritance (equivalente al mutex ChibiOS).
 */

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "stm32h7xx_hal.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static SemaphoreHandle_t bench_mtx;
static SemaphoreHandle_t high_done_sem;
static SemaphoreHandle_t low_go_sem;

static volatile uint32_t low_release_timestamp;
static volatile uint32_t sample_idx;
static bench_sample_t   *current_samples;
static volatile bool     test_done;

static TaskHandle_t high_handle, low_handle;

static void high_task(void *p)
{
    (void)p;
    while (!test_done) {
        xSemaphoreTake(bench_mtx, portMAX_DELAY);

        uint32_t now = dwt_get_cycles();
        uint32_t delta = dwt_diff(low_release_timestamp, now);

        HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_0);

        if (sample_idx < BENCH_ITERATIONS) {
            current_samples[sample_idx++].cycles = delta;
        } else {
            test_done = true;
        }

        xSemaphoreGive(bench_mtx);
        xSemaphoreGive(high_done_sem);

        if (test_done) break;
    }
    vTaskDelete(NULL);
}

static void low_task(void *p)
{
    (void)p;
    while (!test_done) {
        xSemaphoreTake(low_go_sem, portMAX_DELAY);
        if (test_done) break;

        xSemaphoreTake(bench_mtx, portMAX_DELAY);

        /* Finestra per HIGH: ~50 us */
        for (volatile int i = 0; i < 24000; i++) { /* @480 MHz ~50us */ }

        low_release_timestamp = dwt_get_cycles();
        xSemaphoreGive(bench_mtx);

        xSemaphoreTake(high_done_sem, portMAX_DELAY);
    }
    vTaskDelete(NULL);
}

void bench_t2_setup(void)
{
    bench_mtx     = xSemaphoreCreateMutex();   /* PIP attivo di default */
    high_done_sem = xSemaphoreCreateBinary();
    low_go_sem    = xSemaphoreCreateBinary();

    sample_idx = 0;
    test_done = false;

    /* HIGH > runner_task; LOW < runner_task */
    xTaskCreate(high_task, "high", 1024, NULL,
                configMAX_PRIORITIES - 1, &high_handle);
    xTaskCreate(low_task, "low", 1024, NULL,
                configMAX_PRIORITIES - 4, &low_handle);
}

void bench_t2_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx = 0;
    test_done = false;

    while (!test_done) {
        xSemaphoreGive(low_go_sem);
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}
