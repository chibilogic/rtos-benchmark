/**
 * @file    test_ctxsw_mutex.c
 * @brief   T2 — Context switch via mutex contention (ChibiOS).
 *
 * Sequenza misurata:
 *   1. Thread LOW (priorita' bassa) acquisisce il mutex
 *   2. Thread HIGH (priorita' alta) tenta chMtxLock() -> si blocca
 *   3. Thread LOW chiama chMtxUnlock() E SALVA timestamp
 *   4. Lo scheduler sveglia HIGH, che acquisisce il mutex
 *   5. HIGH legge DWT, calcola delta = misura della latenza scheduler
 *
 * Questo test misura il "context switch indotto da release di
 * risorsa contesa", caso classico nei sistemi RT con shared
 * resources. ChibiOS implementa Priority Inheritance Protocol (PIP)
 * di default sui mutex, FreeRTOS opzionale, Zephyr opzionale.
 *
 * IMPORTANTE: tutti e tre i progetti devono abilitare PIP per un
 * confronto equo (vedi chconf.h, FreeRTOSConfig.h, prj.conf).
 */

#include "ch.h"
#include "hal.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static mutex_t bench_mtx;

/* Timestamp salvato da LOW prima di rilasciare */
static volatile uint32_t low_release_timestamp;

static volatile uint32_t sample_idx;
static bench_sample_t *current_samples;
static volatile bool test_done;

/* Sincronizzazione tra HIGH e LOW per la sequenza ordinata */
static binary_semaphore_t high_done_sem;
static binary_semaphore_t low_go_sem;

static THD_WORKING_AREA(waHighThread, 512);
static THD_WORKING_AREA(waLowThread, 512);

/* ------------------------------------------------------------------ */
/* Thread HIGH: si blocca sul mutex, misura il wake-up                */
/* ------------------------------------------------------------------ */
static THD_FUNCTION(highThread, arg)
{
    (void)arg;
    chRegSetThreadName("bench_high");

    while (!test_done) {
        /* Tenta lock — si blocca perche' LOW lo ha gia' */
        chMtxLock(&bench_mtx);

        /* Appena ottenuto il mutex: misura */
        uint32_t now = dwt_get_cycles();
        uint32_t delta = dwt_diff(low_release_timestamp, now);

        palTogglePad(GPIOB, 0);

        if (sample_idx < BENCH_ITERATIONS) {
            current_samples[sample_idx++].cycles = delta;
        } else {
            test_done = true;
        }

        /* Rilascia e segnala a LOW di proseguire */
        chMtxUnlock(&bench_mtx);
        chBSemSignal(&high_done_sem);

        if (test_done) break;
    }
}

/* ------------------------------------------------------------------ */
/* Thread LOW: prende mutex per primo, attende che HIGH si blocchi,   */
/* poi rilascia e misura                                               */
/* ------------------------------------------------------------------ */
static THD_FUNCTION(lowThread, arg)
{
    (void)arg;
    chRegSetThreadName("bench_low");

    while (!test_done) {
        /* Attende il segnale di partenza dal main */
        chBSemWait(&low_go_sem);
        if (test_done) break;

        /* Acquisisce il mutex */
        chMtxLock(&bench_mtx);

        /* Yield per dare a HIGH la chance di mettersi in attesa */
        chThdSleepMicroseconds(50);

        /* Salva timestamp e rilascia. La unlock causera' lo scheduling
         * immediato di HIGH grazie a priority inheritance. */
        low_release_timestamp = dwt_get_cycles();
        chMtxUnlock(&bench_mtx);

        /* Attende che HIGH abbia finito */
        chBSemWait(&high_done_sem);
    }
}

void bench_t2_setup(void)
{
    chMtxObjectInit(&bench_mtx);
    chBSemObjectInit(&high_done_sem, true);  /* taken */
    chBSemObjectInit(&low_go_sem, true);     /* taken */

    sample_idx = 0;
    test_done = false;

    /* HIGH ha priorita' superiore al main (NORMALPRIO) */
    chThdCreateStatic(waHighThread, sizeof(waHighThread),
                      NORMALPRIO + 10, highThread, NULL);

    /* LOW ha priorita' inferiore al main, cosi' main controlla tempistica */
    chThdCreateStatic(waLowThread, sizeof(waLowThread),
                      NORMALPRIO - 10, lowThread, NULL);
}

void bench_t2_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx = 0;
    test_done = false;

    /* Lancia BENCH_ITERATIONS volte la sequenza */
    while (!test_done) {
        chBSemSignal(&low_go_sem);   /* fa partire LOW */
        chThdSleepMilliseconds(1);    /* finestra per completare iterazione */
    }
}
