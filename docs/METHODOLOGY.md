# Metodologia del Benchmark

Documento di riferimento sui criteri di equivalenza, le scelte di
misurazione e i limiti del confronto. Da leggere prima di interpretare
o presentare i risultati.

## Principio guida

> Le condizioni di misura devono essere fisicamente identiche per
> tutti e tre gli RTOS. Qualsiasi differenza nei numeri prodotti deve
> essere attribuibile UNICAMENTE alle differenze tra gli RTOS, non a
> differenze nel setup.

## Vincoli identici

| Aspetto             | Valore           | Note                                      |
|---------------------|------------------|-------------------------------------------|
| MCU                 | STM32H743ZIT6    | Cortex-M7 r0p1, FPU SP                    |
| Clock               | 480 MHz          | HSE 8 MHz x PLL                           |
| Flash latency       | WS=4             | Coerente con 480 MHz a Vcore VOS0         |
| I-Cache             | OFF              | Disabilitata da main.c di ogni RTOS       |
| D-Cache             | OFF              | Disabilitata da main.c di ogni RTOS       |
| Tick rate           | 1000 Hz          | configurato in chconf/FreeRTOSConfig/Kconfig |
| Tickless            | OFF (scenario A) | Sara' attivato in scenario B separato     |
| Compilatore         | gcc 13.x         | Stessi flag: -O2 -ggdb -mcpu=cortex-m7   |
| LTO                 | OFF              | Coerenza tra RTOS                         |
| FPU                 | hard, fpv5-d16   | Stesso codegen su tutti                   |
| Mutex con PIP       | ON               | Default ChibiOS, esplicito FreeRTOS+Zephyr |

## Strumento di misura

### Perche' il DWT cycle counter?

Il registro `DWT->CYCCNT` e' un peripheral hardware del Cortex-M che
incrementa ad ogni ciclo di CPU. E' COMPLETAMENTE indipendente
dall'RTOS: nessun kernel puo' "barare" sui suoi valori. A 480 MHz
fornisce risoluzione di ~2 ns, sufficiente per misurare context
switch sub-microsecondo.

### Validazione esterna con oscilloscopio

Per ogni nuovo setup, eseguiamo questa sanity check:
1. Nel test, dopo il context switch, togliamo PB0
2. Sull'oscilloscopio misuriamo l'intervallo tra due toggle
3. Confrontiamo con la media dei sample software
4. Se differiscono di >5%, c'e' un bug nel setup o nel DWT

## Test eseguiti

### T1 — Context switch via IRQ wake-up

**Cosa misura**: il tempo NETTO che intercorre tra il momento in cui
un'ISR rilascia un semaforo (start) e il momento in cui il thread
bloccato su quel semaforo riprende l'esecuzione (end).

**Cammino misurato** include: epilogue dell'ISR + scheduler decision +
context switch + prologue del thread risvegliato.

**Cammino NON misurato** (per esclusione): il jitter del timer HW
stesso (l'ISR salva il timestamp prima di fare signal, eliminandolo).

### T2 — Context switch via mutex contention

**Cosa misura**: il tempo NETTO tra il rilascio di un mutex da parte
di un thread a bassa priorita' e l'acquisizione dello stesso mutex
da parte di un thread ad alta priorita' che lo stava attendendo.

**Caratteristiche**: questo e' il cammino piu' rilevante per i
sistemi RT che usano risorse condivise. Include scheduler + context
switch + costo del priority inheritance.

## Analisi statistica

Per ogni test eseguiamo **10.000 iterazioni** consecutive. Per ciascuna
salviamo il numero di cicli misurato. A fine test calcoliamo:

- **Min**: il caso migliore (limite teorico inferiore)
- **Max**: il worst-case osservato (rilevante per i sistemi RT hard)
- **Mean**: valore atteso medio
- **Stddev**: dispersione, indicatore di determinismo
- **Outliers oltre 3-sigma**: contati ma NON rimossi
- **p99.9**: calcolato offline dal CSV (vedi `scripts/plot_results.py`)

## Cosa NON misuriamo (e perche')

| Non misurato            | Motivo                                              |
|-------------------------|-----------------------------------------------------|
| Memory footprint        | Argomento per analisi separata                      |
| Throughput msg/s        | T1 e T2 catturano gia' il context switch puro       |
| Power consumption       | Richiede strumentazione dedicata (PPK2)             |
| Boot time               | Non rappresentativo dell'uso run-time               |
| Scheduling overhead %   | Difficile misurare in modo equo                     |

## Limiti del benchmark

Onesta' intellettuale impone di dichiarare i limiti:

1. **Una sola board, una sola MCU**: i risultati non sono
   automaticamente trasferibili ad altre famiglie (STM32F4, STM32G4,
   nRF52, ecc.)

2. **Configurazioni "default-like"**: ciascun RTOS puo' essere
   tunato in modo molto fine. I nostri valori sono ragionevoli ma
   non necessariamente ottimali per ciascun RTOS.

3. **Cache OFF**: configurazione che molti utenti non userebbero in
   produzione. Necessaria per misure pulite, ma non rappresentativa
   delle prestazioni "tutto acceso".

4. **Test sintetici**: il context switch isolato non rappresenta il
   carico reale di un'applicazione. I numeri sono indicativi, non
   predittivi della performance applicativa.

5. **Versioni specifiche**: ChibiOS X.Y, FreeRTOS X.Y, Zephyr v3.7.0
   LTS. Versioni successive potrebbero modificare i risultati.

## Replica dei risultati

Per garantire la riproducibilita':
- Tutto il codice e' nel repo (incluso il `CLAUDE.md` con i vincoli)
- I file di configurazione `chconf.h`, `FreeRTOSConfig.h`, `prj.conf`
  sono versionati
- I CSV grezzi sono in `results/`
- Gli script Python di analisi sono in `scripts/`

Chiunque, partendo dal repo + hardware, deve poter ottenere risultati
sostanzialmente equivalenti (entro la varianza statistica naturale).
