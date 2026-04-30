# File di configurazione ChibiOS

I file `chconf.h`, `halconf.h` e `mcuconf.h` non sono inclusi nello
scaffold per evitare di committare codice ChibiOS modificato (fragile
nei merge con submodule).

## Come ottenerli

Dopo aver inizializzato il submodule ChibiOS:

```bash
cd chibios/benchmark_chibios/cfg

# chconf.h dal template RT
cp ../../ChibiOS/os/rt/templates/chconf.h .

# halconf.h dal template HAL
cp ../../ChibiOS/os/hal/templates/halconf.h .

# mcuconf.h specifico per STM32H743 e Nucleo
cp ../../ChibiOS/os/hal/boards/ST_NUCLEO144_H743ZI/cfg/mcuconf.h .
```

## Modifiche obbligatorie per il benchmark

In `chconf.h`:

```c
/* Tick rate identico agli altri RTOS */
#define CH_CFG_ST_FREQUENCY                 1000

/* TimeDelta = 0 -> tickless DISABILITATO (default = on)
 * Se vuoi testare anche modalita' tickless, mettilo a 2 */
#define CH_CFG_ST_TIMEDELTA                 0

/* Priority inheritance ABILITATA (deve coincidere con FreeRTOS+Zephyr) */
#define CH_CFG_USE_MUTEXES_RECURSIVE        TRUE
#define CH_CFG_USE_MUTEXES                  TRUE

/* Stats rilevazioni interne disabilitate (overhead non voluto) */
#define CH_DBG_STATISTICS                   FALSE
#define CH_DBG_SYSTEM_STATE_CHECK           FALSE
#define CH_DBG_ENABLE_CHECKS                FALSE
#define CH_DBG_ENABLE_ASSERTS               FALSE
#define CH_DBG_TRACE_MASK                   CH_DBG_TRACE_MASK_DISABLED
```

In `halconf.h`:

```c
#define HAL_USE_PAL                         TRUE
#define HAL_USE_SERIAL                      TRUE
#define HAL_USE_GPT                         TRUE
/* Tutti gli altri driver: FALSE per minimizzare codice */
```

In `mcuconf.h`:

```c
/* Verifica che TIM2 (usato dal test T1) sia abilitato */
#define STM32_GPT_USE_TIM2                  TRUE

/* USART3 abilitata per VCP */
#define STM32_SERIAL_USE_USART3             TRUE

/* Clock: 480 MHz dal preset standard del Nucleo-H743ZI */
/* (mantieni i valori di default del template) */
```
