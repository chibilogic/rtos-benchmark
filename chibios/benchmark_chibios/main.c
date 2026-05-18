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
 * @brief   ChibiOS port main: HAL+RT init, cache, DWT, GPIOs, banner,
 *          runs the 4 benchmark tests in sequence.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 */

#include "ch.h"
#include "hal.h"
#include "portab.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

/* Per-test sample buffers. 11000 samples * 4 B * 4 tests = 176 KB BSS. */
static bench_sample_t samples_t1[BENCH_TOTAL_ITERATIONS];
static bench_sample_t samples_t2[BENCH_TOTAL_ITERATIONS];
static bench_sample_t samples_t3[BENCH_TOTAL_ITERATIONS];
static bench_sample_t samples_t4[BENCH_TOTAL_ITERATIONS];

/* Output UART: USART3 = ST-Link VCP on STM32H750B-DK. */
#define BENCH_UART  &SD3

/* 115200 8N1 explicit -- ChibiOS' SERIAL_DEFAULT_BITRATE is 38400,
 * which would garble the VCP stream. The other two ports already
 * configure 115200 explicitly (FreeRTOS HAL_UART_Init,
 * Zephyr device-tree current-speed). */
static const SerialConfig bench_serial_cfg = {
    115200,                 /* speed                 */
    0,                      /* CR1                   */
    USART_CR2_STOP1_BITS,   /* CR2: 1 stop bit       */
    0                       /* CR3                   */
};

/* putchar used by benchmark_stats.c. */
void bench_putchar(char c)
{
    sdPut(BENCH_UART, (uint8_t)c);
}

/* Idle delay used by bench_wait_user_start() between B1 polls. */
void bench_idle_delay_ms(uint32_t ms)
{
    chThdSleepMilliseconds(ms);
}

static void cache_enable(void)
{
    /* ADR-010: I+D cache ON.
     * Idempotent: if the cache is already enabled (e.g. by the
     * boot/SoC layer in a future port), do NOT call
     * SCB_InvalidateDCache because that discards any dirty lines
     * already present and may corrupt early UART/printf buffers. */
    if ((SCB->CCR & SCB_CCR_IC_Msk) == 0U) {
        SCB_InvalidateICache();
        SCB_EnableICache();
    }
    if ((SCB->CCR & SCB_CCR_DC_Msk) == 0U) {
        SCB_InvalidateDCache();
        SCB_EnableDCache();
    }
}

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

int main(void)
{
    halInit();
    chSysInit();

    /* Snapshot SCB->CCR BEFORE cache_enable so the banner can
     * report both "before" and "after" states (reviewer #12). */
    bench_snapshot_scb_ccr_before();

    /* Cache ON (ADR-010). */
    cache_enable();

    dwt_init();

    /* USART3 at 115200 8N1 (explicit; ChibiOS default is 38400). */
    sdStart(BENCH_UART, &bench_serial_cfg);

    /* 5 software-driven test pins on STMod+ P1 (ADR-007), output
     * push-pull, max speed. Reused with different labels between T1
     * and T4 (see bench_pins.h). */
    static const ioline_t sw_pins[] = {
        BENCH_PIN_A1, BENCH_PIN_A2, BENCH_PIN_A3, BENCH_PIN_A4,
        BENCH_PIN_M
    };
    for (size_t i = 0; i < sizeof(sw_pins)/sizeof(sw_pins[0]); i++) {
        palSetLineMode(sw_pins[i],
                       PAL_MODE_OUTPUT_PUSHPULL |
                       PAL_STM32_OSPEED_HIGHEST);
        palClearLine(sw_pins[i]);
    }

    /* PA0 = A0_HW: hardware-driven by TIM2 channel 1 in PWM mode 2
     * with CCR1=1 and CC1 IRQ enabled (strada A1, ADR-014).
     * Configured as alternate function AF1 here; the TIM2 register
     * setup is done in bench_t1_setup. PA0 is inactive in TEST
     * 2/3/4 (CCER.CC1E cleared by bench_t1_run on exit). */
    /* USER button B1 = PC13, input + pull-down (ADR-016). Polling
     * only, no EXTI. Polarity: pressed = HIGH. */
    palSetPadMode(GPIOC, 13U, PAL_MODE_INPUT_PULLDOWN);
    palSetLineMode(BENCH_PIN_A0_HW,
                   PAL_MODE_ALTERNATE(1U) |
                   PAL_STM32_OSPEED_HIGHEST);

    /* portab hook (empty in upstream, reserved for future custom init). */
    portab_setup();

    /* Runtime banner + memory placement audit (ADR-017) +
     * CSV header. */
    bench_print_banner();

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

    /* Run the 4 tests in sequence (ADR-014). T4 is one-shot per
     * ChibiOS rt_test_008_002 pattern: no warmup, BENCH_T4_RUNS valid.
     * Each test is gated by a B1 USER button press (ADR-016). */

    /* T1 is special-cased: dump TIM2 state right after setup and
     * after run so the manifest can prove the live configuration
     * (banner dump runs before setup). */
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

    /* PI summary AFTER the T4 stats+CSV so the output stream is
     * linear: stats -> CSV -> PI rows for each test in turn. */
    bench_print_t4_pi_summary("t4_mtx_pi", bench_t4_get_pi_ok(),
                              BENCH_T4_RUNS);

    bench_putchar('\r'); bench_putchar('\n');
    const char *done = "=== BENCHMARK COMPLETE ===\r\n";
    while (*done) bench_putchar(*done++);

    /* Idle loop: slow PH1 toggle to indicate "done". */
    while (true) {
        palToggleLine(BENCH_PIN_A1);
        chThdSleepMilliseconds(500);
    }
}
