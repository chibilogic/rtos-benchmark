/**
 * @file    dwt_cycle_counter.c
 * @brief   Implementazione del DWT cycle counter (BSP-neutrale).
 */

#include "dwt_cycle_counter.h"

/* Indirizzi registri ARM Cortex-M (validi su M3/M4/M7) */
#define DEMCR_ADDR          (*(volatile uint32_t *)0xE000EDFC)
#define DWT_CTRL_ADDR       (*(volatile uint32_t *)0xE0001000)
#define DWT_CYCCNT_ADDR     (*(volatile uint32_t *)0xE0001004)
#define DWT_LAR_ADDR        (*(volatile uint32_t *)0xE0001FB0)

#define DEMCR_TRCENA_BIT    (1UL << 24)
#define DWT_CTRL_CYCCNTENA  (1UL << 0)
#define DWT_LAR_UNLOCK_KEY  0xC5ACCE55UL

void dwt_init(void)
{
    /* Step 1: abilita TRCENA in DEMCR (sblocca tutto il blocco DWT/ITM) */
    DEMCR_ADDR |= DEMCR_TRCENA_BIT;

    /* Step 2: su alcuni Cortex-M7 (incluso STM32H7) il DWT e' protetto
     * da un Lock Access Register. Va sbloccato esplicitamente.
     * Su M3/M4 questa scrittura e' innocua. */
    DWT_LAR_ADDR = DWT_LAR_UNLOCK_KEY;

    /* Step 3: azzera il counter */
    DWT_CYCCNT_ADDR = 0U;

    /* Step 4: abilita CYCCNT */
    DWT_CTRL_ADDR |= DWT_CTRL_CYCCNTENA;
}

uint32_t dwt_measure_overhead(void)
{
    /* Misura l'overhead intrinseco di due letture consecutive del DWT.
     * Eseguiamo 1024 misure e restituiamo il minimo (caso ideale,
     * non disturbato da interrupt). */
    uint32_t min_overhead = 0xFFFFFFFFU;
    volatile uint32_t start, end, delta;

    for (int i = 0; i < 1024; i++) {
        start = dwt_get_cycles();
        end = dwt_get_cycles();
        delta = end - start;
        if (delta < min_overhead) {
            min_overhead = delta;
        }
    }

    return min_overhead;
}
