#!/usr/bin/env python3
"""
plot_results.py

Carica i CSV prodotti da collect_results.py e produce grafici
comparativi tra i tre RTOS.

Output:
    results/comparison_ctxsw_irq.png
    results/comparison_ctxsw_mutex.png
    results/summary_table.md

Statistiche calcolate:
    - min, max, mean, stddev
    - p99.9 (calcolato qui da CSV completo, piu' accurato di max)
    - violin plot della distribuzione

Uso:
    ./plot_results.py
    ./plot_results.py --results-dir results/  --output-dir results/
"""

import argparse
import sys
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
except ImportError as e:
    print(f"ERRORE: dipendenza mancante ({e}). Esegui:", file=sys.stderr)
    print("  pip install pandas numpy matplotlib", file=sys.stderr)
    sys.exit(1)


RTOSES = ["chibios", "freertos", "zephyr"]
COLORS = {"chibios": "#7F77DD", "freertos": "#1D9E75", "zephyr": "#D85A30"}
TESTS = ["ctxsw_irq", "ctxsw_mutex"]


def load_all_results(results_dir: Path) -> pd.DataFrame:
    dfs = []
    for rtos in RTOSES:
        csv_path = results_dir / f"{rtos}_results.csv"
        if not csv_path.exists():
            print(f"WARN: {csv_path} non trovato, skip {rtos}")
            continue
        df = pd.read_csv(csv_path)
        dfs.append(df)
    if not dfs:
        print("ERRORE: nessun CSV trovato.")
        sys.exit(1)
    return pd.concat(dfs, ignore_index=True)


def compute_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Statistiche per (rtos, test) — tabella riassuntiva."""
    rows = []
    for (rtos, test), grp in df.groupby(["rtos", "test_name"]):
        cycles = grp["cycles"].values
        rows.append({
            "rtos": rtos,
            "test": test,
            "n": len(cycles),
            "min": int(cycles.min()),
            "mean": int(cycles.mean()),
            "median": int(np.median(cycles)),
            "p99": int(np.percentile(cycles, 99)),
            "p99.9": int(np.percentile(cycles, 99.9)),
            "max": int(cycles.max()),
            "stddev": int(cycles.std()),
        })
    return pd.DataFrame(rows)


def plot_comparison(df: pd.DataFrame, test: str, output_path: Path):
    """Violin plot comparativo per un test specifico."""
    test_df = df[df["test_name"] == test]
    if test_df.empty:
        print(f"WARN: nessun dato per {test}")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Violin plot
    data_per_rtos = []
    labels = []
    colors_list = []
    for rtos in RTOSES:
        rdata = test_df[test_df["rtos"] == rtos]["cycles"].values
        if len(rdata) > 0:
            data_per_rtos.append(rdata)
            labels.append(rtos)
            colors_list.append(COLORS[rtos])

    if data_per_rtos:
        parts = ax1.violinplot(data_per_rtos, showmeans=True, showmedians=True)
        for i, body in enumerate(parts["bodies"]):
            body.set_facecolor(colors_list[i])
            body.set_alpha(0.7)
        ax1.set_xticks(range(1, len(labels) + 1))
        ax1.set_xticklabels(labels)
        ax1.set_ylabel("Cicli CPU (DWT)")
        ax1.set_title(f"Distribuzione — {test}")
        ax1.grid(True, alpha=0.3)

    # Bar chart con mean +/- stddev
    means = [d.mean() for d in data_per_rtos]
    stds  = [d.std() for d in data_per_rtos]
    bars = ax2.bar(labels, means, yerr=stds, color=colors_list,
                   alpha=0.7, capsize=8)
    ax2.set_ylabel("Cicli CPU (mean +/- stddev)")
    ax2.set_title(f"Confronto medie — {test}")
    ax2.grid(True, alpha=0.3, axis="y")

    # Annotazione valori sopra le barre
    for bar, mean in zip(bars, means):
        ax2.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + 2,
                 f"{int(mean)}",
                 ha="center", fontsize=10)

    plt.suptitle(f"RTOS Benchmark — {test}", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    print(f"Salvato {output_path}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--output-dir", default="results")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_all_results(results_dir)
    print(f"Caricati {len(df)} sample totali.")

    # Tabella riassuntiva
    summary = compute_summary(df)
    print("\n=== Riepilogo ===")
    print(summary.to_string(index=False))

    summary_md = output_dir / "summary_table.md"
    with summary_md.open("w") as f:
        f.write("# Risultati Benchmark — Riepilogo\n\n")
        f.write("Tutti i valori in **cicli CPU** (480 MHz -> 1 ciclo = 2.083 ns).\n\n")
        f.write(summary.to_markdown(index=False))
        f.write("\n")
    print(f"\nTabella riepilogo: {summary_md}")

    # Plot per ogni test
    for test in TESTS:
        out = output_dir / f"comparison_{test}.png"
        plot_comparison(df, test, out)


if __name__ == "__main__":
    main()
