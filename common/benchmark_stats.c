/**
 * @file    benchmark_stats.c
 * @brief   Statistical analysis + CSV output + boot config banner.
 *          Pure C, RTOS-agnostic, shared across the 3 ports.
 *
 * Spec: ADR-013 (notes/).
 */

#include "benchmark_api.h"
#include "dwt_cycle_counter.h"
#include <stdint.h>
#include <stdlib.h>   /* qsort */
#include <math.h>     /* sqrtf */

#if !defined(BENCH_HOST_BUILD)
/* Embedded build: pull CMSIS headers and the per-RTOS hooks. The
 * BENCH_HOST_BUILD guard exposes only bench_compute_stats() to the
 * host unit-test harness (round-8 Item 5), which has no peripheral
 * registers and no UART backend. The compute_stats path is pure C
 * and is identical between host and target builds. */

/* CMSIS — provided by each RTOS through its HAL. */
/* The product label below is the only "human-readable" string we
 * pin in source. The version number always comes from a macro the
 * RTOS itself exposes, so a submodule bump propagates automatically.
 *
 * Why "ChibiOS RT" and not just "ChibiOS": ChibiOS is an ecosystem
 * (RT, OS Library, HAL, NIL, EX...). The 4 benchmark tests exercise
 * the RT kernel APIs (chThdSuspend, chMtxLock, chSchGoSleepS), so
 * the RT subsystem is the one being measured. CH_KERNEL_VERSION is
 * defined in os/rt/include/ch.h and is RT's own version number. */
#if defined(BENCH_RTOS_CHIBIOS)
  #include "hal.h"            /* pulls CMSIS via stm32 headers */
  #include "ch.h"             /* CH_KERNEL_VERSION */
  #define BENCH_RTOS_KERNEL_LABEL  "ChibiOS RT " CH_KERNEL_VERSION
#elif defined(BENCH_RTOS_FREERTOS)
  #include "stm32h7xx.h"
  #include "FreeRTOS.h"
  #include "task.h"           /* tskKERNEL_VERSION_NUMBER */
  #define BENCH_RTOS_KERNEL_LABEL  "FreeRTOS " tskKERNEL_VERSION_NUMBER
#elif defined(BENCH_RTOS_ZEPHYR)
  #include <soc.h>
  #include <zephyr/version.h> /* KERNEL_VERSION_STRING */
  #define BENCH_RTOS_KERNEL_LABEL  "Zephyr " KERNEL_VERSION_STRING
#endif

/* Character output, supplied by the per-RTOS main.c. */
extern void bench_putchar(char c);

/*===========================================================================*/
/* Local mini-formatters (no newlib printf, keeps dependencies light).      */
/*===========================================================================*/

static void bench_print_str(const char *s)
{
    while (*s) {
        bench_putchar(*s++);
    }
}

static void bench_print_uint(uint32_t v)
{
    char buf[12];
    int i = 0;
    if (v == 0) {
        bench_putchar('0');
        return;
    }
    while (v > 0) {
        buf[i++] = (char)('0' + (v % 10U));
        v /= 10U;
    }
    while (i > 0) {
        bench_putchar(buf[--i]);
    }
}

static void bench_print_hex32(uint32_t v)
{
    static const char hex[] = "0123456789abcdef";
    bench_print_str("0x");
    for (int i = 7; i >= 0; i--) {
        bench_putchar(hex[(v >> (i * 4)) & 0xFU]);
    }
}

/* Print a float with 3 decimals, no printf("%f"). */
static void bench_print_float3(float v)
{
    if (v < 0.0f) {
        bench_putchar('-');
        v = -v;
    }
    uint32_t int_part  = (uint32_t)v;
    uint32_t frac_part = (uint32_t)((v - (float)int_part) * 1000.0f + 0.5f);
    bench_print_uint(int_part);
    bench_putchar('.');
    if (frac_part < 100U) bench_putchar('0');
    if (frac_part < 10U)  bench_putchar('0');
    bench_print_uint(frac_part);
}

