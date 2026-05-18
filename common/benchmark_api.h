/**
 * @file    benchmark_api.h
 * @brief   Abstract benchmark API, identical across the 3 RTOSes.
 *
 * The 4 tests are defined in ADR-014 (notes/) and are per-iteration
 * adaptations of the official ChibiOS reference tests:
 *   T1 ctxsw_irq      = chThdSuspendS + chThdResumeI (ISR) pattern
 *   T2 thread_handoff = rt_test_012_004 (chSchGoSleepS + chSchWakeupS)
 *   T3 mutex_uncont   = rt_test_012_011 (chMtxLock + chMtxUnlock)
 *   T4 mutex_pi       = rt_test_008_002 (3 threads H/M/L with PI)
 *
 * On FreeRTOS and Zephyr, the tests use the closest semantic
 * equivalent of the ChibiOS primitives (see ADR-014 for the mapping).
 */

#ifndef BENCHMARK_API_H
#define BENCHMARK_API_H

#include <stdint.h>
#include <stdbool.h>

#if defined(__cplusplus)
extern "C" {
#endif

/* ---- Iteration counts (ADR-013) ---- */

/** Samples discarded before stats start (cache warmup). */
#define BENCH_WARMUP_ITERATIONS    1000U

/** Valid samples used for statistics. */
#define BENCH_VALID_ITERATIONS     10000U

/** Total per-test buffer size = warmup + valid. */
#define BENCH_TOTAL_ITERATIONS     (BENCH_WARMUP_ITERATIONS + BENCH_VALID_ITERATIONS)

/**
 * Number of one-shot runs of TEST 4 (mutex_pi). TEST 4 follows the
 * ChibiOS rt_test_008_002 pattern adapted as a one-shot scenario:
 * each run creates a fresh H/M/L scheduling situation, the runner
 * collects 1 latency sample + 1 PI_OK boolean, and starts the next
 * run. With 100 runs of ~110 ms each the test takes ~11 s per RTOS.
 *
 * TEST 4 is exempt from the BENCH_WARMUP_ITERATIONS / BENCH_VALID_-
 * ITERATIONS scheme: PI is deterministic (it works or it does not),
 * so 100 runs are abundant for jitter characterisation. See ADR-013.
 */
#define BENCH_T4_RUNS              100U

/** Declared CPU frequency (must match the runtime value). */
#define BENCH_CPU_HZ               480000000UL

/* AXI SRAM range on STM32H750 (D1 domain, 512 KB cacheable).
 * ADR-017 publication gate: every benchmark-owned object must
 * reside in [BENCH_AXI_SRAM_START, BENCH_AXI_SRAM_END). */
#define BENCH_AXI_SRAM_START       0x24000000UL
#define BENCH_AXI_SRAM_END         0x24080000UL

/* DTCM range (system stacks land here on ChibiOS). Phase 2 scope. */
#define BENCH_DTCM_START           0x20000000UL
#define BENCH_DTCM_END             0x20020000UL

/* ChibiOS NOCACHE region (MPU region 6). Benchmark objects MUST NOT
 * land here; we publish the boundary in the banner for inspection. */
#define BENCH_NOCACHE_START        0x30040000UL
#define BENCH_NOCACHE_END          0x30048000UL

/**
 * Compile-time switch to bypass the USER-button gating before
 * each test (ADR-016). Default OFF: the firmware prints
 * "=== READY <test> ===" and waits for B1 press+release before
 * starting the test, which is what the lab procedure expects.
 *
 * Set to 1 at build time (-DBENCH_AUTORUN=1) for headless smoke
 * tests / CI: the firmware then prints "=== AUTORUN <test> ==="
 * and proceeds without waiting.
 */
#ifndef BENCH_AUTORUN
#define BENCH_AUTORUN              0
#endif

/* ---- RTOS identifier (compile-time) ---- */

#if defined(BENCH_RTOS_CHIBIOS)
    #define BENCH_RTOS_NAME "chibios"
#elif defined(BENCH_RTOS_FREERTOS)
    #define BENCH_RTOS_NAME "freertos"
#elif defined(BENCH_RTOS_ZEPHYR)
    #define BENCH_RTOS_NAME "zephyr"
#else
    #error "Define BENCH_RTOS_<name> in build system"
#endif

/* ---- Profile identifier (ADR-011, compile-time) ---- */

#if defined(BENCH_PROFILE_FAIR_PERF)
    #define BENCH_PROFILE_NAME "fair_perf"
#elif defined(BENCH_PROFILE_REALISTIC_TICKLESS)
    #define BENCH_PROFILE_NAME "realistic_tickless"
#elif defined(BENCH_PROFILE_DEBUG_DEV)
    /* Development-only profile (-Og -g3). Numbers from this profile
     * are NOT publishable and must NOT be compared with the other two.
     * Banner emits a clear warning. */
    #define BENCH_PROFILE_NAME "debug_dev"
#else
    #error "Define BENCH_PROFILE_<name> in build system"
#endif

/* ---- Types ---- */

/**
 * @brief   Raw result of a single test iteration.
 *          4 bytes * 11000 samples = 44 KB per buffer; 4 tests = 176 KB BSS.
 */
typedef struct {
    uint32_t cycles;    /**< CPU cycles measured via DWT. */
} bench_sample_t;

/**
 * @brief   Aggregated statistics after a test run (ADR-013).
 */
typedef struct {
    uint32_t n;              /**< Number of valid samples. */
    uint32_t min_cycles;
    uint32_t max_cycles;
    uint32_t mean_cycles;
    uint32_t stddev_cycles;
    uint32_t median_cycles;  /**< p50. */
    uint32_t p95_cycles;
    uint32_t p99_cycles;
    uint32_t jitter_cycles;  /**< max - min. */
} bench_stats_t;

/* ---- TEST 1: IRQ -> thread latency ---- */
/**
 * @brief   Set up TEST 1 (IRQ -> thread). Creates the target
 *          thread, initialises TIM2 in PWM mode 2 with CC1 IRQ.
 *
 * @api
 */
void bench_t1_setup(void);
/**
 * @brief   Run TEST 1: 1000 warmup + 10000 valid samples of
 *          ISR-to-thread latency. Fills @p samples.
 *
 * @param[out] samples buffer of BENCH_TOTAL_ITERATIONS entries
 *
 * @api
 */
void bench_t1_run(bench_sample_t *samples);

/* ---- TEST 2: thread handoff latency ---- */
/**
 * @brief   Set up TEST 2 (thread-to-thread handoff). Creates
 *          two equal-priority threads and their synchronisation
 *          objects.
 *
 * @api
 */
void bench_t2_setup(void);
/**
 * @brief   Run TEST 2: 1000 warmup + 10000 valid samples of
 *          thread-to-thread context switch cost via DWT.
 *
 * @param[out] samples buffer of BENCH_TOTAL_ITERATIONS entries
 *
 * @api
 */
void bench_t2_run(bench_sample_t *samples);

/* ---- TEST 3: mutex uncontended lock/unlock ---- */
/**
 * @brief   Set up TEST 3 (uncontended mutex). Creates the
 *          single mutex used for the lock/unlock loop.
 *
 * @api
 */
void bench_t3_setup(void);
/**
 * @brief   Run TEST 3: 1000 warmup + 10000 valid samples of
 *          one lock/unlock pair via DWT.
 *
 * @param[out] samples buffer of BENCH_TOTAL_ITERATIONS entries
 *
 * @api
 */
void bench_t3_run(bench_sample_t *samples);

/* ---- TEST 4: mutex contended + priority inheritance ---- */
/**
 * @brief   Set up TEST 4 (mutex + priority inheritance).
 *          Creates the H/M/L threads and the priority-inherited
 *          mutex.
 *
 * @api
 */
void bench_t4_setup(void);
/**
 * @brief   Run TEST 4: BENCH_T4_RUNS one-shot scenarios. Fills
 *          @p samples (handoff cycles) and the file-scope
 *          pi_ok array (accessible via bench_t4_get_pi_ok()).
 *
 * @param[out] samples buffer of BENCH_T4_RUNS entries
 *
 * @api
 */
void bench_t4_run(bench_sample_t *samples);

/**
 * @brief Returns pointer to the file-scope pi_ok array filled by
 *        bench_t4_run. One byte per run: 1 = sequence "ABC"
 *        observed (PI worked), 0 = otherwise. Length =
 *        BENCH_T4_RUNS. Caller (main) uses this to print the
 *        PI summary AFTER stats + CSV so the output stream is
 *        linear: stats -> CSV -> PI summary.
 *
 * @api
 */
const uint8_t *bench_t4_get_pi_ok(void);

/* ---- Analysis and output ---- */

/**
 * @brief   Compute statistics over a sample range.
 *          Non-mutating: an internal copy is sorted for percentiles.
 *
 * @api
 */
void bench_compute_stats(const bench_sample_t *samples,
                         uint32_t count,
                         bench_stats_t *stats);

/**
 * @brief   Print human-readable stats summary to UART.
 *
 * @api
 */
void bench_print_stats(const char *test_name, const bench_stats_t *stats);

/**
 * @brief   Print CSV with header:
 *          rtos,profile,test_name,metric,phase,iteration,cycles,microseconds
 *          phase in {warmup, valid}; iteration restarts at 1 in each phase.
 *
 *          The @p metric string disambiguates what the cycle count
 *          represents (reviewer round-5 #8). The DWT figure is NOT
 *          always the headline metric of the test. Source
 *          attribution depends on the active publication mode
 *          (ADR-015):
 *
 *            t1_irq        : metric "dwt_a4_minus_a1"
 *                            - Phase 1 (DWT-only, active):
 *                              published headline. Source `DWT`.
 *                              HW-event-to-ISR-entry component
 *                              EXCLUDED.
 *                            - Mode LA (future): software
 *                              validation only; external headline
 *                              is the LA capture of A4 - A0_HW.
 *            t2_handoff    : metric "dwt_thread_to_thread"
 *                            Source `DWT` in both modes.
 *            t3_mtx_uncont : metric "dwt_lock_unlock_pair"
 *                            (includes 1 DWT read-pair overhead)
 *                            Source `DWT` in both modes.
 *            t4_mtx_pi     : metric "dwt_low_unlock_to_high_acquire"
 *                            - Phase 1 (DWT-only, active):
 *                              accessory handoff microbenchmark,
 *                              source `DWT`, reported alongside
 *                              `pi_ok` (primary T4 correctness).
 *                            - Mode LA (future): software
 *                              validation; external accessory is
 *                              the LA delta HIGH_ACQUIRE -
 *                              LOW_UNLOCK with PI waveform as
 *                              supporting evidence.
 *
 *          For TEST 4 (one-shot, no warmup), pass warmup_count=0 and
 *          valid_count=BENCH_T4_RUNS.
 *
 * @api
 */
void bench_print_csv(const char *test_name,
                     const char *metric,
                     const bench_sample_t *samples,
                     uint32_t warmup_count,
                     uint32_t valid_count);

/**
 * @brief   Print TEST 4 priority-inheritance pass/fail summary.
 *          One row per run: rtos,profile,test_name,iteration,pi_ok
 *          where pi_ok = 1 if the run's emit-token sequence == "ABC"
 *          (PI worked), 0 otherwise.
 *
 *          Also prints a one-line aggregate "passed N/M".
 *
 * @api
 */
void bench_print_t4_pi_summary(const char *test_name,
                               const uint8_t *pi_ok,
                               uint32_t count);

/**
 * @brief   Print the CSV header once, before the first test.
 *
 * @api
 */
void bench_print_csv_header(void);

/**
 * @brief   Print the boot config banner. Reads SystemCoreClock,
 *          SCB->CCR, DBGMCU->IDCODE at runtime; reads compile-time
 *          macros for profile/tickless. Call AFTER clock/cache/DWT
 *          init and BEFORE the first test.
 *
 * @api
 */
void bench_print_banner(void);

/**
 * @brief Snapshot SCB->CCR cache bits to the SCB_CCR_before
 *        slot in benchmark_stats.c. Call BEFORE cache_enable()
 *        in main(). The boot banner then reports both the
 *        "before" and "after" cache state, so a future port
 *        that inherits cache from the boot loader is auditable.
 *
 * @init
 */
void bench_snapshot_scb_ccr_before(void);

/**
 * @brief USER-button gating before a test (ADR-016). Prints
 *        "=== READY <test_name> ===" then polls B1 until
 *        press+release+200ms settle. Prints "=== START
 *        <test_name> ===" before returning. Bypassed by
 *        BENCH_AUTORUN=1 at build time.
 *
 * @api
 */
void bench_wait_user_start(const char *test_name);

/**
 * @brief RTOS-specific idle sleep. Implemented per-RTOS in
 *        main.c (chThdSleepMilliseconds / vTaskDelay /
 *        k_msleep). Used by bench_wait_user_start() to yield
 *        the CPU between B1 polls.
 *
 * @api
 */
void bench_idle_delay_ms(uint32_t ms);

/* ---- ADR-017: memory placement runtime audit ---- */

/**
 * @brief   Print one "bench_addr <name> : 0x<addr>  <STATUS>" row
 *          where STATUS is AXI_SRAM_OK / DTCM_WARN / NOCACHE_FAIL /
 *          OTHER_FAIL / INFO depending on the address range
 *          (ADR-017 publication gate).
 *
 * @api
 */
void bench_print_addr(const char *name, const void *p);

/**
 * @brief   Header / footer of the per-run memory placement block.
 *          Called by main.c around the per-test print_addresses
 *          calls.
 *
 * @api
 */
void bench_print_address_table_begin(void);
void bench_print_address_table_end(void);

/* Per-test address dumps. Each test_*.c implements its own
 * function and prints only its file-local static objects.
 * Sample arrays are owned by main.c and printed there. */

/** @brief Print bench_addr rows for TEST 1 private objects (ADR-017). @api */
void bench_t1_print_addresses(void);
/** @brief Print bench_addr rows for TEST 2 private objects (ADR-017). @api */
void bench_t2_print_addresses(void);
/** @brief Print bench_addr rows for TEST 3 private objects (ADR-017). @api */
void bench_t3_print_addresses(void);
/** @brief Print bench_addr rows for TEST 4 private objects (ADR-017). @api */
void bench_t4_print_addresses(void);

/**
 * @brief   Dump the live TIM2 register state with a caller-supplied
 *          tag. Intended to be called AFTER bench_t1_setup() so the
 *          run manifest can prove TIM2 is in PWM mode 2 + CC1 IRQ
 *          configuration (the boot banner dump happens before
 *          T1 setup and shows zeros).
 *
 *          Tag examples: "after_t1_setup", "after_t1_run".
 *
 * @api
 */
void bench_print_tim2_state(const char *tag);

#if defined(__cplusplus)
}
#endif

#endif /* BENCHMARK_API_H */
