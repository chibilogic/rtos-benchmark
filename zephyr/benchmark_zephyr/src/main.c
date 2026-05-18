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
 * @file    main.c
 * @brief   Zephyr port main: cache, DWT, GPIO pins, banner, runs the
 *          4 benchmark tests in sequence.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Mirrors the structure of the chibios/freertos main.c. The clock
 * chain (HSE 25 MHz -> SYSCLK 480 MHz) is already configured by the
 * upstream stm32h750b_dk board file at boot, so we do NOT touch it.
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/uart.h>
#include <soc.h>

#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

/* Per-test sample buffers. 11000 samples * 4 B * 4 tests = 176 KB BSS. */
static bench_sample_t samples_t1[BENCH_TOTAL_ITERATIONS];
static bench_sample_t samples_t2[BENCH_TOTAL_ITERATIONS];
static bench_sample_t samples_t3[BENCH_TOTAL_ITERATIONS];
static bench_sample_t samples_t4[BENCH_TOTAL_ITERATIONS];

/* GPIO specs from the device-tree aliases declared in
 * boards/stm32h750b_dk.overlay. PA0 (= A0_HW) has no DT alias:
 * it is hardware-driven by TIM2 OC and configured as alternate
 * function AF1 inside test_ctxsw_irq.c::bench_t1_setup. */
const struct gpio_dt_spec bench_pin_a1 =
    GPIO_DT_SPEC_GET(BENCH_PIN_A1_NODE, gpios);
const struct gpio_dt_spec bench_pin_a2 =
    GPIO_DT_SPEC_GET(BENCH_PIN_A2_NODE, gpios);
const struct gpio_dt_spec bench_pin_a3 =
    GPIO_DT_SPEC_GET(BENCH_PIN_A3_NODE, gpios);
const struct gpio_dt_spec bench_pin_a4 =
    GPIO_DT_SPEC_GET(BENCH_PIN_A4_NODE, gpios);
const struct gpio_dt_spec bench_pin_m =
    GPIO_DT_SPEC_GET(BENCH_PIN_M_NODE,  gpios);

void bench_pins_init(void)
{
    gpio_pin_configure_dt(&bench_pin_a1, GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&bench_pin_a2, GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&bench_pin_a3, GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&bench_pin_a4, GPIO_OUTPUT_INACTIVE);
    gpio_pin_configure_dt(&bench_pin_m,  GPIO_OUTPUT_INACTIVE);

    /* USER button B1 = PC13 (ADR-016). Register-direct setup,
     * coherent with the PA0 / TIM2 init pattern in
     * test_ctxsw_irq.c: we don't want to depend on the Zephyr
     * GPIO/pinctrl scheme for a pin we only poll outside the
     * measured window. Configure as input with pull-down. */
    RCC->AHB4ENR |= RCC_AHB4ENR_GPIOCEN;
    GPIOC->MODER &= ~GPIO_MODER_MODE13;       /* MODE = 00 (input) */
    GPIOC->PUPDR  = (GPIOC->PUPDR & ~GPIO_PUPDR_PUPD13) |
                    (2U << GPIO_PUPDR_PUPD13_Pos);  /* 10 = pull-down */
}

/* putchar over the chosen zephyr,console (= USART3 on the board),
 * used by benchmark_stats.c. */
void bench_putchar(char c)
{
    /* printk routes to the chosen console; using putchar via printk
     * keeps the dependency on a single Zephyr facility. */
    printk("%c", c);
}

/* Idle delay used by bench_wait_user_start() between B1 polls. */
void bench_idle_delay_ms(uint32_t ms)
{
    k_msleep((int32_t)ms);
}

/*===========================================================================*/
/* FLASH_ACR workaround for the Zephyr port (ADR-018).                       */
/*===========================================================================*/

static void apply_flash_acr_workaround(void)
{
    /* STM32CubeH7 LL_SetFlashLatency() has no VOS0 branch for
     * STM32H7_DEV_ID == 0x450 (STM32H750/H743 family). Zephyr's
     * clock_stm32_ll_h7.c switches VOS to SCALE0 before calling
     * LL_SetFlashLatency(240 MHz), so the function falls through
     * to the SCALE3 path, finds no matching HCLK range, returns
     * ERROR and never writes FLASH_ACR. The register keeps the
     * boot-ROM value (LATENCY=2, WRHIGHFREQ=3 = 0x32 observed).
     *
     * Per RM0433 sec.4.3.8 + DS12550, the official setting for
     * VOS0 with HCLK <= 240 MHz is LATENCY=4, WRHIGHFREQ=3 (0x34).
     * ChibiOS and FreeRTOS HAL configure 0x34 through their own
     * routines; we force the same value here so the 3 RTOS ports
     * use identical FLASH timings (constraint #3 of CLAUDE.local).
     *
     * Safe to apply after the clock switch is complete: increasing
     * the wait-state count never causes a flash access violation. */
    uint32_t acr = FLASH->ACR;
    acr &= ~(FLASH_ACR_LATENCY | FLASH_ACR_WRHIGHFREQ);
    acr |=  FLASH_ACR_LATENCY_4WS |
            (3UL << FLASH_ACR_WRHIGHFREQ_Pos);
    FLASH->ACR = acr;
    __DSB();
    __ISB();
    (void)FLASH->ACR;   /* Read-back to commit before next access. */
}

