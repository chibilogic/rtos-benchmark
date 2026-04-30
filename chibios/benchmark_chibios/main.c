/**
 * @file    main.c
 * @brief   Main del benchmark ChibiOS.
 *          Inizializza HAL+RT, configura clock, lancia i test e
 *          stampa i risultati su USART3 (ST-Link VCP).
 */

#include "ch.h"
#include "hal.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

extern void bench_print_csv_header(void);

/* Buffer globali — 10000 sample * 4 byte = 40 KB. Su STM32H743 (1 MB
 * RAM) e' tranquillamente allocabile in BSS. */
static bench_sample_t samples_t1[BENCH_ITERATIONS];
static bench_sample_t samples_t2[BENCH_ITERATIONS];

/* UART di output — su Nucleo-H743ZI2 il VCP e' su USART3. */
#define BENCH_UART  &SD3

/* Implementazione del putchar usato da benchmark_stats.c */
void bench_putchar(char c)
{
    sdPut(BENCH_UART, (uint8_t)c);
}

int main(void)
{
    /* HAL/RT init standard ChibiOS */
    halInit();
    chSysInit();

    /* IMPORTANTE: disabilitiamo le cache per il benchmark.
     * Su Cortex-M7 le cache abilitate causano varianza di misura
     * non legata all'RTOS. Per un confronto pulito, OFF su tutti. */
    SCB_DisableICache();
    SCB_DisableDCache();

    /* DWT cycle counter init — chiave dell'affidabilita' delle misure */
    dwt_init();

    /* USART3 a 115200 8N1 (default ChibiOS sd_lld_config) */
    sdStart(BENCH_UART, NULL);

    /* Pin di test PB0 in output push-pull per validazione oscilloscopio */
    palSetPadMode(GPIOB, 0, PAL_MODE_OUTPUT_PUSHPULL);
    palClearPad(GPIOB, 0);

    /* Banner di avvio */
    bench_putchar('\r'); bench_putchar('\n');
    const char *banner =
        "==========================================\r\n"
        "  RTOS Benchmark - ChibiOS edition\r\n"
        "  Board: NUCLEO-H743ZI2 @ 480 MHz\r\n"
        "  Iterations per test: 10000\r\n"
        "==========================================\r\n";
    while (*banner) bench_putchar(*banner++);

    /* Misura overhead del DWT (per sottrazione successiva) */
    uint32_t overhead = dwt_measure_overhead();
    const char *ov = "DWT read overhead: ";
    while (*ov) bench_putchar(*ov++);
    /* Stampa overhead — riusiamo le funzioni di benchmark_stats */
    {
        bench_stats_t s = {.min_cycles = overhead, .max_cycles = overhead,
                           .mean_cycles = overhead, .stddev_cycles = 0,
                           .p99_9_cycles = overhead, .outliers_above_3sigma = 0};
        bench_print_stats("dwt_baseline", &s);
    }

    /* CSV header */
    bench_print_csv_header();

    /* ----------- Test T1: context switch via IRQ wake-up ----------- */
    bench_t1_setup();
    bench_t1_run(samples_t1);

    {
        bench_stats_t stats;
        bench_compute_stats(samples_t1, BENCH_ITERATIONS, &stats);
        bench_print_stats("ctxsw_irq", &stats);
    }
    bench_print_csv("ctxsw_irq", samples_t1, BENCH_ITERATIONS);

    /* ----------- Test T2: context switch via mutex ----------- */
    bench_t2_setup();
    bench_t2_run(samples_t2);

    {
        bench_stats_t stats;
        bench_compute_stats(samples_t2, BENCH_ITERATIONS, &stats);
        bench_print_stats("ctxsw_mutex", &stats);
    }
    bench_print_csv("ctxsw_mutex", samples_t2, BENCH_ITERATIONS);

    const char *done = "\r\n=== BENCHMARK COMPLETE ===\r\n";
    while (*done) bench_putchar(*done++);

    /* Idle loop con LED lampeggiante per indicare "fatto" */
    while (true) {
        palTogglePad(GPIOB, 0);  /* PB0 LED1 sul Nucleo */
        chThdSleepMilliseconds(500);
    }
}
