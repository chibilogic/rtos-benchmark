/**
 * @file    test_ctxsw_irq.c
 * @brief   T1 — Context switch via IRQ wake-up (FreeRTOS).
 *
 * Replica funzionale del test ChibiOS:
 *   - TIM2 genera IRQ ogni 1 ms
 *   - L'ISR fa xSemaphoreGiveFromISR() su un semaforo binario
 *   - Il task bench attende su xSemaphoreTake() e misura il delta
 */

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include "stm32h7xx_hal.h"
#include "dwt_cycle_counter.h"
#include "benchmark_api.h"

static SemaphoreHandle_t bench_sem;
static TaskHandle_t      bench_task_handle;
static TIM_HandleTypeDef htim2;

static volatile uint32_t isr_timestamp;
static volatile uint32_t sample_idx;
static bench_sample_t   *current_samples;
static volatile bool     test_done;

/* ISR del TIM2 — alias dichiarato in stm32h7xx_it.c.
 * Per minimizzare overhead, calliamo direttamente da li' qui. */
void bench_t1_isr(void)
{
    /* Misura PRIMA del give */
    isr_timestamp = dwt_get_cycles();

    BaseType_t higher_woken = pdFALSE;
    xSemaphoreGiveFromISR(bench_sem, &higher_woken);

    __HAL_TIM_CLEAR_IT(&htim2, TIM_IT_UPDATE);

    portYIELD_FROM_ISR(higher_woken);
}

static void bench_task(void *p)
{
    (void)p;
    while (!test_done) {
        if (xSemaphoreTake(bench_sem, portMAX_DELAY) == pdTRUE) {
            uint32_t now = dwt_get_cycles();
            uint32_t delta = dwt_diff(isr_timestamp, now);

            HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_0);

            if (sample_idx < BENCH_ITERATIONS) {
                current_samples[sample_idx++].cycles = delta;
            } else {
                test_done = true;
            }
        }
    }
    vTaskDelete(NULL);
}

static void tim2_init(void)
{
    __HAL_RCC_TIM2_CLK_ENABLE();
    htim2.Instance = TIM2;
    /* TIM2 clock su STM32H743 = 240 MHz (APB1 timer clock).
     * Vogliamo IRQ ogni 1 ms = 240000 ticks.
     * Prescaler = 239 -> timer @ 1 MHz, period = 1000 -> 1 kHz */
    htim2.Init.Prescaler = 239;
    htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim2.Init.Period = 999;
    htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_Base_Init(&htim2);

    HAL_NVIC_SetPriority(TIM2_IRQn, 6, 0);
    HAL_NVIC_EnableIRQ(TIM2_IRQn);
}

void bench_t1_setup(void)
{
    bench_sem = xSemaphoreCreateBinary();
    sample_idx = 0;
    test_done = false;

    xTaskCreate(bench_task, "bench_t1", 1024, NULL,
                configMAX_PRIORITIES - 1, &bench_task_handle);

    tim2_init();
}

void bench_t1_run(bench_sample_t *samples)
{
    current_samples = samples;
    sample_idx = 0;
    test_done = false;

    HAL_TIM_Base_Start_IT(&htim2);

    while (!test_done) {
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    HAL_TIM_Base_Stop_IT(&htim2);
}