/*===========================================================================*/
/* I+D cache ON (ADR-010).                                                  */
/*===========================================================================*/

static void cache_enable(void)
{
    /* ADR-010 + reviewer #13: idempotent. Zephyr's SoC layer may
     * have enabled the cache already; calling SCB_InvalidateDCache
     * unconditionally would discard any dirty lines (e.g. printk
     * buffer) and corrupt the very early boot output. */
    if ((SCB->CCR & SCB_CCR_IC_Msk) == 0U) {
        SCB_InvalidateICache();
        SCB_EnableICache();
    }
    if ((SCB->CCR & SCB_CCR_DC_Msk) == 0U) {
        SCB_InvalidateDCache();
        SCB_EnableDCache();
    }
}

/*===========================================================================*/
/* Test runner.                                                             */
/*===========================================================================*/

static void run_test(const char *name,
                     const char *metric,
                     void (*setup)(void),
                     void (*run)(bench_sample_t *),
                     bench_sample_t *samples,
                     uint32_t warmup,
                     uint32_t valid)
{
    setup();
    run(samples);

    bench_stats_t stats;
    bench_compute_stats(&samples[warmup], valid, &stats);
    bench_print_stats(name, &stats);
    bench_print_csv(name, metric, samples, warmup, valid);
}

/*===========================================================================*/
/* main.                                                                    */
/*===========================================================================*/

int main(void)
{
    /* ADR-018: force FLASH_ACR = 0x34 before anything else. Zephyr's
     * clock init leaves it at 0x32 because of a CubeH7 LL bug for
     * DEV_ID=0x450 at VOS0. Applied first so cache enable, DWT init,
     * and the banner all see the corrected wait-state value. */
    apply_flash_acr_workaround();

    bench_snapshot_scb_ccr_before();
    cache_enable();
    dwt_init();
    bench_pins_init();

    bench_print_banner();

    /* ADR-017 memory placement audit. */
    bench_print_address_table_begin();
    bench_print_addr("samples_t1", samples_t1);
    bench_print_addr("samples_t2", samples_t2);
    bench_print_addr("samples_t3", samples_t3);
    bench_print_addr("samples_t4", samples_t4);
    bench_t1_print_addresses();
    bench_t2_print_addresses();
    bench_t3_print_addresses();
    bench_t4_print_addresses();
    bench_print_address_table_end();

    bench_print_csv_header();

    /* T1 special-cased: TIM2 state dump after setup and after run
     * (reviewer round-5 #3). Each test gated by B1 (ADR-016). */
    bench_wait_user_start("t1_irq");
    bench_t1_setup();
    bench_print_tim2_state("after_t1_setup");
    bench_t1_run(samples_t1);
    bench_print_tim2_state("after_t1_run");
    {
        bench_stats_t stats;
        bench_compute_stats(&samples_t1[BENCH_WARMUP_ITERATIONS],
                            BENCH_VALID_ITERATIONS, &stats);
        bench_print_stats("t1_irq", &stats);
        bench_print_csv("t1_irq", "dwt_a4_minus_a1",
                        samples_t1,
                        BENCH_WARMUP_ITERATIONS, BENCH_VALID_ITERATIONS);
    }
    bench_wait_user_start("t2_handoff");
    run_test("t2_handoff",    "dwt_thread_to_thread",
             bench_t2_setup, bench_t2_run, samples_t2,
             BENCH_WARMUP_ITERATIONS, BENCH_VALID_ITERATIONS);
    bench_wait_user_start("t3_mtx_uncont");
    run_test("t3_mtx_uncont", "dwt_lock_unlock_pair",
             bench_t3_setup, bench_t3_run, samples_t3,
             BENCH_WARMUP_ITERATIONS, BENCH_VALID_ITERATIONS);
    bench_wait_user_start("t4_mtx_pi");
    run_test("t4_mtx_pi",     "dwt_low_unlock_to_high_acquire",
             bench_t4_setup, bench_t4_run, samples_t4,
             0U, BENCH_T4_RUNS);

    /* PI summary AFTER the T4 stats+CSV so the output stream is linear. */
    bench_print_t4_pi_summary("t4_mtx_pi", bench_t4_get_pi_ok(),
                              BENCH_T4_RUNS);

    printk("\r\n=== BENCHMARK COMPLETE ===\r\n");

    /* Idle loop: slow PH1 toggle to indicate "done". */
    while (1) {
        gpio_pin_toggle_dt(&bench_pin_a1);
        k_msleep(500);
    }

    return 0;
}
