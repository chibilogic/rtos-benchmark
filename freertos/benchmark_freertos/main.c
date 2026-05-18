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
 * @brief   FreeRTOS port main: HAL init, SystemClock_Config @ 480 MHz
 *          (ADR-008), I+D cache ON (ADR-010), DWT, USART3, 5 test
 *          pins (ADR-007), runtime banner, runner of the 4 tests.
 * @author  Edoardo Lombardi elombardi@chibilogic.com
 *
 * Mirrors the structure of chibios/main.c.
 */

#include "FreeRTOS.h"
#include "task.h"
#include "stm32h7xx_hal.h"
#include "bench_pins.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

/* Per-test sample buffers. 11000 samples * 4 B * 4 tests = 176 KB BSS. */
static bench_sample_t samples_t1[BENCH_TOTAL_ITERATIONS];
static bench_sample_t samples_t2[BENCH_TOTAL_ITERATIONS];
static bench_sample_t samples_t3[BENCH_TOTAL_ITERATIONS];
static bench_sample_t samples_t4[BENCH_TOTAL_ITERATIONS];

static UART_HandleTypeDef huart3;
static TaskHandle_t       runner_task_handle;

/* Static allocation for the runner task (configSUPPORT_DYNAMIC_-
 * ALLOCATION=0). 4*configMINIMAL_STACK_SIZE words = 4 KB stack. */
#define RUNNER_STACK_WORDS    (4U * configMINIMAL_STACK_SIZE)
static StackType_t  runner_task_stack[RUNNER_STACK_WORDS];
static StaticTask_t runner_task_tcb;

/*===========================================================================*/
/* SystemClock_Config: 480 MHz @ VOS0 (ADR-008 Appendix B).                 */
/*===========================================================================*/

static void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    /* Power supply: LDO (board default). */
    HAL_PWREx_ConfigSupply(PWR_LDO_SUPPLY);

    /* Recent HAL exposes scale 0 (overdrive) directly via
     * HAL_PWREx_ControlVoltageScaling, no separate EnableOverDrive
     * step. Wait for VOSRDY before clocking PLL1. */
    HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE0);
    while (!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) { }

    /* HSE 25 MHz + PLL1 5/192/2/15/2 -> SYSCLK = 480 MHz (ADR-008). */
    RCC_OscInitStruct.OscillatorType  = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState        = RCC_HSE_ON;
    RCC_OscInitStruct.HSIState        = RCC_HSI_OFF;
    RCC_OscInitStruct.CSIState        = RCC_CSI_OFF;
    RCC_OscInitStruct.PLL.PLLState    = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource   = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLM        = 5;
    RCC_OscInitStruct.PLL.PLLN        = 192;
    RCC_OscInitStruct.PLL.PLLP        = 2;
    RCC_OscInitStruct.PLL.PLLQ        = 15;
    RCC_OscInitStruct.PLL.PLLR        = 2;
    RCC_OscInitStruct.PLL.PLLFRACN    = 0;
    RCC_OscInitStruct.PLL.PLLVCOSEL   = RCC_PLL1VCOWIDE;
    RCC_OscInitStruct.PLL.PLLRGE      = RCC_PLL1VCIRANGE_2;   /* 4..8 MHz */
    HAL_RCC_OscConfig(&RCC_OscInitStruct);

    RCC_ClkInitStruct.ClockType = (RCC_CLOCKTYPE_SYSCLK |
                                   RCC_CLOCKTYPE_HCLK   |
                                   RCC_CLOCKTYPE_D1PCLK1|
                                   RCC_CLOCKTYPE_PCLK1  |
                                   RCC_CLOCKTYPE_PCLK2  |
                                   RCC_CLOCKTYPE_D3PCLK1);
    RCC_ClkInitStruct.SYSCLKSource    = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.SYSCLKDivider   = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.AHBCLKDivider   = RCC_HCLK_DIV2;
    RCC_ClkInitStruct.APB3CLKDivider  = RCC_APB3_DIV2;
    RCC_ClkInitStruct.APB1CLKDivider  = RCC_APB1_DIV2;
    RCC_ClkInitStruct.APB2CLKDivider  = RCC_APB2_DIV2;
    RCC_ClkInitStruct.APB4CLKDivider  = RCC_APB4_DIV2;
    HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4);
}

