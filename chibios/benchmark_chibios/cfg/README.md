# ChibiOS configuration files

The 5 files (`chconf.h`, `halconf.h`, `mcuconf.h`, `portab.c`, `portab.h`)
were cloned 2026-05-04 from:

  chibios/ChibiOS/demos/STM32/RT-STM32-MULTI/cfg/stm32h750xb_discovery/

License: Apache 2.0 (preserved in each file). The ChibiOS copyright
header is intact. The upstream demo is validated on the same hardware
target (STM32H750B-DK) and already contains the 480 MHz PLL chain
required by ADR-008.

## Local modifications

All modifications are "remove unused stuff". Clock/PLL/VOS values are
NOT touched: they are already correct for 480 MHz @ VOS0 on the rev V
silicon mounted on this board.

### chconf.h

  CH_CFG_ST_FREQUENCY        = 1000   /* identical on the 3 RTOSes */
  CH_CFG_ST_TIMEDELTA        = 0      /* tickless OFF for now */
  CH_DBG_STATISTICS          = FALSE  /* no measurement overhead */
  CH_DBG_SYSTEM_STATE_CHECK  = FALSE
  CH_DBG_ENABLE_CHECKS       = FALSE
  CH_DBG_ENABLE_ASSERTS      = FALSE
  CH_DBG_TRACE_MASK          = CH_DBG_TRACE_MASK_DISABLED

### halconf.h

Keep TRUE only the drivers used by the benchmark:
  HAL_USE_PAL, HAL_USE_SERIAL, HAL_USE_GPT.
Set everything else (SPI, I2C, USB, MAC, SDC, etc.) to FALSE to
reduce code size and init time.

### mcuconf.h

Verify:
  STM32_GPT_USE_TIM2         = TRUE   /* used by T1 */
  STM32_SERIAL_USE_USART3    = TRUE   /* ST-Link VCP */

Consider (deferred to a later session, with before/after measurement):
  - disable PLL2 and PLL3 (not needed by the benchmark; would reduce
    init time and supply ripple).
  - disable drivers for unused peripherals (SDMMC, FMC, etc.).
