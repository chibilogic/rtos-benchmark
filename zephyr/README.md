# Benchmark Zephyr

Implementazione del benchmark per Zephyr RTOS su NUCLEO-H743ZI2.

## Setup iniziale

Zephyr usa **west** come gestore di workspace, NON git submodule.

```bash
# Da rtos-benchmark/zephyr/
python3 -m venv .venv
source .venv/bin/activate
pip install west

# Inizializza il workspace puntando al manifest del nostro progetto
west init -l benchmark_zephyr

# Scarica Zephyr e tutti i moduli (HAL, CMSIS, ecc.)
west update

# Installa requirements Python di Zephyr
pip install -r zephyr/scripts/requirements.txt

# Installa Zephyr SDK (se non gia' presente)
# Vedi https://docs.zephyrproject.org/latest/develop/getting_started/
```

## Build

```bash
# Da rtos-benchmark/zephyr/
source .venv/bin/activate
west build -b nucleo_h743zi benchmark_zephyr -p always
```

Output: `build/zephyr/zephyr.elf`

## Flash

```bash
west flash
# oppure manualmente:
openocd -f interface/stlink.cfg -f target/stm32h7x.cfg \
        -c "program build/zephyr/zephyr.elf verify reset exit"
```

## UART

Identico agli altri RTOS. Console su USART3 → ST-Link VCP.

## Note specifiche Zephyr

- I device tree overlay sono in `benchmark_zephyr/boards/`
- TIM2 e' usato come "counter device" tramite l'API zephyr `drivers/counter`
- Le cache vengono disabilitate runtime in `main.c` (Zephyr le abilita
  di default su Cortex-M7)
- Priority numbering INVERSO rispetto a ChibiOS/FreeRTOS: numero
  basso = priorita' alta. Tenuto conto nei file di test.