#endif /* !BENCH_HOST_BUILD (formatters and CMSIS dependencies) */

/*===========================================================================*/
/* Statistics.                                                              */
/*===========================================================================*/

/* Static sort buffer reused across tests (one test at a time). */
static uint32_t sort_buf[BENCH_VALID_ITERATIONS];

static int cmp_u32(const void *a, const void *b)
{
    uint32_t va = *(const uint32_t *)a;
    uint32_t vb = *(const uint32_t *)b;
    if (va < vb) return -1;
    if (va > vb) return  1;
    return 0;
}

void bench_compute_stats(const bench_sample_t *samples,
                         uint32_t count,
                         bench_stats_t *stats)
{
    /* Pass 1: min, max, sum, copy into sort buffer. */
    uint32_t min_v = 0xFFFFFFFFU;
    uint32_t max_v = 0U;
    uint64_t sum   = 0U;

    for (uint32_t i = 0; i < count; i++) {
        uint32_t v = samples[i].cycles;
        if (v < min_v) min_v = v;
        if (v > max_v) max_v = v;
        sum += v;
        sort_buf[i] = v;
    }
    uint32_t mean = (uint32_t)(sum / count);

    /* Pass 2: stddev. */
    uint64_t sq_sum = 0U;
    for (uint32_t i = 0; i < count; i++) {
        int32_t d = (int32_t)samples[i].cycles - (int32_t)mean;
        sq_sum += (uint64_t)((int64_t)d * (int64_t)d);
    }
    uint32_t stddev = (uint32_t)sqrtf((float)(sq_sum / count));

    /* Sort the copy for exact percentiles. */
    qsort(sort_buf, count, sizeof(uint32_t), cmp_u32);

    uint32_t median = sort_buf[count / 2U];
    uint32_t p95    = sort_buf[(uint64_t)count * 95U / 100U];
    uint32_t p99    = sort_buf[(uint64_t)count * 99U / 100U];

    stats->n             = count;
    stats->min_cycles    = min_v;
    stats->max_cycles    = max_v;
    stats->mean_cycles   = mean;
    stats->stddev_cycles = stddev;
    stats->median_cycles = median;
    stats->p95_cycles    = p95;
    stats->p99_cycles    = p99;
    stats->jitter_cycles = max_v - min_v;
}

#if !defined(BENCH_HOST_BUILD)
/*===========================================================================*/
/* Human-readable output.                                                   */
/*===========================================================================*/

static void print_field(const char *label, uint32_t cycles)
{
    bench_print_str("  ");
    bench_print_str(label);
    bench_print_uint(cycles);
    bench_print_str(" cycles (");
    bench_print_float3(dwt_cycles_to_us(cycles, BENCH_CPU_HZ));
    bench_print_str(" us)\r\n");
}

void bench_print_stats(const char *test_name, const bench_stats_t *stats)
{
    bench_print_str("\r\n=== Stats for ");
    bench_print_str(test_name);
    bench_print_str(" (");
    bench_print_str(BENCH_RTOS_NAME);
    bench_print_str(", ");
    bench_print_str(BENCH_PROFILE_NAME);
    bench_print_str(") ===\r\n");

    bench_print_str("  n         : ");
    bench_print_uint(stats->n);
    bench_print_str("\r\n");

    print_field("min       : ", stats->min_cycles);
    print_field("median    : ", stats->median_cycles);
    print_field("mean      : ", stats->mean_cycles);
    print_field("p95       : ", stats->p95_cycles);
    print_field("p99       : ", stats->p99_cycles);
    print_field("max       : ", stats->max_cycles);
    print_field("jitter    : ", stats->jitter_cycles);

    bench_print_str("  stddev    : ");
    bench_print_uint(stats->stddev_cycles);
    bench_print_str(" cycles\r\n");
}

/*===========================================================================*/
/* CSV.                                                                     */
/*===========================================================================*/

