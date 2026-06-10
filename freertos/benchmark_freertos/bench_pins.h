/* SPDX-License-Identifier: MIT */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    bench_pins.h
 * @brief   6 GPIO marker pins for the benchmark (ADR-007), FreeRTOS port.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Identical mapping as the ChibiOS / Zephyr ports. Pins (ADR-007):
 *   PA0  STMOD#1   A0_HW (TIM2 CH1 PWM mode 2, hardware-driven)
 *   PH1  STMOD#17  A1 (ISR_ENTRY) / LOW_LOCK
 *   PH4  STMOD#19  A2 (wake start) / HIGH_WAIT
 *   PH8  STMOD#20  A3 (wake done = READY) / LOW_UNLOCK
 *   PH12 STMOD#11  A4 (RUNNING) / HIGH_ACQUIRE
 *   PI11 STMOD#18  MEDIUM_RUN (TEST 4 only)
 *
 * PA0 has NO software set/clear macro: it is driven in hardware
 * by TIM2 channel 1 in PWM mode 2 with CCR1=1 and CC1 IRQ enabled
 * (strada A1 per ADR-014), set up in test_ctxsw_irq.c::
 * bench_t1_setup. It is configured as alternate function AF1 by
 * main.c::bench_pins_init.
 *
 * The 5 software pins use direct BSRR writes to minimise overhead
 * vs HAL_GPIO_WritePin (which performs additional checks). The
 * ChibiOS and Zephyr ports use the same BSRR-direct shape so the
 * marker overhead is identical across the 3 RTOS ports.
 */

#ifndef BENCH_PINS_H
#define BENCH_PINS_H

#include "stm32h7xx_hal.h"

/**
 * @brief   Drive @p pin_mask HIGH on @p port via a single BSRR
 *          write (~3 CPU cycles). Used inside the measured path.
 *
 * @param[in,out] port      GPIO port base (e.g. GPIOH).
 * @param[in]     pin_mask  bitmask of pins to set.
 *
 * @xclass
 */
static inline void bench_pin_set(GPIO_TypeDef *port, uint32_t pin_mask)
{
    port->BSRR = pin_mask;
}

/**
 * @brief   Drive @p pin_mask LOW on @p port via a single BSRR
 *          write (~3 CPU cycles). Used inside the measured path.
 *
 * @param[in,out] port      GPIO port base (e.g. GPIOH).
 * @param[in]     pin_mask  bitmask of pins to clear.
 *
 * @xclass
 */
static inline void bench_pin_clear(GPIO_TypeDef *port, uint32_t pin_mask)
{
    port->BSRR = (uint32_t)pin_mask << 16U;
}

/**
 * @brief   Toggle @p pin_mask on @p port via a single BSRR write.
 *          Set bits that were 0, clear bits that were 1, in one
 *          AHB transaction.
 *
 * @param[in,out] port      GPIO port base (e.g. GPIOH).
 * @param[in]     pin_mask  bitmask of pins to toggle.
 *
 * @xclass
 */
static inline void bench_pin_toggle(GPIO_TypeDef *port, uint32_t pin_mask)
{
    uint32_t odr = port->ODR;
    /* In one BSRR write: set bits that were 0, clear bits that were 1. */
    port->BSRR = ((odr & pin_mask) << 16U) | (~odr & pin_mask);
}

/* Hardware-driven pin (TIM2 CH1 PWM mode 2 on AF1). Reference
 * timestamp. Defined for documentation/init only; no SET/CLR macros. */
#define BENCH_PIN_A0_HW_PORT   GPIOA
#define BENCH_PIN_A0_HW_MASK   GPIO_PIN_0

/* Software-driven markers. Renumbered 2026-05-05: what used to be
 * A0/A1/A2/A3 is now A1/A2/A3/A4 (A0_HW added). */
#define BENCH_PIN_A1_PORT   GPIOH
#define BENCH_PIN_A1_MASK   GPIO_PIN_1
#define BENCH_PIN_A2_PORT   GPIOH
#define BENCH_PIN_A2_MASK   GPIO_PIN_4
#define BENCH_PIN_A3_PORT   GPIOH
#define BENCH_PIN_A3_MASK   GPIO_PIN_8
#define BENCH_PIN_A4_PORT   GPIOH
#define BENCH_PIN_A4_MASK   GPIO_PIN_12
#define BENCH_PIN_M_PORT    GPIOI
#define BENCH_PIN_M_MASK    GPIO_PIN_11

/* Convenience macros (parallel to the ChibiOS port). */
#define BENCH_SET_A1()      bench_pin_set(BENCH_PIN_A1_PORT, BENCH_PIN_A1_MASK)
#define BENCH_CLR_A1()      bench_pin_clear(BENCH_PIN_A1_PORT, BENCH_PIN_A1_MASK)
#define BENCH_SET_A2()      bench_pin_set(BENCH_PIN_A2_PORT, BENCH_PIN_A2_MASK)
#define BENCH_CLR_A2()      bench_pin_clear(BENCH_PIN_A2_PORT, BENCH_PIN_A2_MASK)
#define BENCH_SET_A3()      bench_pin_set(BENCH_PIN_A3_PORT, BENCH_PIN_A3_MASK)
#define BENCH_CLR_A3()      bench_pin_clear(BENCH_PIN_A3_PORT, BENCH_PIN_A3_MASK)
#define BENCH_SET_A4()      bench_pin_set(BENCH_PIN_A4_PORT, BENCH_PIN_A4_MASK)
#define BENCH_CLR_A4()      bench_pin_clear(BENCH_PIN_A4_PORT, BENCH_PIN_A4_MASK)
#define BENCH_SET_M()       bench_pin_set(BENCH_PIN_M_PORT,  BENCH_PIN_M_MASK)
#define BENCH_CLR_M()       bench_pin_clear(BENCH_PIN_M_PORT, BENCH_PIN_M_MASK)

/* TEST 4 aliases (renumbered to point at A1..A4). */
#define BENCH_SET_LOW_LOCK()        BENCH_SET_A1()
#define BENCH_CLR_LOW_LOCK()        BENCH_CLR_A1()
#define BENCH_SET_HIGH_WAIT()       BENCH_SET_A2()
#define BENCH_CLR_HIGH_WAIT()       BENCH_CLR_A2()
#define BENCH_SET_LOW_UNLOCK()      BENCH_SET_A3()
#define BENCH_CLR_LOW_UNLOCK()      BENCH_CLR_A3()
#define BENCH_SET_HIGH_ACQUIRE()    BENCH_SET_A4()
#define BENCH_CLR_HIGH_ACQUIRE()    BENCH_CLR_A4()
#define BENCH_SET_MEDIUM_RUN()      BENCH_SET_M()
#define BENCH_CLR_MEDIUM_RUN()      BENCH_CLR_M()

/**
 * @brief   Configure the 5 software marker pins (PH1, PH4, PH8,
 *          PH12, PI11) as push-pull outputs and the hardware-
 *          driven PA0 as alternate function AF1 (TIM2_CH1).
 *          Idempotent; call once during board bring-up before
 *          any test runs.
 *
 * @init
 */
void bench_pins_init(void);

#endif /* BENCH_PINS_H */
