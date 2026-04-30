# Benchmark ChibiOS

Implementazione del benchmark per ChibiOS/RT su NUCLEO-H743ZI2.

## Setup iniziale

```bash
# Dal root del repo
git submodule add https://github.com/ChibiOS/ChibiOS chibios/ChibiOS
git submodule update --init --recursive

# Copia i file di config (vedi cfg/README.md)
cd chibios/benchmark_chibios/cfg
cp ../../ChibiOS/os/rt/templates/chconf.h .
cp ../../ChibiOS/os/hal/templates/halconf.h .
cp ../../ChibiOS/os/hal/boards/ST_NUCLEO144_H743ZI/cfg/mcuconf.h .
# ... poi modifica come da cfg/README.md
```

## Build

```bash
cd chibios/benchmark_chibios
make -j
```

Output: `build/benchmark_chibios.elf` (e .bin, .hex)

## Flash

```bash
# Con OpenOCD (installato con ChibiStudio o standalone)
openocd -f interface/stlink.cfg -f target/stm32h7x.cfg \
        -c "program build/benchmark_chibios.elf verify reset exit"

# Oppure con st-flash
st-flash --connect-under-reset write build/benchmark_chibios.bin 0x8000000
```

## Connessione UART

Il VCP della ST-Link compare come `/dev/ttyACM0` (Linux) o `COM<n>` (Win).

```bash
# Linux
minicom -D /dev/ttyACM0 -b 115200

# oppure picocom
picocom -b 115200 /dev/ttyACM0
```

## Output atteso

```
==========================================
  RTOS Benchmark - ChibiOS edition
  Board: NUCLEO-H743ZI2 @ 480 MHz
  Iterations per test: 10000
==========================================

DWT read overhead: ...
=== Stats for dwt_baseline (chibios) ===
  min     : 2 cycles (0.004 us)
  ...

rtos,test_name,iteration,cycles,microseconds
chibios,ctxsw_irq,1,142,0.296
chibios,ctxsw_irq,2,140,0.292
...
```

## Note

- `chconf.h`, `halconf.h`, `mcuconf.h` NON sono nel repo (vedi cfg/README.md)
- Cache I/D disabilitate da main.c per misure pulite
- LTO disabilitato per coerenza con FreeRTOS/Zephyr
