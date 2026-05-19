/**
 * @file    dwt_cycle_counter.h
 * @brief   Cortex-M DWT cycle counter access for high-precision timing.
 *
 * The DWT (Data Watchpoint and Trace) is a hardware peripheral present
 * on every Cortex-M3/M4/M7. Its CYCCNT register increments once per
 * CPU clock cycle, providing a measurement that is COMPLETELY
 * INDEPENDENT of the RTOS - the foundation of the benchmark's
 * neutrality.
 *
 * On STM32H750 at 480 MHz: 1 cycle = ~2.083 ns, max resolution ~2 ns.
 * Wrap-around: 32 bits -> ~8.95 s at 480 MHz (sufficient for our tests).
 *
 * IMPORTANT: DWT must be enabled ONCE at startup before any measurement.
 */

#ifndef DWT_CYCLE_COUNTER_H
#define DWT_CYCLE_COUNTER_H

#include <stdint.h>

#if defined(__cplusplus)
extern "C" {
#endif

/**
 * @brief   Enables the DWT cycle counter.
 *          Call ONCE at init, before any measurement. Idempotent.
 *
 * @init
 */
void dwt_init(void);

/**
 * @brief   Returns the current value of the cycle counter.
 *          Forced inline to avoid call overhead inside measured
 *          critical sections.
 *
 * @xclass
 */
static inline uint32_t dwt_get_cycles(void)
{
    /* DWT_CYCCNT register at 0xE0001004 */
    return *((volatile uint32_t *)0xE0001004);
}

/**
 * @brief   Cycle delta between two timestamps, handles wrap-around.
 *          CYCCNT is 32-bit unsigned, so modular subtraction yields
 *          the correct result as long as the interval is < 2^32 cycles.
 *
 * @xclass
 */
static inline uint32_t dwt_diff(uint32_t start, uint32_t end)
{
    return end - start;  /* unsigned subtraction handles wrap */
}

/**
 * @brief   Calibrates the DWT read overhead.
 *          Measures the cycle count of the sequence
 *          'start = dwt_get_cycles(); end = dwt_get_cycles();'.
 *          Subtract from measurements for the net interval.
 *          Typically 2-4 cycles on Cortex-M7.
 *
 * @init
 */
uint32_t dwt_measure_overhead(void);

/**
 * @brief   Convert cycles to microseconds.
 *          @param cycles    measured cycle count
 *          @param cpu_hz    CPU frequency in Hz (e.g. 480000000)
 *          @return          interval in microseconds (float)
 *
 * @xclass
 */
static inline float dwt_cycles_to_us(uint32_t cycles, uint32_t cpu_hz)
{
    return ((float)cycles * 1000000.0f) / (float)cpu_hz;
}

/**
 * @brief   Busy-wait until the calling thread has consumed @p us
 *          microseconds of CPU time. Time slices spent preempted
 *          (gap > preempt_threshold between two consecutive DWT
 *          reads inside this loop) are NOT counted.
 *
 *          Equivalent in spirit to ChibiOS' test_cpu_pulse(), but
 *          self-contained and portable. Used by TEST 4 (rt_test_008_002
 *          one-shot adaptation, ADR-014) to model realistic critical
 *          sections that must not collapse to "wall time" when the
 *          thread is preempted.
 *
 *          @param us        target CPU-time in microseconds
 *          @param cpu_hz    CPU frequency in Hz (e.g. 480000000)
 *
 * @api
 */
static inline void dwt_busy_cpu_pulse_us(uint32_t us, uint32_t cpu_hz)
{
    /* Any inter-iteration delta larger than this is treated as a
     * context switch and excluded from accumulated CPU time.
     * 500 cycles ~= 1 us at 480 MHz; loop body is ~5 cycles, so
     * non-preempted deltas are well below this threshold. */
    const uint32_t preempt_threshold = 500U;
    const uint32_t target_cycles = us * (cpu_hz / 1000000U);
    uint32_t accumulated = 0U;
    uint32_t prev = dwt_get_cycles();
    while (accumulated < target_cycles) {
        uint32_t now = dwt_get_cycles();
        uint32_t delta = now - prev;
        prev = now;
        if (delta < preempt_threshold) {
            accumulated += delta;
        }
    }
}

/**
 * @brief   Same as dwt_busy_cpu_pulse_us, but pulses a marker pin
 *          via the supplied set/clr callbacks inside the busy loop.
 *          Designed for the M thread of TEST 4: MEDIUM_RUN must
 *          actually pulse while M is on the CPU, and stay flat
 *          while M is preempted (the PI proof). The callbacks are
 *          expected to expand to ~3-cycle BSRR writes.
 *
 *          @param us         target CPU-time in microseconds
 *          @param cpu_hz     CPU frequency in Hz
 *          @param marker_set callback called inside the loop body
 *                            to drive the marker pin HIGH
 *          @param marker_clr callback called inside the loop body
 *                            to drive the marker pin LOW
 *
 *          Single helper used identically across the 3 RTOS ports
 *          (reviewer round-5 #5 deduplication). The preempt
 *          threshold is wider than the no-marker version (5000
 *          cycles) because the marker writes + nop padding push
 *          the per-iteration delta higher.
 *
 * @api
 */
static inline void dwt_busy_cpu_pulse_us_marker(uint32_t us,
                                                uint32_t cpu_hz,
                                                void (*marker_set)(void),
                                                void (*marker_clr)(void))
{
    const uint32_t preempt_threshold = 5000U;
    const uint32_t target_cycles = us * (cpu_hz / 1000000U);
    uint32_t accumulated = 0U;
    uint32_t prev = dwt_get_cycles();
    while (accumulated < target_cycles) {
        marker_set();
        for (volatile int i = 0; i < 100; i++) { __asm__ volatile("nop"); }
        marker_clr();
        for (volatile int i = 0; i < 100; i++) { __asm__ volatile("nop"); }
        uint32_t now = dwt_get_cycles();
        uint32_t delta = now - prev;
        prev = now;
        if (delta < preempt_threshold) {
            accumulated += delta;
        }
    }
}

#if defined(__cplusplus)
}
#endif

#endif /* DWT_CYCLE_COUNTER_H */