void bench_print_csv_header(void)
{
    bench_print_str("rtos,profile,test_name,metric,phase,iteration,cycles,microseconds\r\n");
}

static void csv_row(const char *test_name, const char *metric,
                    const char *phase,
                    uint32_t iter_in_phase, uint32_t cycles)
{
    bench_print_str(BENCH_RTOS_NAME);
    bench_putchar(',');
    bench_print_str(BENCH_PROFILE_NAME);
    bench_putchar(',');
    bench_print_str(test_name);
    bench_putchar(',');
    bench_print_str(metric);
    bench_putchar(',');
    bench_print_str(phase);
    bench_putchar(',');
    bench_print_uint(iter_in_phase);
    bench_putchar(',');
    bench_print_uint(cycles);
    bench_putchar(',');
    bench_print_float3(dwt_cycles_to_us(cycles, BENCH_CPU_HZ));
    bench_print_str("\r\n");
}

void bench_print_csv(const char *test_name,
                     const char *metric,
                     const bench_sample_t *samples,
                     uint32_t warmup_count,
                     uint32_t valid_count)
{
    /* Phase 1: warmup (iter 1..warmup_count). */
    for (uint32_t i = 0; i < warmup_count; i++) {
        csv_row(test_name, metric, "warmup", i + 1U, samples[i].cycles);
    }

    /* Phase 2: valid (iter 1..valid_count, buffer index
     * warmup_count..warmup_count+valid_count-1). */
    for (uint32_t i = 0; i < valid_count; i++) {
        csv_row(test_name, metric, "valid", i + 1U,
                samples[warmup_count + i].cycles);
    }
}

/*===========================================================================*/
/* TEST 4 priority-inheritance pass/fail summary.                           */
/*===========================================================================*/

void bench_print_t4_pi_summary(const char *test_name,
                               const uint8_t *pi_ok,
                               uint32_t count)
{
    uint32_t passed = 0U;
    for (uint32_t i = 0; i < count; i++) {
        if (pi_ok[i]) {
            passed++;
        }
    }

    /* Aggregate line. */
    bench_print_str("\r\n=== PI summary for ");
    bench_print_str(test_name);
    bench_print_str(" (");
    bench_print_str(BENCH_RTOS_NAME);
    bench_print_str(", ");
    bench_print_str(BENCH_PROFILE_NAME);
    bench_print_str(") ===\r\n");
    bench_print_str("  PI passed   : ");
    bench_print_uint(passed);
    bench_print_str(" / ");
    bench_print_uint(count);
    bench_print_str("\r\n");

    /* Per-run rows. */
    for (uint32_t i = 0; i < count; i++) {
        bench_print_str(BENCH_RTOS_NAME);
        bench_putchar(',');
        bench_print_str(BENCH_PROFILE_NAME);
        bench_putchar(',');
        bench_print_str(test_name);
        bench_putchar(',');
        bench_print_uint(i + 1U);
        bench_putchar(',');
        bench_putchar(pi_ok[i] ? '1' : '0');
        bench_print_str("\r\n");
    }
}

/*===========================================================================*/
/* Boot config banner (runtime dump).                                       */
/*===========================================================================*/

extern uint32_t SystemCoreClock;   /* CMSIS, supplied by the 3 RTOSes */

/* Snapshot of SCB->CCR captured BEFORE cache_enable() runs.
 * Initialised to 0xFFFFFFFFU as a "not snapshotted" sentinel; if
 * the application calls bench_snapshot_scb_ccr_before() before
 * cache_enable() the banner reports both before and after states.
 * Useful when a future port inherits cache enablement from a
 * boot loader (reviewer round-5 #12). */
static uint32_t scb_ccr_before = 0xFFFFFFFFU;

void bench_snapshot_scb_ccr_before(void)
{
    scb_ccr_before = SCB->CCR;
}

