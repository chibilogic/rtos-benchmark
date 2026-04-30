/**
 * @file    main.c
 * @brief   Main del benchmark Zephyr.
 *          Stessa struttura di chibios e freertos per equivalenza.
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/sys/printk.h>
#include <zephyr/console/console.h>

/* Su Cortex-M7 abbiamo bisogno di SCB per disabilitare le cache */
#include <cmsis_core.h>

#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

extern void bench_print_csv_header(void);

#define BENCH_LED_NODE DT_ALIAS(bench_led)
static const struct gpio_dt_spec bench_pin =
    GPIO_DT_SPEC_GET(BENCH_LED_NODE, gpios);

static bench_sample_t samples_t1[BENCH_ITERATIONS];
static bench_sample_t samples_t2[BENCH_ITERATIONS];

/* Implementazione del putchar usato da benchmark_stats.c.
 * Su Zephyr usiamo printk() con %c (non bloccante per default,
 * ma sufficiente per il nostro output. */
void bench_putchar(char c)
{
    printk("%c", c);
}

int main(void)
{
    /* Cache OFF su Cortex-M7 per parita' con altri RTOS */
    SCB_DisableICache();
    SCB_DisableDCache();

    /* DWT init */
    dwt_init();

    /* GPIO test pin */
    if (!device_is_ready(bench_pin.port)) {
        printk("ERR: bench pin GPIO not ready\n");
        return -1;
    }
    gpio_pin_configure_dt(&bench_pin, GPIO_OUTPUT_INACTIVE);

    /* Banner */
    printk("\r\n");
    printk("==========================================\r\n");
    printk("  RTOS Benchmark - Zephyr edition\r\n");
    printk("  Board: NUCLEO-H743ZI2 @ 480 MHz\r\n");
    printk("  Iterations per test: %u\r\n", BENCH_ITERATIONS);
    printk("==========================================\r\n");

    uint32_t overhead = dwt_measure_overhead();
    {
        bench_stats_t s = {.min_cycles = overhead, .max_cycles = overhead,
                           .mean_cycles = overhead, .stddev_cycles = 0,
                           .p99_9_cycles = overhead, .outliers_above_3sigma = 0};
        bench_print_stats("dwt_baseline", &s);
    }

    bench_print_csv_header();

    /* Test T1 */
    bench_t1_setup();
    bench_t1_run(samples_t1);
    {
        bench_stats_t stats;
        bench_compute_stats(samples_t1, BENCH_ITERATIONS, &stats);
        bench_print_stats("ctxsw_irq", &stats);
    }
    bench_print_csv("ctxsw_irq", samples_t1, BENCH_ITERATIONS);

    /* Test T2 */
    bench_t2_setup();
    bench_t2_run(samples_t2);
    {
        bench_stats_t stats;
        bench_compute_stats(samples_t2, BENCH_ITERATIONS, &stats);
        bench_print_stats("ctxsw_mutex", &stats);
    }
    bench_print_csv("ctxsw_mutex", samples_t2, BENCH_ITERATIONS);

    printk("\r\n=== BENCHMARK COMPLETE ===\r\n");

    while (1) {
        gpio_pin_toggle_dt(&bench_pin);
        k_msleep(500);
    }
    return 0;
}
