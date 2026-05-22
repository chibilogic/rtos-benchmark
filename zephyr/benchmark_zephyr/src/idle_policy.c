/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 *
 * This program is free software: you can redistribute it and/or
 * modify it under the terms of the GNU General Public License as
 * published by the Free Software Foundation, either version 3 of
 * the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program. If not, see
 * <https://www.gnu.org/licenses/>.
 */

/**
 * @file     idle_policy.c
 * @brief    Zephyr ARM idle-hook callback for ADR-024 WFI parity.
 * @author   Edoardo Lombardi elombardi@chibilogic.com
 *
 * @addtogroup BENCHMARK_ZEPHYR
 * @{
 */

/*===========================================================================*/
/* Driver local definitions.                                                 */
/*===========================================================================*/

/*
 * Zephyr v4.4.0 ARM Cortex-M idle path:
 *   kernel/idle.c::idle()              -> calls k_cpu_idle()
 *   arch/arm/core/cortex_m/cpu_idle.c::arch_cpu_idle()
 *     SLEEP_IF_ALLOWED(__WFI)
 *
 * SLEEP_IF_ALLOWED is gated by CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK:
 *   when y, arch_cpu_idle first calls z_arm_on_enter_cpu_idle();
 *   if that returns false, the WFI/WFE instruction is SKIPPED.
 *
 * Per ADR-024:
 *   - fair_perf / debug_dev: ARM_ON_ENTER_CPU_IDLE_HOOK=y in the
 *     per-profile conf; this callback returns false so the idle
 *     path busy-spins (parity with ChibiOS CORTEX_ENABLE_WFI_IDLE
 *     =FALSE and FreeRTOS configUSE_TICKLESS_IDLE=0).
 *   - realistic_tickless: ARM_ON_ENTER_CPU_IDLE_HOOK is absent in
 *     the per-profile conf; the symbol below is NEVER referenced by
 *     the kernel in that build, but is defined unconditionally so
 *     a profile flip does not require source-file edits.
 *
 * Codex PLAN_REVIEW round 6 (handoff
 * 2026-05-22-realistic-tickless-and-fair-perf-wfi-congruence-006)
 * blessed this approach as the supported Zephyr mechanism and the
 * only one that avoids modifying RTOS sources (CLAUDE.local.md
 * hard rule).
 */

/*===========================================================================*/
/* Driver exported variables.                                                */
/*===========================================================================*/

/*===========================================================================*/
/* Driver local types.                                                       */
/*===========================================================================*/

/*===========================================================================*/
/* Driver local variables and types.                                         */
/*===========================================================================*/

/*===========================================================================*/
/* Driver local functions.                                                   */
/*===========================================================================*/

/*===========================================================================*/
/* Driver interrupt handlers.                                                */
/*===========================================================================*/

/*===========================================================================*/
/* Driver exported functions.                                                */
/*===========================================================================*/

#include <stdbool.h>

/**
 * @brief   Zephyr ARM idle-entry hook: refuse WFI/WFE.
 * @details Called by `arch_cpu_idle()` on Cortex-M when
 *          `CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK=y` is selected.
 *          Returning `false` makes `arch_cpu_idle` skip the
 *          `__WFI()` / `__WFE()` instruction so the idle thread
 *          busy-spins. This is the ADR-024 mechanism to bring
 *          Zephyr `fair_perf` and `debug_dev` to parity with
 *          ChibiOS `CORTEX_ENABLE_WFI_IDLE=FALSE` and FreeRTOS
 *          `configUSE_TICKLESS_IDLE=0`.
 *
 * @note    The function is defined unconditionally so a future
 *          profile flip does not require touching this source
 *          file; the symbol is referenced by the kernel only when
 *          the hook Kconfig is enabled.
 *
 * @return  Always `false` (skip WFI).
 *
 * @api
 */
bool z_arm_on_enter_cpu_idle(void) {

    return false;
}

/** @} */
