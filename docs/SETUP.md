# Setup Guide

Procedura completa per portare il progetto da zero a "primo benchmark".

## 1. Toolchain

### Compilatore ARM (necessario a tutti e tre)

```bash
# Ubuntu/Debian
sudo apt install gcc-arm-none-eabi gdb-multiarch openocd

# Verifica versione (deve essere 13.x per coerenza)
arm-none-eabi-gcc --version
```

### CMake e Ninja (per FreeRTOS e Zephyr)

```bash
sudo apt install cmake ninja-build
```

### Make (per ChibiOS)

```bash
sudo apt install make
```

### Python (per script di analisi)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pyserial pandas matplotlib numpy
```

## 2. Submodule

```bash
git submodule add https://github.com/ChibiOS/ChibiOS \
                  chibios/ChibiOS
git submodule add https://github.com/FreeRTOS/FreeRTOS-Kernel \
                  freertos/FreeRTOS-Kernel
git submodule add https://github.com/STMicroelectronics/STM32CubeH7 \
                  freertos/stm32_hal
git submodule update --init --recursive
```

## 3. Zephyr (separato — usa west)

```bash
cd zephyr
python3 -m venv .venv
source .venv/bin/activate
pip install west
west init -l benchmark_zephyr
west update
pip install -r zephyr/scripts/requirements.txt
```

## 4. Hardware

- Collega NUCLEO-H743ZI2 al PC via USB (presa CN1, lato ST-Link)
- Verifica che compaia `/dev/ttyACM0` (Linux) o `COM<n>` (Windows)
- Per validazione esterna, collega oscilloscopio a:
  - Sonda CH1 → pin PB0 (CN10 pin 31 sul connettore Morpho)
  - GND → CN10 pin 9

## 5. Primo build di prova

```bash
# ChibiOS
cd chibios/benchmark_chibios && make
# Atteso: build/benchmark_chibios.elf

# FreeRTOS
cd freertos/benchmark_freertos
cmake -B build -G Ninja
cmake --build build
# Atteso: build/benchmark_freertos.elf

# Zephyr
cd zephyr
source .venv/bin/activate
west build -b nucleo_h743zi benchmark_zephyr -p always
# Atteso: build/zephyr/zephyr.elf
```

## 6. Flash e raccolta primi dati

```bash
# Flash ChibiOS, poi:
./scripts/collect_results.py --port /dev/ttyACM0 --rtos chibios \
    --output results/chibios_results.csv

# Ripeti per FreeRTOS e Zephyr.

# Plot comparativo
./scripts/plot_results.py
```

## 7. Validazione con oscilloscopio (CONSIGLIATO)

Per il primo run, verifica con oscilloscopio che il GPIO PB0 si toggli
con la cadenza attesa (~1 ms nel test T1). Se il pattern hardware non
corrisponde a quello che il software dice di misurare, c'e' un
problema di setup da risolvere PRIMA di fidarsi dei numeri.
