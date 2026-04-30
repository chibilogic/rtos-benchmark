/**
 * @file    dwt_cycle_counter.h
 * @brief   Cortex-M DWT cycle counter access for high-precision timing.
 *
 * Il DWT (Data Watchpoint and Trace) e un peripheral hardware presente
 * in tutti i Cortex-M3/M4/M7. Il suo registro CYCCNT incrementa ad
 * ogni ciclo di clock CPU, fornendo una misura COMPLETAMENTE
 * INDIPENDENTE dall'RTOS: questa e' la chiave dell'affidabilita' del
 * benchmark.
 *
 * Su STM32H743 a 480 MHz: 1 ciclo = ~2.083 ns
 * Risoluzione massima ottenibile: ~2 ns
 * Wrap-around: 32 bit -> ~8.95 secondi a 480 MHz (sufficiente per i test)
 *
 * IMPORTANTE: il DWT va abilitato UNA VOLTA all'avvio, prima di tutto.
 */

#ifndef DWT_CYCLE_COUNTER_H
#define DWT_CYCLE_COUNTER_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief   Abilita il DWT cycle counter.
 *          Va chiamata UNA VOLTA in fase di init, prima di qualsiasi
 *          misura. Idempotente.
 */
void dwt_init(void);

/**
 * @brief   Restituisce il valore corrente del cycle counter.
 *          Inline forzato per evitare overhead di chiamata funzione
 *          dentro le sezioni critiche di misura.
 */
static inline uint32_t dwt_get_cycles(void)
{
    /* DWT_CYCCNT register at 0xE0001004 */
    return *((volatile uint32_t *)0xE0001004);
}

/**
 * @brief   Misura in cicli tra due timestamp, gestendo wrap-around.
 *          Dato che CYCCNT e' a 32 bit unsigned, la sottrazione
 *          modulare 2^32 produce sempre il risultato corretto a patto
 *          che l'intervallo sia < 2^32 cicli.
 */
static inline uint32_t dwt_diff(uint32_t start, uint32_t end)
{
    return end - start;  /* unsigned subtraction handles wrap */
}

/**
 * @brief   Calibra l'overhead di lettura del DWT.
 *          Misura il numero di cicli che impiega la sequenza
 *          'start = dwt_get_cycles(); end = dwt_get_cycles();'
 *          Va sottratto dalle misure per ottenere il tempo netto.
 *          Tipicamente 2-4 cicli su Cortex-M7.
 */
uint32_t dwt_measure_overhead(void);

/**
 * @brief   Conversione cicli -> microsecondi.
 *          @param cycles    numero di cicli misurati
 *          @param cpu_hz    frequenza CPU in Hz (es. 480000000)
 *          @return          tempo in microsecondi (float)
 */
static inline float dwt_cycles_to_us(uint32_t cycles, uint32_t cpu_hz)
{
    return ((float)cycles * 1000000.0f) / (float)cpu_hz;
}

#ifdef __cplusplus
}
#endif

#endif /* DWT_CYCLE_COUNTER_H */
