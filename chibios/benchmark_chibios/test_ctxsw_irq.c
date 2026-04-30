/**
 * @file    test_ctxsw_irq.c
 * @brief   T1 — Context switch via IRQ wake-up (ChibiOS).
 *
 * Sequenza misurata:
 *   1. Thread B (basso priorita') gira in idle / yield loop
 *   2. Timer hardware (GPT) genera un IRQ periodico
 *   3. ISR chiama chBSemSignalI() -> sblocca thread A (alta priorita')
 *   4. Thread A si sveglia, legge DWT, sottrae il timestamp salvato
 *      dall'ISR e registra il delta come "wake-up latency"
 *
 * NOTA: il timer ISR salva il proprio timestamp PRIMA di fare signal.
 * Cosi' misuriamo il tempo NETTO scheduler+context-switch, escludendo
 * il jitter del timer stesso.
 *
 * TODO: questo file e' uno SCAFFOLD. Le sezioni marcate con TODO
 * vanno completate (vedi CLAUDE.md per istruzioni).
 */

#include "ch.h"
#include "hal.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

/* Semaforo binario su cui il thread di benchmark si blocca */
static binary_semaphore_t bench_bsem;

/* Timestamp salvato dall'ISR appena prima di fare signal */
static volatile uint32_t isr_timestamp;

/* Indice corrente dell'array di sample (gestito dal thread bench) */
static volatile uint32_t sample_idx;
static bench_sample_t *current_samples;

/* Flag che indica fine test */
static volatile bool test_done;

/* Working area per il thread di benchmark */
static THD_WORKING_AREA(waBenchThread, 512);

/* ------------------------------------------------------------------ */
/* ISR del timer GPT: salva timestamp e sblocca il thread             */
/* ------------------------------------------------------------------ */
static void gpt_callback(GPTDriver *gptp)
{
    (void)gptp;
    /* Misura PRIMA del signal: questo e' lo "start" del cronometro */
    isr_timestamp = dwt_get_cycles();

    chSysLockFromISR();
    chBSemSignalI(&bench_bsem);
    chSysUnlockFromISR();
}

/* Configurazione GPT: usiamo TIM2 a 1 MHz, IRQ ogni 1 ms */
static const GPTConfig gpt_config = {
    .frequency = 1000000U,
    .callback  = gpt_callback,
    .cr2       = 0,
    .dier      = 0
};

/* ------------------------------------------------------------------ */
/* Thread di benchmark: attende signal, misura latenza                */
/* ------------------------------------------------------------------ */
static THD_FUNCTION(benchThread, arg)
{
    (void)arg;
    chRegSetThreadName("bench_t1");

    while (!test_done) {
        /* Si blocca sul semaforo */
        chBSemWait(&bench_bsem);

        /* Appena svegliato: misura il tempo dal signal ISR */
        uint32_t now = dwt_get_cycles();
        uint32_t delta = dwt_diff(isr_timestamp, now);

        /* Toggle GPIO per validazione esterna con oscilloscopio */
        palTogglePad(GPIOB, 0);

        /* Salva il sample */
        if (sample_idx < BENCH_ITERATIONS) {
            current_samples[sample_idx++].cycles = delta;
        } else {
            test_done = true;
        }
    }
}

/* ------------------------------------------------------------------ */
/* API pubblica                                                       */
/* ------------------------------------------------------------------ */

void bench_t1_setup(void)
{
    chBSemObjectInit(&bench_bsem, true);  /* taken */
    sample_idx = 0;
    test_done = false;

    /* Crea il thread di benchmark con priorita' alta (NORMALPRIO+10) */
    chThdCreateStatic(waBenchThread, sizeof(waBenchThread),
                      NORMALPRIO + 10, benchThread, NULL);

    /* Avvia GPT (TIM2) */
    gptStart(&GPTD2, &gpt_config);
}

void bench_t1_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx = 0;
    test_done = false;

    /* Avvia generazione IRQ ogni 1000 us = 1 ms */
    gptStartContinuous(&GPTD2, 1000U);

    /* Attende fine test (busy wait con yield per non bloccare il thread
     * benchmark che ha priorita' superiore) */
    while (!test_done) {
        chThdSleepMilliseconds(10);
    }

    gptStopTimer(&GPTD2);
}
