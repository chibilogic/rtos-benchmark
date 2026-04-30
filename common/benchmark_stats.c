/**
 * @file    benchmark_stats.c
 * @brief   Implementazione delle funzioni di analisi statistica e
 *          output CSV. Codice puro C, nessuna dipendenza da RTOS:
 *          compilato e linkato in tutti e tre i progetti.
 */

#include "benchmark_api.h"
#include "dwt_cycle_counter.h"
#include <stdio.h>
#include <math.h>

/* Funzione di output character-by-character, da implementare in
 * ciascun progetto RTOS (puntando alla rispettiva UART). */
extern void bench_putchar(char c);

/* Mini-printf locale per evitare dipendenze su newlib pesanti.
 * Supporta solo %u, %lu, %s, %.3f. Sufficiente per i nostri output. */
static void bench_print_str(const char *s)
{
    while (*s) {
        bench_putchar(*s++);
    }
}

static void bench_print_uint(uint32_t v)
{
    char buf[12];
    int i = 0;
    if (v == 0) {
        bench_putchar('0');
        return;
    }
    while (v > 0) {
        buf[i++] = '0' + (v % 10);
        v /= 10;
    }
    while (i > 0) {
        bench_putchar(buf[--i]);
    }
}

/* Stampa un float con 3 decimali, senza usare printf("%f"). */
static void bench_print_float3(float v)
{
    if (v < 0) {
        bench_putchar('-');
        v = -v;
    }
    uint32_t int_part = (uint32_t)v;
    uint32_t frac_part = (uint32_t)((v - (float)int_part) * 1000.0f + 0.5f);
    bench_print_uint(int_part);
    bench_putchar('.');
    /* Padding zero */
    if (frac_part < 100) bench_putchar('0');
    if (frac_part < 10) bench_putchar('0');
    bench_print_uint(frac_part);
}

void bench_compute_stats(const bench_sample_t *samples,
                        uint32_t count,
                        bench_stats_t *stats)
{
    /* Min, max, sum */
    uint32_t min_v = 0xFFFFFFFFU;
    uint32_t max_v = 0U;
    uint64_t sum = 0;

    for (uint32_t i = 0; i < count; i++) {
        uint32_t v = samples[i].cycles;
        if (v < min_v) min_v = v;
        if (v > max_v) max_v = v;
        sum += v;
    }
    uint32_t mean = (uint32_t)(sum / count);

    /* Stddev (formula Welford-like, ma qui semplificata) */
    uint64_t sq_sum = 0;
    for (uint32_t i = 0; i < count; i++) {
        int32_t d = (int32_t)samples[i].cycles - (int32_t)mean;
        sq_sum += (uint64_t)((int64_t)d * (int64_t)d);
    }
    uint32_t stddev = (uint32_t)sqrtf((float)(sq_sum / count));

    /* p99.9: sortiamo una copia? troppo costoso in RAM/tempo.
     * Approssimazione: contiamo i sample > soglia iterativamente.
     * Per il momento usiamo max_v come proxy del worst-case e
     * documenteremo che il p99.9 va calcolato offline dal CSV. */
    uint32_t p99_9 = max_v;  /* placeholder, calcolato offline da CSV */

    /* Outliers oltre 3-sigma */
    uint32_t outliers = 0;
    uint32_t threshold = mean + 3U * stddev;
    for (uint32_t i = 0; i < count; i++) {
        if (samples[i].cycles > threshold) outliers++;
    }

    stats->min_cycles = min_v;
    stats->max_cycles = max_v;
    stats->mean_cycles = mean;
    stats->stddev_cycles = stddev;
    stats->p99_9_cycles = p99_9;
    stats->outliers_above_3sigma = outliers;
}

void bench_print_stats(const char *test_name, const bench_stats_t *stats)
{
    bench_print_str("\r\n=== Stats for ");
    bench_print_str(test_name);
    bench_print_str(" (");
    bench_print_str(BENCH_RTOS_NAME);
    bench_print_str(") ===\r\n");

    bench_print_str("  min     : ");
    bench_print_uint(stats->min_cycles);
    bench_print_str(" cycles (");
    bench_print_float3(dwt_cycles_to_us(stats->min_cycles, BENCH_CPU_HZ));
    bench_print_str(" us)\r\n");

    bench_print_str("  max     : ");
    bench_print_uint(stats->max_cycles);
    bench_print_str(" cycles (");
    bench_print_float3(dwt_cycles_to_us(stats->max_cycles, BENCH_CPU_HZ));
    bench_print_str(" us)\r\n");

    bench_print_str("  mean    : ");
    bench_print_uint(stats->mean_cycles);
    bench_print_str(" cycles (");
    bench_print_float3(dwt_cycles_to_us(stats->mean_cycles, BENCH_CPU_HZ));
    bench_print_str(" us)\r\n");

    bench_print_str("  stddev  : ");
    bench_print_uint(stats->stddev_cycles);
    bench_print_str(" cycles\r\n");

    bench_print_str("  outliers (>3sigma): ");
    bench_print_uint(stats->outliers_above_3sigma);
    bench_print_str("\r\n");
}

void bench_print_csv(const char *test_name,
                    const bench_sample_t *samples,
                    uint32_t count)
{
    /* Header CSV: lo stampa solo il primo test per evitare duplicati.
     * Convenzione: il main chiama bench_print_csv_header() una volta
     * sola prima del primo test. Vedi sotto. */
    for (uint32_t i = 0; i < count; i++) {
        bench_print_str(BENCH_RTOS_NAME);
        bench_putchar(',');
        bench_print_str(test_name);
        bench_putchar(',');
        bench_print_uint(i + 1);
        bench_putchar(',');
        bench_print_uint(samples[i].cycles);
        bench_putchar(',');
        bench_print_float3(dwt_cycles_to_us(samples[i].cycles,
                                            BENCH_CPU_HZ));
        bench_print_str("\r\n");
    }
}

/* Header CSV — chiamare una volta in main prima del primo test. */
void bench_print_csv_header(void)
{
    bench_print_str("rtos,test_name,iteration,cycles,microseconds\r\n");
}
