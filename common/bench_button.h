/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    bench_button.h
 * @brief   USER button (B1) gating for the benchmark sequencer.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * On the STM32H750B-DK, the blue B1 USER button is wired to PC13
 * (the WAKEUP pin). The official ST BSP defines:
 *   BUTTON_USER_PIN       = GPIO_PIN_13
 *   BUTTON_USER_GPIO_PORT = GPIOC
 *   BUTTON_PRESSED        = 1U     (HIGH = pressed)
 *   BUTTON_RELEASED       = 0U
 * and configures the pin with GPIO_PULLDOWN. Pressed therefore
 * means level HIGH on the IDR bit.
 *
 * The polarity above must be physically verified on the actual
 * board before publication (VAL-009).
 *
 * The inline reader uses CMSIS GPIOC->IDR, which is identical in
 * all 3 RTOS ports (ChibiOS stm32_gpio_t and CMSIS GPIO_TypeDef
 * both expose IDR as a plain uint32_t).
 *
 * Polling-only (no EXTI). The function is invoked outside the
 * measured window of any test, so its overhead is irrelevant.
 */

#ifndef BENCH_BUTTON_H
#define BENCH_BUTTON_H

#include <stdbool.h>
#include <stdint.h>

#if defined(BENCH_RTOS_CHIBIOS)
  #include "hal.h"
#elif defined(BENCH_RTOS_FREERTOS)
  #include "stm32h7xx.h"
#elif defined(BENCH_RTOS_ZEPHYR)
  #include <soc.h>
#endif

#define BENCH_USER_BUTTON_PORT            GPIOC
#define BENCH_USER_BUTTON_PIN             13U
#define BENCH_USER_BUTTON_PRESSED_LEVEL   1U

/**
 * @brief   Sample the USER button (B1, PC13) instantaneous state.
 * @return  @p true if the button is currently pressed (level
 *          BENCH_USER_BUTTON_PRESSED_LEVEL on PC13.IDR), @p false
 *          otherwise. No debouncing; the caller is responsible
 *          for press/release filtering.
 *
 * @xclass
 */
static inline bool bench_user_button_is_pressed(void)
{
    uint32_t level =
        (BENCH_USER_BUTTON_PORT->IDR >> BENCH_USER_BUTTON_PIN) & 1U;
    return level == BENCH_USER_BUTTON_PRESSED_LEVEL;
}

#endif /* BENCH_BUTTON_H */