void bench_print_banner(void)
{
    bench_print_str("\r\n==========================================\r\n");
    bench_print_str("  RTOS Benchmark\r\n");

    bench_print_str("  RTOS         : ");
    bench_print_str(BENCH_RTOS_NAME);
    bench_print_str("\r\n");

    /* Kernel label = product name + version. The version part is
     * NEVER hardcoded: it comes from the RTOS-side macro selected
     * in the BENCH_RTOS_KERNEL_LABEL definition above
     * (CH_KERNEL_VERSION / tskKERNEL_VERSION_NUMBER /
     * KERNEL_VERSION_STRING). Bumping a submodule pin is enough to
     * update this line — no source edit required. */
    bench_print_str("  RTOS kernel  : ");
    bench_print_str(BENCH_RTOS_KERNEL_LABEL);
    bench_print_str("\r\n");

    bench_print_str("  Profile      : ");
    bench_print_str(BENCH_PROFILE_NAME);
    bench_print_str("\r\n");

    bench_print_str("  Board        : STM32H750B-DK\r\n");

    /* DBGMCU->IDCODE: low 12 bits = device id, high 16 bits = REV_ID */
    uint32_t idcode = DBGMCU->IDCODE;
    bench_print_str("  DBGMCU IDCODE: ");
    bench_print_hex32(idcode);
    bench_print_str("\r\n");

    bench_print_str("  SystemClock  : ");
    bench_print_uint(SystemCoreClock);
    bench_print_str(" Hz\r\n");

    uint32_t ccr = SCB->CCR;
    if (scb_ccr_before != 0xFFFFFFFFU) {
        bench_print_str("  SCB->CCR pre : ");
        bench_print_hex32(scb_ccr_before);
        bench_print_str("\r\n");
    }
    bench_print_str("  SCB->CCR     : ");
    bench_print_hex32(ccr);
    bench_print_str("\r\n");

    bench_print_str("  ICache       : ");
    bench_print_str((ccr & SCB_CCR_IC_Msk) ? "ON\r\n" : "OFF\r\n");
    bench_print_str("  DCache       : ");
    bench_print_str((ccr & SCB_CCR_DC_Msk) ? "ON\r\n" : "OFF\r\n");

    /* Clock-tree / power / flash register dump (ADR-013).
     * These registers fully determine the silicon state at runtime;
     * they go in the run manifest for reproducibility. */
    bench_print_str("  RCC_PLLCKSELR: ");
    bench_print_hex32(RCC->PLLCKSELR);
    bench_print_str("\r\n");

    bench_print_str("  RCC_PLLCFGR  : ");
    bench_print_hex32(RCC->PLLCFGR);
    bench_print_str("\r\n");

    bench_print_str("  RCC_PLL1DIVR : ");
    bench_print_hex32(RCC->PLL1DIVR);
    bench_print_str("\r\n");

    bench_print_str("  RCC_D1CFGR   : ");
    bench_print_hex32(RCC->D1CFGR);
    bench_print_str("\r\n");

    bench_print_str("  RCC_D2CFGR   : ");
    bench_print_hex32(RCC->D2CFGR);
    bench_print_str("\r\n");

    bench_print_str("  RCC_D3CFGR   : ");
    bench_print_hex32(RCC->D3CFGR);
    bench_print_str("\r\n");

    bench_print_str("  PWR_D3CR     : ");
    bench_print_hex32(PWR->D3CR);
    bench_print_str("\r\n");

    /* Decode VOS level and VOSRDY from PWR_D3CR (round-8 §2).
     * PWR_D3CR.VOS is bits[15:14]: 11=SCALE0/VOS0, 10=SCALE1,
     * 01=SCALE2, 00=SCALE3. PWR_D3CR.VOSRDY is bit 13 (read-only,
     * 1 = regulator output reached the programmed level). */
    {
        uint32_t pwrd3 = PWR->D3CR;
        const char *vos_label;
        switch ((pwrd3 >> 14) & 0x3U) {
            case 0x3U: vos_label = "VOS0"; break;
            case 0x2U: vos_label = "VOS1"; break;
            case 0x1U: vos_label = "VOS2"; break;
            default:   vos_label = "VOS3"; break;
        }
        bench_print_str("  VOS level    : ");
        bench_print_str(vos_label);
        bench_print_str("\r\n");
        bench_print_str("  VOSRDY       : ");
        bench_print_str(((pwrd3 >> 13) & 0x1U) ? "READY" : "NOT_READY");
        bench_print_str("\r\n");
    }

    bench_print_str("  SYSCFG_PWRCR : ");
    bench_print_hex32(SYSCFG->PWRCR);
    bench_print_str("\r\n");

    bench_print_str("  FLASH_ACR    : ");
    bench_print_hex32(FLASH->ACR);
    bench_print_str("\r\n");

    /* TIM2 register dump. TIM2 is reserved for TEST 1 (CC1 IRQ +
     * PWM mode 2 on PA0 = A0_HW). The dump lets the manifest verify
     * the OC channel is configured as expected and was not silently
     * reset by the GPT/counter driver. */
    bench_print_str("  TIM2_CR1     : ");
    bench_print_hex32(TIM2->CR1);
    bench_print_str("\r\n");
    bench_print_str("  TIM2_DIER    : ");
    bench_print_hex32(TIM2->DIER);
    bench_print_str("\r\n");
    bench_print_str("  TIM2_CCMR1   : ");
    bench_print_hex32(TIM2->CCMR1);
    bench_print_str("\r\n");
    bench_print_str("  TIM2_CCER    : ");
    bench_print_hex32(TIM2->CCER);
    bench_print_str("\r\n");
    bench_print_str("  TIM2_PSC     : ");
    bench_print_hex32(TIM2->PSC);
    bench_print_str("\r\n");
    bench_print_str("  TIM2_ARR     : ");
    bench_print_hex32(TIM2->ARR);
    bench_print_str("\r\n");
    bench_print_str("  TIM2_CCR1    : ");
    bench_print_hex32(TIM2->CCR1);
    bench_print_str("\r\n");

    bench_print_str("  Tickless     : ");
#if defined(BENCH_PROFILE_REALISTIC_TICKLESS)
    bench_print_str("ON\r\n");
    bench_print_str("  WFI in idle  : ON\r\n");
#else
    bench_print_str("OFF\r\n");
    bench_print_str("  WFI in idle  : OFF\r\n");
#endif

    bench_print_str("  Tick rate    : 1000 Hz\r\n");
#if defined(BENCH_PROFILE_DEBUG_DEV)
    bench_print_str("  Optimization : -Og -g3  (DEV PROFILE - numbers NOT for publication)\r\n");
#else
    bench_print_str("  Optimization : -O2  LTO=no\r\n");
#endif
    bench_print_str("  Test pins    : PA0 + PH1/PH4/PH8/PH12 + PI11"
                    "  (STMod+ P1 pins 1/17/19/20/11/18)\r\n");

    bench_print_str("  T1/T2/T3 wm  : ");
    bench_print_uint(BENCH_WARMUP_ITERATIONS);
    bench_print_str(" iter (discarded)\r\n");

    bench_print_str("  T1/T2/T3 valid: ");
    bench_print_uint(BENCH_VALID_ITERATIONS);
    bench_print_str(" iter\r\n");

    bench_print_str("  T4 runs      : ");
    bench_print_uint(BENCH_T4_RUNS);
    bench_print_str(" one-shot scenarios (no warmup, ADR-013 exception)\r\n");

    uint32_t ovh = dwt_measure_overhead();
    bench_print_str("  DWT overhead : ");
    bench_print_uint(ovh);
    bench_print_str(" cycles (");
    bench_print_float3(dwt_cycles_to_us(ovh, BENCH_CPU_HZ));
    bench_print_str(" us)\r\n");

    bench_print_str("==========================================\r\n");
}