/*===========================================================================*/
/* I+D cache ON (ADR-010).                                                  */
/*===========================================================================*/

static void cache_enable(void)
{
    /* ADR-010 + reviewer #13: idempotent. Skip Invalidate if the
     * cache is already on (avoids discarding dirty lines that may
     * exist if a previous boot stage enabled the cache). */
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
/* GPIO init: PH1/PH4/PH8/PH12/PI11 + PB10/PB11 (USART3 VCP).               */
/*===========================================================================*/

void bench_pins_init(void)
{
    GPIO_InitTypeDef gi = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOH_CLK_ENABLE();
    __HAL_RCC_GPIOI_CLK_ENABLE();

    /* 5 software-driven markers (output push-pull, max speed). */
    gi.Mode  = GPIO_MODE_OUTPUT_PP;
    gi.Pull  = GPIO_NOPULL;
    gi.Speed = GPIO_SPEED_FREQ_VERY_HIGH;

    gi.Pin = BENCH_PIN_A1_MASK;  HAL_GPIO_Init(BENCH_PIN_A1_PORT, &gi);
    gi.Pin = BENCH_PIN_A2_MASK;  HAL_GPIO_Init(BENCH_PIN_A2_PORT, &gi);
    gi.Pin = BENCH_PIN_A3_MASK;  HAL_GPIO_Init(BENCH_PIN_A3_PORT, &gi);
    gi.Pin = BENCH_PIN_A4_MASK;  HAL_GPIO_Init(BENCH_PIN_A4_PORT, &gi);
    gi.Pin = BENCH_PIN_M_MASK;   HAL_GPIO_Init(BENCH_PIN_M_PORT,  &gi);

    BENCH_CLR_A1(); BENCH_CLR_A2(); BENCH_CLR_A3(); BENCH_CLR_A4();
    BENCH_CLR_M();

    /* PA0 = A0_HW: alternate function AF1 (TIM2_CH1). The TIM2 OC
     * register setup is done in test_ctxsw_irq.c::bench_t1_setup.
     * ADR-007 + ADR-014. */
    gi.Pin       = BENCH_PIN_A0_HW_MASK;
    gi.Mode      = GPIO_MODE_AF_PP;
    gi.Pull      = GPIO_NOPULL;
    gi.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    gi.Alternate = GPIO_AF1_TIM2;
    HAL_GPIO_Init(BENCH_PIN_A0_HW_PORT, &gi);

    /* USER button B1 = PC13, input + pull-down (ADR-016).
     * Polling only, no EXTI. Polarity: pressed = HIGH (per ST BSP). */
    __HAL_RCC_GPIOC_CLK_ENABLE();
    GPIO_InitTypeDef bgi = {0};
    bgi.Pin   = GPIO_PIN_13;
    bgi.Mode  = GPIO_MODE_INPUT;
    bgi.Pull  = GPIO_PULLDOWN;
    bgi.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOC, &bgi);
}

/*===========================================================================*/
/* USART3 init (ST-Link VCP).                                               */
/*===========================================================================*/

static void usart3_init(void)
{
    GPIO_InitTypeDef gi = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_USART3_CLK_ENABLE();

    /* PB10 = TX, PB11 = RX, AF7 = USART3. */
    gi.Pin       = GPIO_PIN_10 | GPIO_PIN_11;
    gi.Mode      = GPIO_MODE_AF_PP;
    gi.Pull      = GPIO_NOPULL;
    gi.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    gi.Alternate = GPIO_AF7_USART3;
    HAL_GPIO_Init(GPIOB, &gi);

    huart3.Instance        = USART3;
    huart3.Init.BaudRate   = 115200;
    huart3.Init.WordLength = UART_WORDLENGTH_8B;
    huart3.Init.StopBits   = UART_STOPBITS_1;
    huart3.Init.Parity     = UART_PARITY_NONE;
    huart3.Init.Mode       = UART_MODE_TX;
    huart3.Init.HwFlowCtl  = UART_HWCONTROL_NONE;
    huart3.Init.OverSampling = UART_OVERSAMPLING_16;
    HAL_UART_Init(&huart3);
}

