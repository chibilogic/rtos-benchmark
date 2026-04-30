/**
 * @file    test_ctxsw_irq.c
 * @brief   T1 — Context switch via IRQ wake-up (Zephyr).
 *
 * Equivalente Zephyr del test ChibiOS/FreeRTOS:
 *   - Usa il counter API (driver/counter) per timer HW periodico
 *   - L'ISR fa k_sem_give() su un semaforo
 *   - Il thread bench attende su k_sem_take() e misura
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/counter.h>
#include <zephyr/drivers/gpio.h>
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

#define BENCH_LED_NODE DT_ALIAS(bench_led)
static const struct gpio_dt_spec bench_pin =
    GPIO_DT_SPEC_GET(BENCH_LED_NODE, gpios);

/* TIM2 esposto come counter device */
static const struct device *const counter_dev =
    DEVICE_DT_GET(DT_NODELABEL(counter2));

static struct k_sem bench_sem;
static volatile uint32_t isr_timestamp;
static volatile uint32_t sample_idx;
static bench_sample_t   *current_samples;
static volatile bool     test_done;

#define BENCH_THREAD_STACK_SIZE 2048
#define BENCH_THREAD_PRIORITY   2     /* alta priorita' (numeri bassi = alti in Zephyr) */

K_THREAD_STACK_DEFINE(bench_thread_stack, BENCH_THREAD_STACK_SIZE);
static struct k_thread bench_thread_data;

static void counter_isr(const struct device *dev,
                        uint8_t chan_id,
                        uint32_t ticks,
                        void *user_data)
{
    ARG_UNUSED(dev); ARG_UNUSED(chan_id); ARG_UNUSED(ticks);
    ARG_UNUSED(user_data);

    isr_timestamp = dwt_get_cycles();
    k_sem_give(&bench_sem);
}

static struct counter_alarm_cfg alarm_cfg;

static void bench_thread(void *p1, void *p2, void *p3)
{
    ARG_UNUSED(p1); ARG_UNUSED(p2); ARG_UNUSED(p3);

    while (!test_done) {
        if (k_sem_take(&bench_sem, K_FOREVER) == 0) {
            uint32_t now = dwt_get_cycles();
            uint32_t delta = dwt_diff(isr_timestamp, now);

            gpio_pin_toggle_dt(&bench_pin);

            if (sample_idx < BENCH_ITERATIONS) {
                current_samples[sample_idx++].cycles = delta;
            } else {
                test_done = true;
            }

            /* Riprogramma alarm per il prossimo evento */
            counter_set_channel_alarm(counter_dev, 0, &alarm_cfg);
        }
    }
}

void bench_t1_setup(void)
{
    k_sem_init(&bench_sem, 0, 1);
    sample_idx = 0;
    test_done = false;

    if (!device_is_ready(counter_dev)) {
        printk("ERR: counter2 not ready\n");
        return;
    }

    /* Alarm ogni 1 ms (counter freq tipicamente 1 MHz dopo prescaler) */
    uint32_t freq = counter_get_frequency(counter_dev);
    alarm_cfg.callback = counter_isr;
    alarm_cfg.ticks = freq / 1000;   /* 1 ms */
    alarm_cfg.user_data = NULL;
    alarm_cfg.flags = 0;

    k_thread_create(&bench_thread_data, bench_thread_stack,
                    K_THREAD_STACK_SIZEOF(bench_thread_stack),
                    bench_thread, NULL, NULL, NULL,
                    BENCH_THREAD_PRIORITY, 0, K_NO_WAIT);
    k_thread_name_set(&bench_thread_data, "bench_t1");
}

void bench_t1_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx = 0;
    test_done = false;

    counter_start(counter_dev);
    counter_set_channel_alarm(counter_dev, 0, &alarm_cfg);

    while (!test_done) {
        k_msleep(10);
    }

    counter_stop(counter_dev);
}
