/**
 * @file    main.c
 * @brief   Main del benchmark FreeRTOS.
 *          Stessa struttura di chibios/main.c per garantire equivalenza.
 */

#include "FreeRTOS.h"
#include "task.h"
#include "stm32h7xx_hal.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

extern void bench_print_csv_header(void);
extern void SystemClock_Config(void);  /* in system_stm32h7xx.c o qui */

static UART_HandleTypeDef huart3;

static bench_sample_t samples_t1[BENCH_ITERATIONS];
static bench_sample_t samples_t2[BENCH_ITERATIONS];

/* Implementazione del putchar usato da benchmark_stats.c */
void bench_putchar(char c)
{
    HAL_UART_Transmit(&huart3, (uint8_t *)&c, 1, HAL_MAX_DELAY);
}

static void uart3_init(void)
{
    huart3.Instance = USART3;
    huart3.Init.BaudRate = 115200;
    huart3.Init.WordLength = UART_WORDLENGTH_8B;
    huart3.Init.StopBits = UART_STOPBITS_1;
    huart3.Init.Parity = UART_PARITY_NONE;
    huart3.Init.Mode = UART_MODE_TX_RX;
    huart3.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart3.Init.OverSampling = UART_OVERSAMPLING_16;
    huart3.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
    huart3.Init.ClockPrescaler = UART_PRESCALER_DIV1;
    huart3.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
    HAL_UART_Init(&huart3);
}

static void gpio_init(void)
{
    __HAL_RCC_GPIOB_CLK_ENABLE();
    GPIO_InitTypeDef cfg = {0};
    cfg.Pin = GPIO_PIN_0;
    cfg.Mode = GPIO_MODE_OUTPUT_PP;
    cfg.Pull = GPIO_NOPULL;
    cfg.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(GPIOB, &cfg);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, GPIO_PIN_RESET);
}

/* Task runner: esegue tutta la sequenza di test */
static void runner_task(void *p)
{
    (void)p;

    /* Banner */
    const char *banner =
        "\r\n==========================================\r\n"
        "  RTOS Benchmark - FreeRTOS edition\r\n"
        "  Board: NUCLEO-H743ZI2 @ 480 MHz\r\n"
        "  Iterations per test: 10000\r\n"
        "==========================================\r\n";
    while (*banner) bench_putchar(*banner++);

    uint32_t overhead = dwt_measure_overhead();
    {
        bench_stats_t s = {.min_cycles = overhead, .max_cycles = overhead,
                           .mean_cycles = overhead, .stddev_cycles = 0,
                           .p99_9_cycles = overhead, .outliers_above_3sigma = 0};
        bench_print_stats("dwt_baseline", &s);
    }

    bench_print_csv_header();

    /* Test T1 */
    bench_t1_setup();
    bench_t1_run(samples_t1);
    {
        bench_stats_t stats;
        bench_compute_stats(samples_t1, BENCH_ITERATIONS, &stats);
        bench_print_stats("ctxsw_irq", &stats);
    }
    bench_print_csv("ctxsw_irq", samples_t1, BENCH_ITERATIONS);

    /* Test T2 */
    bench_t2_setup();
    bench_t2_run(samples_t2);
    {
        bench_stats_t stats;
        bench_compute_stats(samples_t2, BENCH_ITERATIONS, &stats);
        bench_print_stats("ctxsw_mutex", &stats);
    }
    bench_print_csv("ctxsw_mutex", samples_t2, BENCH_ITERATIONS);

    const char *done = "\r\n=== BENCHMARK COMPLETE ===\r\n";
    while (*done) bench_putchar(*done++);

    /* Idle blink */
    while (1) {
        HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_0);
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

int main(void)
{
    HAL_Init();
    SystemClock_Config();   /* TODO: implementare per 480 MHz */

    /* Cache OFF per parita' con ChibiOS/Zephyr */
    SCB_DisableICache();
    SCB_DisableDCache();

    dwt_init();
    uart3_init();
    gpio_init();

    /* Crea il task runner ad alta priorita' */
    xTaskCreate(runner_task, "runner", 2048, NULL,
                configMAX_PRIORITIES - 2, NULL);

    vTaskStartScheduler();

    /* Non si arriva mai qui */
    while (1) {}
}
