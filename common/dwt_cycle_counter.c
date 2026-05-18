/**
 * @file    dwt_cycle_counter.c
 * @brief   DWT cycle counter implementation (BSP-neutral).
 */

#include "dwt_cycle_counter.h"

/* ARM Cortex-M register addresses (valid on M3/M4/M7). */
#define DEMCR_ADDR          (*(volatile uint32_t *)0xE000EDFC)
#define DWT_CTRL_ADDR       (*(volatile uint32_t *)0xE0001000)
#define DWT_CYCCNT_ADDR     (*(volatile uint32_t *)0xE0001004)
#define DWT_LAR_ADDR        (*(volatile uint32_t *)0xE0001FB0)

#define DEMCR_TRCENA_BIT    (1UL << 24)
#define DWT_CTRL_CYCCNTENA  (1UL << 0)
#define DWT_LAR_UNLOCK_KEY  0xC5ACCE55UL

void dwt_init(void)
{
    /* Step 1: enable TRCENA in DEMCR (unlocks the DWT/ITM block). */
    DEMCR_ADDR |= DEMCR_TRCENA_BIT;

    /* Step 2: on some Cortex-M7 cores (incl. STM32H7) the DWT is
     * protected by a Lock Access Register; it must be unlocked
     * explicitly. On M3/M4 this write is a no-op. */
    DWT_LAR_ADDR = DWT_LAR_UNLOCK_KEY;

    /* Step 3: zero the counter. */
    DWT_CYCCNT_ADDR = 0U;

    /* Step 4: enable CYCCNT. */
    DWT_CTRL_ADDR |= DWT_CTRL_CYCCNTENA;
}

uint32_t dwt_measure_overhead(void)
{
    /* Measure the intrinsic overhead of two consecutive DWT
     * reads. Take 1024 samples and return the minimum (ideal
     * case, not disturbed by interrupts). */
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