/*===========================================================================*/
/* Live TIM2 register dump (reviewer round-5 #3).                           */
/* The banner dump above runs BEFORE bench_t1_setup() and therefore         */
/* reports the reset state (all zeros). main() must call this AFTER         */
/* bench_t1_setup() and AFTER bench_t1_run() so the manifest can            */
/* validate the actual PWM mode 2 + CC1 IRQ configuration.                  */
/*===========================================================================*/

void bench_print_tim2_state(const char *tag)
{
    bench_print_str("\r\n--- TIM2 state (");
    bench_print_str(tag);
    bench_print_str(") ---\r\n");
    bench_print_str("  TIM2_CR1     : "); bench_print_hex32(TIM2->CR1);   bench_print_str("\r\n");
    bench_print_str("  TIM2_DIER    : "); bench_print_hex32(TIM2->DIER);  bench_print_str("\r\n");
    bench_print_str("  TIM2_CCMR1   : "); bench_print_hex32(TIM2->CCMR1); bench_print_str("\r\n");
    bench_print_str("  TIM2_CCER    : "); bench_print_hex32(TIM2->CCER);  bench_print_str("\r\n");
    bench_print_str("  TIM2_PSC     : "); bench_print_hex32(TIM2->PSC);   bench_print_str("\r\n");
    bench_print_str("  TIM2_ARR     : "); bench_print_hex32(TIM2->ARR);   bench_print_str("\r\n");
    bench_print_str("  TIM2_CCR1    : "); bench_print_hex32(TIM2->CCR1);  bench_print_str("\r\n");
    bench_print_str("--- end TIM2 state ---\r\n");
}

