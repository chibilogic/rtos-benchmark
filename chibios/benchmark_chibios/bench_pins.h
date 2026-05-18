/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

/**
 * @file    bench_pins.h
 * @brief   Macros for the 6 test marker pins (ADR-007).
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Pin -> role mapping per test (see ADR-014):
 *
 *   Pin    STMOD#   T1                    T2/T3        T4
 *   PA0    #1       A0_HW (TIM2 CH1 PWM)  -            -
 *   PH1    #17      A1 (ISR_ENTRY)        DWT region   LOW_LOCK
 *   PH4    #19      A2 (wake start)       -            HIGH_WAIT
 *   PH8    #20      A3 (wake done/READY)  -            LOW_UNLOCK
 *   PH12   #11      A4 (THREAD_RUN)       -            HIGH_ACQUIRE
 *   PI11   #18      -                     -            MEDIUM_RUN (PI proof)
 *
 * PA0 is hardware-driven by TIM2 channel 1 in PWM mode 2 with CCR1=1
 * and CC1 IRQ enabled (strada A1 per ADR-014). It does NOT have
 * SET/CLR macros; configuration is in main.c (alternate function AF1)
 * and in test_ctxsw_irq.c (TIM2 register setup).
 *
 * The other 5 pins are software-driven via direct BSRR writes
 * (single AHB cycle, ~3 cycles total). The PAL_LINE constants are
 * kept for use by main.c's palSetLineMode() during pin init only;
 * inside the measured path always use the BENCH_SET_xxx and
 * BENCH_CLR_xxx macros so that the marker overhead is identical
 * to FreeRTOS and Zephyr (BSRR-direct in all 3 ports).
 */

#ifndef BENCH_PINS_H
#define BENCH_PINS_H

#include "hal.h"

/* PAL_LINE constants for pin init (palSetLineMode in main.c). */
#define BENCH_PIN_A0_HW PAL_LINE(GPIOA, 0U)
#define BENCH_PIN_A1    PAL_LINE(GPIOH, 1U)
#define BENCH_PIN_A2    PAL_LINE(GPIOH, 4U)
#define BENCH_PIN_A3    PAL_LINE(GPIOH, 8U)
#define BENCH_PIN_A4    PAL_LINE(GPIOH, 12U)
#define BENCH_PIN_M     PAL_LINE(GPIOI, 11U)

/* Aliases for TEST 4 (same physical pins, different semantic). */
#define BENCH_PIN_LOW_LOCK       BENCH_PIN_A1
#define BENCH_PIN_HIGH_WAIT      BENCH_PIN_A2
#define BENCH_PIN_LOW_UNLOCK     BENCH_PIN_A3
#define BENCH_PIN_HIGH_ACQUIRE   BENCH_PIN_A4
#define BENCH_PIN_MEDIUM_RUN     BENCH_PIN_M

/* Direct-BSRR marker writes for the measured path. Identical
 * code shape across the 3 RTOS ports (~3 cycles per call).
 *
 * NOTE: ChibiOS HAL redefines GPIO_TypeDef as stm32_gpio_t with
 * BSRR as a union { uint32_t W; struct {uint16_t set, clear;} H; }.
 * We use the .W accessor; the resulting assembly is identical to
 * the plain `port->BSRR = mask` form in FreeRTOS/Zephyr. */
#define BENCH_SET_A1()      (GPIOH->BSRR.W = (1U << 1))
#define BENCH_CLR_A1()      (GPIOH->BSRR.W = (1U << (1 + 16)))
#define BENCH_SET_A2()      (GPIOH->BSRR.W = (1U << 4))
#define BENCH_CLR_A2()      (GPIOH->BSRR.W = (1U << (4 + 16)))
#define BENCH_SET_A3()      (GPIOH->BSRR.W = (1U << 8))
#define BENCH_CLR_A3()      (GPIOH->BSRR.W = (1U << (8 + 16)))
#define BENCH_SET_A4()      (GPIOH->BSRR.W = (1U << 12))
#define BENCH_CLR_A4()      (GPIOH->BSRR.W = (1U << (12 + 16)))
#define BENCH_SET_M()       (GPIOI->BSRR.W = (1U << 11))
#define BENCH_CLR_M()       (GPIOI->BSRR.W = (1U << (11 + 16)))

/* TEST 4 aliases. */
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

#endif /* BENCH_PINS_H */
