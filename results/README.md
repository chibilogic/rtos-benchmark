# Risultati

Questa directory raccoglie i CSV grezzi e i grafici prodotti dal
benchmark.

## File attesi

Dopo aver eseguito `./scripts/flash_all.sh all`:

- `chibios_results.csv` — 20.000 sample (T1 + T2)
- `freertos_results.csv` — 20.000 sample
- `zephyr_results.csv` — 20.000 sample
- `comparison_ctxsw_irq.png` — violin plot + bar chart per T1
- `comparison_ctxsw_mutex.png` — violin plot + bar chart per T2
- `summary_table.md` — tabella riassuntiva markdown

## Formato CSV

```csv
rtos,test_name,iteration,cycles,microseconds
chibios,ctxsw_irq,1,142,0.296
chibios,ctxsw_irq,2,140,0.292
...
```

Colonne:
- `rtos`: chibios | freertos | zephyr
- `test_name`: ctxsw_irq | ctxsw_mutex | dwt_baseline
- `iteration`: 1..N (N = BENCH_ITERATIONS = 10000)
- `cycles`: cicli CPU misurati via DWT
- `microseconds`: cycles / 480 (CPU @ 480 MHz)

## Cosa NON commettere

Vedi `.gitignore` — i log grezzi della seriale (`*.log`, `raw/*`) non
vanno committati. Solo i CSV finali puliti.
