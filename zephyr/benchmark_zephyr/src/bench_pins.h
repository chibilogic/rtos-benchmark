/* SPDX-License-Identifier: Apache-2.0 */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    bench_pins.h
 * @brief   6 GPIO marker pins for the benchmark (ADR-007), Zephyr port.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Identical mapping as ChibiOS / FreeRTOS ports (ADR-007 + ADR-014):
 *   PA0  STMOD#1   A0_HW (TIM2 CH1 PWM mode 2, hardware-driven)
 *   PH1  STMOD#17  A1 (ISR_ENTRY) / LOW_LOCK
 *   PH4  STMOD#19  A2 (wake start) / HIGH_WAIT
 *   PH8  STMOD#20  A3 (wake done = READY) / LOW_UNLOCK
 *   PH12 STMOD#11  A4 (RUNNING) / HIGH_ACQUIRE
 *   PI11 STMOD#18  MEDIUM_RUN (TEST 4 only)
 *
 * The 5 software pins are still declared via device-tree aliases in
 *   boards/stm32h750b_dk.overlay
 * so that bench_pins_init() can use the Zephyr GPIO driver to set
 * MODER/OSPEED at boot. Inside the measured path however the
 * BENCH_SET_xxx and BENCH_CLR_xxx macros write BSRR directly via CMSIS,
 * matching the ChibiOS and FreeRTOS ports exactly. This eliminates
 * the marker-overhead asymmetry that the gpio_pin_set_dt() function
 * call would otherwise introduce (~50 cycles vs ~3 cycles).
 *
 * PA0 has NO DT alias and NO software set/clear macro: it is driven
 * in hardware by TIM2 channel 1 (PWM mode 2 + CC1 IRQ, strada A1
 * per ADR-014). Its AF1 alternate-function configuration and the
 * TIM2 register setup are done in src/test_ctxsw_irq.c::
 * bench_t1_setup via direct register writes.
 */

#ifndef BENCH_PINS_H
#define BENCH_PINS_H

#include <zephyr/kernel.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <soc.h>     /* CMSIS: GPIOH, GPIOI base addresses */

#define BENCH_PIN_A1_NODE   DT_ALIAS(bench_pin_a1)
#define BENCH_PIN_A2_NODE   DT_ALIAS(bench_pin_a2)
#define BENCH_PIN_A3_NODE   DT_ALIAS(bench_pin_a3)
#define BENCH_PIN_A4_NODE   DT_ALIAS(bench_pin_a4)
#define BENCH_PIN_M_NODE    DT_ALIAS(bench_pin_m)

extern const struct gpio_dt_spec bench_pin_a1;
extern const struct gpio_dt_spec bench_pin_a2;
extern const struct gpio_dt_spec bench_pin_a3;
extern const struct gpio_dt_spec bench_pin_a4;
extern const struct gpio_dt_spec bench_pin_m;

/**
 * @brief   Configure the 5 software marker pins via the Zephyr
 *          GPIO driver (DT spec bench_pin_a1..a4 + bench_pin_m),
 *          plus PA0 in alternate function AF1 (TIM2_CH1) via
 *          direct register writes. Idempotent; call once at
 *          startup.
 *
 * @init
 */
void bench_pins_init(void);

/* Direct-BSRR marker writes. Identical to the ChibiOS and FreeRTOS
 * ports (~3 cycles per call). bench_pins_init() still uses the
 * Zephyr DT/driver path so the pin direction/speed are set
 * coherently with the rest of the system. */
#define BENCH_SET_A1()      (GPIOH->BSRR = (1U << 1))
#define BENCH_CLR_A1()      (GPIOH->BSRR = (1U << (1 + 16)))
#define BENCH_SET_A2()      (GPIOH->BSRR = (1U << 4))
#define BENCH_CLR_A2()      (GPIOH->BSRR = (1U << (4 + 16)))
#define BENCH_SET_A3()      (GPIOH->BSRR = (1U << 8))
#define BENCH_CLR_A3()      (GPIOH->BSRR = (1U << (8 + 16)))
#define BENCH_SET_A4()      (GPIOH->BSRR = (1U << 12))
#define BENCH_CLR_A4()      (GPIOH->BSRR = (1U << (12 + 16)))
#define BENCH_SET_M()       (GPIOI->BSRR = (1U << 11))
#define BENCH_CLR_M()       (GPIOI->BSRR = (1U << (11 + 16)))

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
