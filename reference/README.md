# Riferimento — Codice ChibiOS originale

Questa directory contiene i file di riferimento dei benchmark ufficiali
ChibiOS, da cui sono ispirati i test T1 e T2 di questo progetto.

## File da scaricare

Esegui dopo aver clonato il repo:

```bash
cd reference
wget https://raw.githubusercontent.com/ChibiOS/ChibiOS/master/test/rt/source/test/rt_test_sequence_012.c
wget https://raw.githubusercontent.com/ChibiOS/ChibiOS/master/test/rt/source/test/rt_test_sequence_005.c
```

## Cosa contengono

- **rt_test_sequence_012.c** — la "Benchmarks" sequence ufficiale.
  Misura: messaggi/s, context switch/s, thread creation rate,
  reschedule, mass reschedule, queue throughput.
  Usa il system tick come unita' di misura.

- **rt_test_sequence_005.c** — semafori e mutex, utile per capire
  come ChibiOS testa la correttezza di queste primitive.

## Come abbiamo derivato i nostri test

I test ufficiali ChibiOS misurano OPERAZIONI/SECONDO usando il system
tick. Per il nostro confronto cross-RTOS abbiamo invertito l'approccio:
misuriamo TEMPO/OPERAZIONE usando il DWT cycle counter (hardware
neutrale).

Questo da' due vantaggi:
1. Indipendenza dal tick rate dei diversi RTOS
2. Possibilita' di analizzare la distribuzione (min, max, p99.9, ecc.)
   non solo la media

La logica concettuale (cosa misura, in quale ordine) e' rimasta
identica per garantire equivalenza.

## Equivalenze API

| Concetto              | ChibiOS              | FreeRTOS                  | Zephyr        |
|-----------------------|----------------------|---------------------------|---------------|
| Yield                 | chThdYield()         | taskYIELD()               | k_yield()     |
| Sleep ms              | chThdSleepMs()       | vTaskDelay(pdMS_TO_TICKS) | k_msleep()    |
| Sem signal (ISR)      | chBSemSignalI()      | xSemaphoreGiveFromISR()   | k_sem_give()  |
| Sem wait              | chBSemWait()         | xSemaphoreTake(.., MAX)   | k_sem_take()  |
| Mutex lock            | chMtxLock()          | xSemaphoreTake(mutex,..)  | k_mutex_lock()|
| Mutex unlock          | chMtxUnlock()        | xSemaphoreGive(mutex)     | k_mutex_unlock()|
| Thread create static  | chThdCreateStatic()  | xTaskCreateStatic()       | k_thread_create()|

Il file `reference/api_mapping.md` (da generare con Claude Code se
serve) puo' espandere questo mapping per altre operazioni.
