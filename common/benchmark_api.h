/**
 * @file    benchmark_api.h
 * @brief   API astratta per i benchmark, identica sui 3 RTOS.
 *
 * Ogni RTOS implementa queste funzioni nel suo file test_*.c usando
 * le proprie API native. Il main.c di ogni RTOS chiama queste funzioni
 * in sequenza identica garantendo confrontabilita'.
 */

#ifndef BENCHMARK_API_H
#define BENCHMARK_API_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Numero di iterazioni per ogni test. Statisticamente robusto. */
#define BENCH_ITERATIONS    10000U

/* Frequenza CPU dichiarata (deve corrispondere a quella reale). */
#define BENCH_CPU_HZ        480000000UL

/**
 * @brief   Identificativo dell'RTOS in uso. Definito a compile-time
 *          dal sistema di build di ciascun progetto.
 *          Usato per produrre la prima colonna del CSV.
 */
#if defined(BENCH_RTOS_CHIBIOS)
    #define BENCH_RTOS_NAME "chibios"
#elif defined(BENCH_RTOS_FREERTOS)
    #define BENCH_RTOS_NAME "freertos"
#elif defined(BENCH_RTOS_ZEPHYR)
    #define BENCH_RTOS_NAME "zephyr"
#else
    #error "Definire BENCH_RTOS_<RTOS> nel sistema di build"
#endif

/**
 * @brief   Risultato grezzo di una singola iterazione di test.
 *          Volutamente piccolo (4 byte) per minimizzare consumo RAM:
 *          10.000 iterazioni * 4 byte = 40 KB, OK su STM32H743 (1 MB RAM).
 */
typedef struct {
    uint32_t cycles;    /**< Cicli CPU misurati via DWT. */
} bench_sample_t;

/**
 * @brief   Statistiche aggregate post-test.
 */
typedef struct {
    uint32_t min_cycles;
    uint32_t max_cycles;
    uint32_t mean_cycles;
    uint32_t stddev_cycles;
    uint32_t p99_9_cycles;     /**< 99.9-percentile, indicatore worst-case */
    uint32_t outliers_above_3sigma;
} bench_stats_t;

/* ------------------------------------------------------------------ */
/*  Test T1: context switch via IRQ wake-up                            */
/* ------------------------------------------------------------------ */
/**
 * @brief   Setup del test T1.
 *          Crea i thread necessari, configura il timer HW per generare
 *          IRQ. Il thread di benchmark si blocca in attesa del signal.
 */
void bench_t1_setup(void);

/**
 * @brief   Esegue BENCH_ITERATIONS volte la sequenza:
 *          - timer HW genera IRQ
 *          - ISR fa il signal sul semaforo/event
 *          - thread di benchmark si sveglia e legge timestamp
 *          - calcola delta e salva in array
 *
 * @param   samples    array pre-allocato di BENCH_ITERATIONS elementi
 */
void bench_t1_run(bench_sample_t *samples);

/* ------------------------------------------------------------------ */
/*  Test T2: context switch via mutex contention                       */
/* ------------------------------------------------------------------ */
/**
 * @brief   Setup del test T2.
 *          Crea due thread (HIGH e LOW priority) che si contendono
 *          un mutex con priority inheritance abilitata.
 */
void bench_t2_setup(void);

/**
 * @brief   Esegue BENCH_ITERATIONS volte la sequenza:
 *          - thread LOW prende il mutex
 *          - thread HIGH tenta di prenderlo, si blocca
 *          - thread LOW rilascia, thread HIGH ottiene il mutex
 *          - misura il tempo dal release al wake-up di HIGH
 */
void bench_t2_run(bench_sample_t *samples);

/* ------------------------------------------------------------------ */
/*  Analisi e output                                                   */
/* ------------------------------------------------------------------ */
/**
 * @brief   Calcola le statistiche su un array di samples.
 */
void bench_compute_stats(const bench_sample_t *samples,
                        uint32_t count,
                        bench_stats_t *stats);

/**
 * @brief   Stampa il riepilogo statistico in formato leggibile.
 *          Output va su UART (USART3 / VCP).
 */
void bench_print_stats(const char *test_name, const bench_stats_t *stats);

/**
 * @brief   Stampa tutte le iterazioni in formato CSV.
 *          Header: rtos,test_name,iteration,cycles,microseconds
 *          Da chiamare solo DOPO che tutti i test sono completati,
 *          per non disturbare le misure.
 */
void bench_print_csv(const char *test_name,
                    const bench_sample_t *samples,
                    uint32_t count);

#ifdef __cplusplus
}
#endif

#endif /* BENCHMARK_API_H */