/* Polling putchar, used by benchmark_stats.c. */
void bench_putchar(char c)
{
    HAL_UART_Transmit(&huart3, (uint8_t *)&c, 1, HAL_MAX_DELAY);
}

/* Idle delay used by bench_wait_user_start() between B1 polls. */
void bench_idle_delay_ms(uint32_t ms)
{
    vTaskDelay(pdMS_TO_TICKS(ms));
}

/*===========================================================================*/
/* FreeRTOS static-allocation callback (required by                         */
/* configSUPPORT_STATIC_ALLOCATION=1, configSUPPORT_DYNAMIC_ALLOCATION=0).   */
/* Timer task callback NOT needed: configUSE_TIMERS=0.                      */
/*===========================================================================*/

void vApplicationGetIdleTaskMemory(StaticTask_t **ppxIdleTaskTCBBuffer,
                                   StackType_t  **ppxIdleTaskStackBuffer,
                                   uint32_t      *pulIdleTaskStackSize)
{
    static StaticTask_t xIdleTaskTCB;
    static StackType_t  uxIdleTaskStack[configMINIMAL_STACK_SIZE];
    *ppxIdleTaskTCBBuffer   = &xIdleTaskTCB;
    *ppxIdleTaskStackBuffer = uxIdleTaskStack;
    *pulIdleTaskStackSize   = configMINIMAL_STACK_SIZE;
}

/*===========================================================================*/
/* Runner thread.                                                           */
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

static void runner_task(void *arg)
{
    (void)arg;

    bench_print_banner();

    /* ADR-017 memory placement audit. */
    bench_print_address_table_begin();
    bench_print_addr("samples_t1", samples_t1);
    bench_print_addr("samples_t2", samples_t2);
    bench_print_addr("samples_t3", samples_t3);
    bench_print_addr("samples_t4", samples_t4);
    bench_print_addr("runner_tcb",   &runner_task_tcb);
    bench_print_addr("runner_stack", runner_task_stack);
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

    bench_putchar('\r'); bench_putchar('\n');
    const char *done = "=== BENCHMARK COMPLETE ===\r\n";
    while (*done) bench_putchar(*done++);

    while (1) {
        bench_pin_toggle(BENCH_PIN_A1_PORT, BENCH_PIN_A1_MASK);
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

/*===========================================================================*/
/* main.                                                                    */
/*===========================================================================*/

int main(void)
{
    /* Sequence on H7: HAL_Init -> SystemClock_Config -> cache ON ->
     * peripherals. HAL_Init is needed for the IRQ priority grouping. */
    HAL_Init();
    SystemClock_Config();
    bench_snapshot_scb_ccr_before();
    cache_enable();
    dwt_init();
    bench_pins_init();
    usart3_init();

    /* Runner at prio max-2 (= 6); test target tasks live at max-1 (= 7),
     * so Notify/Resume preempts the runner immediately
     * (vTaskNotifyGiveFromISR sets higher_woken=true only for STRICTLY
     * higher prio than the running task). Statically allocated TCB
     * and stack: configSUPPORT_DYNAMIC_ALLOCATION=0. */
    runner_task_handle = xTaskCreateStatic(runner_task, "runner",
                                           RUNNER_STACK_WORDS,
                                           NULL,
                                           configMAX_PRIORITIES - 2,
                                           runner_task_stack,
                                           &runner_task_tcb);

    vTaskStartScheduler();

    /* Never reached. */
    while (1) { }
}
