/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    bench_button.c
 * @brief   bench_wait_user_start() implementation.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Sequencing pattern: before each test the firmware prints
 *   === READY <test_name> ===
 *   Arm logic analyzer, then press+release USER button B1.
 * and polls the B1 button until press+release+200ms settle is
 * observed, then prints
 *   === START <test_name> ===
 * and returns control. The 200ms settle is OUTSIDE the measured
 * window: it lets the human / button bounce settle and the LA
 * arm before the test actually begins.
 *
 * The whole gating mechanism can be bypassed at compile time by
 * defining BENCH_AUTORUN=1 (default 0). With AUTORUN enabled the
 * function prints "=== AUTORUN <test_name> ===" and returns
 * immediately. Useful for headless smoke tests / CI.
 *
 * RTOS-agnostic: relies on bench_putchar() and bench_idle_delay_ms()
 * supplied by each per-RTOS main.c.
 */

#include "benchmark_api.h"
#include "bench_button.h"

/* Character output, supplied by the per-RTOS main.c (same as
 * benchmark_stats.c uses). */
extern void bench_putchar(char c);

static void print_str(const char *s)
{
    while (*s) {
        bench_putchar(*s++);
    }
}

void bench_wait_user_start(const char *test_name)
{
    print_str("\r\n=== READY ");
    print_str(test_name);
    print_str(" ===\r\n");
    print_str("Arm logic analyzer, then press+release USER button B1.\r\n");

#if BENCH_AUTORUN
    print_str("=== AUTORUN ");
    print_str(test_name);
    print_str(" ===\r\n");
    return;
#else
    /* Wait for stable press, then for stable release. */
    while (!bench_user_button_is_pressed()) {
        bench_idle_delay_ms(1U);
    }
    bench_idle_delay_ms(50U);   /* debounce */

    while (bench_user_button_is_pressed()) {
        bench_idle_delay_ms(1U);
    }
    bench_idle_delay_ms(200U);  /* settle, NOT measured */

    print_str("=== START ");
    print_str(test_name);
    print_str(" ===\r\n");
#endif
}
