/**
 * @file    test_ctxsw_mutex.c
 * @brief   T2 — Context switch via mutex contention (Zephyr).
 *
 * Equivalente Zephyr del test ChibiOS/FreeRTOS, usando k_mutex
 * (priority inheritance abilitato di default in Zephyr).
 */

#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

#define BENCH_LED_NODE DT_ALIAS(bench_led)
static const struct gpio_dt_spec bench_pin =
    GPIO_DT_SPEC_GET(BENCH_LED_NODE, gpios);

static struct k_mutex bench_mtx;
static struct k_sem   high_done_sem;
static struct k_sem   low_go_sem;

static volatile uint32_t low_release_timestamp;
static volatile uint32_t sample_idx;
static bench_sample_t   *current_samples;
static volatile bool     test_done;

#define HIGH_STACK_SIZE 2048
#define LOW_STACK_SIZE  2048
#define HIGH_PRIORITY   2    /* alta */
#define LOW_PRIORITY    8    /* bassa (numero piu' alto = priorita' minore) */

K_THREAD_STACK_DEFINE(high_stack, HIGH_STACK_SIZE);
K_THREAD_STACK_DEFINE(low_stack, LOW_STACK_SIZE);
static struct k_thread high_thread_data, low_thread_data;

static void high_thread(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

    while (!test_done) {
        k_mutex_lock(&bench_mtx, K_FOREVER);

        uint32_t now = dwt_get_cycles();
        uint32_t delta = dwt_diff(low_release_timestamp, now);

        gpio_pin_toggle_dt(&bench_pin);

        if (sample_idx < BENCH_ITERATIONS) {
            current_samples[sample_idx++].cycles = delta;
        } else {
            test_done = true;
        }

        k_mutex_unlock(&bench_mtx);
        k_sem_give(&high_done_sem);

        if (test_done) break;
    }
}

static void low_thread(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

    while (!test_done) {
        k_sem_take(&low_go_sem, K_FOREVER);
        if (test_done) break;

        k_mutex_lock(&bench_mtx, K_FOREVER);

        /* Finestra ~50 us per dare a HIGH la chance di mettersi in attesa */
        k_busy_wait(50);

        low_release_timestamp = dwt_get_cycles();
        k_mutex_unlock(&bench_mtx);

        k_sem_take(&high_done_sem, K_FOREVER);
    }
}

void bench_t2_setup(void)
{
    k_mutex_init(&bench_mtx);
    k_sem_init(&high_done_sem, 0, 1);
    k_sem_init(&low_go_sem, 0, 1);

    sample_idx = 0;
    test_done = false;

    k_thread_create(&high_thread_data, high_stack,
                    K_THREAD_STACK_SIZEOF(high_stack),
                    high_thread, NULL, NULL, NULL,
                    HIGH_PRIORITY, 0, K_NO_WAIT);
    k_thread_name_set(&high_thread_data, "bench_high");

    k_thread_create(&low_thread_data, low_stack,
                    K_THREAD_STACK_SIZEOF(low_stack),
                    low_thread, NULL, NULL, NULL,
                    LOW_PRIORITY, 0, K_NO_WAIT);
    k_thread_name_set(&low_thread_data, "bench_low");
}

void bench_t2_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx = 0;
    test_done = false;

    while (!test_done) {
        k_sem_give(&low_go_sem);
        k_msleep(1);
    }
}