/*===========================================================================*/
/* ADR-017 memory placement audit.                                          */
/*===========================================================================*/

void bench_print_addr(const char *name, const void *p)
{
    uintptr_t a = (uintptr_t)p;
    const char *status;

    if (a >= BENCH_AXI_SRAM_START && a < BENCH_AXI_SRAM_END) {
        status = "AXI_SRAM OK";
    } else if (a >= BENCH_DTCM_START && a < BENCH_DTCM_END) {
        status = "DTCM WARN";
    } else if (a >= BENCH_NOCACHE_START && a < BENCH_NOCACHE_END) {
        status = "NOCACHE FAIL";
    } else if (a == 0U) {
        status = "INFO";
    } else {
        status = "OTHER FAIL";
    }

    bench_print_str("  bench_addr  ");
    bench_print_str(name);
    /* Pad to a fixed column so the output is easy to grep. */
    size_t name_len = 0U;
    while (name[name_len] != '\0') {
        name_len++;
    }
    while (name_len < 18U) {
        bench_putchar(' ');
        name_len++;
    }
    bench_print_str(": ");
    bench_print_hex32((uint32_t)a);
    bench_print_str("  ");
    bench_print_str(status);
    bench_print_str("\r\n");
}

void bench_print_address_table_begin(void)
{
    bench_print_str("\r\n--- Benchmark memory placement (ADR-017) ---\r\n");
    /* Print the NOCACHE region boundary as INFO so that the parser
     * always has a reference: any benchmark-owned address that
     * falls in [start, end) is flagged FAIL by bench_print_addr(). */
    bench_print_str("  bench_addr  axi_sram_start    : ");
    bench_print_hex32((uint32_t)BENCH_AXI_SRAM_START);
    bench_print_str("  INFO\r\n");
    bench_print_str("  bench_addr  axi_sram_end      : ");
    bench_print_hex32((uint32_t)BENCH_AXI_SRAM_END);
    bench_print_str("  INFO\r\n");
    bench_print_str("  bench_addr  nocache_start     : ");
    bench_print_hex32((uint32_t)BENCH_NOCACHE_START);
    bench_print_str("  INFO\r\n");
    bench_print_str("  bench_addr  nocache_end       : ");
    bench_print_hex32((uint32_t)BENCH_NOCACHE_END);
    bench_print_str("  INFO\r\n");
}

void bench_print_address_table_end(void)
{
    bench_print_str("--- end memory placement ---\r\n");
}

#endif /* !BENCH_HOST_BUILD (banner / CSV / address table) */
