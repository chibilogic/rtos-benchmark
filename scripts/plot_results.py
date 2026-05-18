#!/usr/bin/env python3
"""
plot_results.py — produce charts from the validated summary tables
(round-9 D1).

This script is the LAST stage of the pipeline:

    collect_results.py   → results/raw/<run>.csv       (validated)
    analyze_results.py   → cross-check fw vs Python
    report_results.py    → results/summary/<...>.csv   (official tables)
    plot_results.py      → results/plots/<...>.png     (charts)

Key contract: this script is NOT a stats engine. It does not run
`np.percentile`, it does not aggregate raw samples, it does not
re-derive median/p95/p99 in any way. It only renders the numbers
that report_results.py already wrote to the summary CSVs.

This is on purpose: the summary tables are the sole source of
truth for published numbers, and decoupling charts from raw-data
re-aggregation guarantees that what the report prints and what
the chart shows are the same numbers.

Inputs:
    results/summary/<profile>_aggregate.csv
    results/summary/<rtos>_<profile>_run<NN>_summary.csv

Outputs (under <output-dir>, default results/plots/):
    <profile>_<test>_aggregate.png   bars: median / p95 / p99 / max
                                     per RTOS for one test, aggregate
    <profile>_<test>_per_run.png     median per run_id, one line per RTOS
    <profile>_t4_pi.png              T4 PI pass / total per RTOS

Usage:
    python plot_results.py [--profile fair_perf]
                           [--summary-dir results/summary]
                           [--output-dir  results/plots]
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")    # no display required
    import matplotlib.pyplot as plt
except ImportError as exc:
    print(f"ERROR: missing dependency {exc.name}. "
          f"Run: pip install matplotlib", file=sys.stderr)
    sys.exit(1)


# === Constants ========================================================

REPO_ROOT          = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_DIR = REPO_ROOT / "results" / "summary"
DEFAULT_OUTPUT_DIR  = REPO_ROOT / "results" / "plots"

TESTS = ("t1_irq", "t2_handoff", "t3_mtx_uncont", "t4_mtx_pi")

# Stable RTOS palette: same colour for the same RTOS in every chart.
RTOS_COLOR = {
    "chibios":  "#3a7ca5",
    "freertos": "#d97706",
    "zephyr":   "#7a9a01",
}


# === CSV loaders ======================================================

def read_csv_dict(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_aggregate(summary_dir: Path, profile: str
                   ) -> list[dict]:
    path = summary_dir / f"{profile}_aggregate.csv"
    if not path.is_file():
        return []
    return read_csv_dict(path)


def load_per_run_for_profile(summary_dir: Path, profile: str
                             ) -> list[dict]:
    """Concatenate every <rtos>_<profile>_run<NN>_summary.csv
    matching this profile."""
    rows: list[dict] = []
    for path in sorted(summary_dir.glob(
            f"*_{profile}_run*_summary.csv")):
        rows.extend(read_csv_dict(path))
    return rows


# === Plot helpers =====================================================

def _save(fig, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"Wrote {out_path}")


def plot_aggregate_for_test(profile: str, test: str,
                            agg_rows: list[dict],
                            out_dir: Path) -> None:
    """Bar chart: x = stat (median / p95 / p99 / max),
    bar groups = RTOS. Numbers come straight from the aggregate
    CSV (= median across the N runs of each stat field)."""
    rows = [r for r in agg_rows
            if r["profile"] == profile and r["test"] == test]
    if not rows:
        return
    rtos_order = sorted({r["rtos"] for r in rows})
    stats = ("median", "p95", "p99", "max")

    fig, ax = plt.subplots(figsize=(9, 5))
    n_rtos = len(rtos_order)
    width  = 0.8 / n_rtos
    x_base = list(range(len(stats)))

    for i, rtos in enumerate(rtos_order):
        row = next((r for r in rows if r["rtos"] == rtos), None)
        if row is None:
            continue
        values = [int(row[s]) for s in stats]
        offsets = [x + (i - (n_rtos - 1) / 2) * width for x in x_base]
        ax.bar(offsets, values, width=width, label=rtos,
               color=RTOS_COLOR.get(rtos, None), edgecolor="black",
               linewidth=0.5)
        # Annotate value on top of each bar
        for x, v in zip(offsets, values):
            ax.text(x, v, f"{v}", ha="center", va="bottom",
                    fontsize=8)

    n_runs = rows[0].get("n_runs", "?")
    ax.set_xticks(x_base)
    ax.set_xticklabels(stats)
    ax.set_ylabel("DWT cycles")
    ax.set_title(f"{test} — aggregate ({profile}, "
                 f"n_runs={n_runs}, median across runs)")
    ax.grid(axis="y", linestyle=":")
    ax.legend(title="RTOS")
    _save(fig, out_dir / f"{profile}_{test}_aggregate.png")


def plot_per_run_for_test(profile: str, test: str,
                          per_run_rows: list[dict],
                          out_dir: Path) -> None:
    """One line per RTOS, x = run_id, y = per-run median."""
    rows = [r for r in per_run_rows
            if r["profile"] == profile and r["test"] == test]
    if not rows:
        return
    rtos_order = sorted({r["rtos"] for r in rows})

    # Collect (run_id, median) per RTOS, sorted by run_id.
    series: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in rows:
        series[r["rtos"]].append((r["run_id"], int(r["median"])))
    for rtos in series:
        series[rtos].sort(key=lambda t: t[0])

    fig, ax = plt.subplots(figsize=(9, 5))
    for rtos in rtos_order:
        xs = [f"run{rid}" for rid, _ in series[rtos]]
        ys = [v for _, v in series[rtos]]
        ax.plot(xs, ys, marker="o", label=rtos,
                color=RTOS_COLOR.get(rtos, None), linewidth=1.4)
    ax.set_ylabel("median DWT cycles")
    ax.set_title(f"{test} — per-run median ({profile})")
    ax.grid(axis="y", linestyle=":")
    ax.legend(title="RTOS")
    _save(fig, out_dir / f"{profile}_{test}_per_run.png")


def plot_t4_pi(profile: str, agg_rows: list[dict],
               out_dir: Path) -> None:
    """T4 PI passed/total bar chart, one bar per RTOS."""
    rows = [r for r in agg_rows
            if r["profile"] == profile and r["test"] == "t4_mtx_pi"
            and r.get("pi_total_total", "")]
    if not rows:
        return
    rtos_order = sorted({r["rtos"] for r in rows})

    fig, ax = plt.subplots(figsize=(7, 4))
    xs = rtos_order
    passes = [int(next(r["pi_passed_total"]
                       for r in rows if r["rtos"] == rtos))
              for rtos in xs]
    totals = [int(next(r["pi_total_total"]
                       for r in rows if r["rtos"] == rtos))
              for rtos in xs]
    # Round-11 §10: pi_total_total counts PI scenarios across all
    # T4 runs (= sum over runs of BENCH_T4_RUNS=100), NOT runs.
    bar_total = ax.bar(xs, totals, color="lightgray",
                       edgecolor="black", label="PI scenarios")
    bar_pass  = ax.bar(xs, passes,
                       color=[RTOS_COLOR.get(r) for r in xs],
                       edgecolor="black", label="PI passed")
    for x, p, t in zip(xs, passes, totals):
        ax.text(x, t, f"{p}/{t}", ha="center", va="bottom",
                fontsize=10, fontweight="bold")
    ax.set_ylabel("count")
    ax.set_title(f"TEST 4 — PI pass / total ({profile})")
    ax.legend()
    _save(fig, out_dir / f"{profile}_t4_pi.png")


# === Main =============================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Render charts from report_results.py summaries "
                    "(round-9 D1).")
    p.add_argument("--profile",
                   choices=["fair_perf", "realistic_tickless",
                            "debug_dev"],
                   help="Restrict to one profile (default: all "
                        "profiles found).")
    p.add_argument("--summary-dir", default=str(DEFAULT_SUMMARY_DIR))
    p.add_argument("--output-dir",  default=str(DEFAULT_OUTPUT_DIR))
    args = p.parse_args(argv)

    summary_dir = Path(args.summary_dir)
    output_dir  = Path(args.output_dir)
    if not summary_dir.is_dir():
        print(f"ERROR: summary dir not found: {summary_dir}",
              file=sys.stderr)
        return 2

    # Discover profiles by glob: every <profile>_aggregate.csv.
    aggregate_files = sorted(summary_dir.glob("*_aggregate.csv"))
    if args.profile:
        aggregate_files = [f for f in aggregate_files
                           if f.name == f"{args.profile}_aggregate.csv"]
    if not aggregate_files:
        print(f"ERROR: no <profile>_aggregate.csv under {summary_dir}; "
              f"run scripts/report_results.py first.",
              file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    n_charts = 0
    for agg_path in aggregate_files:
        profile = agg_path.stem.removesuffix("_aggregate")
        agg_rows = read_csv_dict(agg_path)
        per_run_rows = load_per_run_for_profile(summary_dir, profile)

        for test in TESTS:
            plot_aggregate_for_test(profile, test, agg_rows,
                                    output_dir)
            plot_per_run_for_test(profile, test, per_run_rows,
                                  output_dir)
            n_charts += 2
        plot_t4_pi(profile, agg_rows, output_dir)
        n_charts += 1

    print(f"Done. Wrote up to {n_charts} charts under {output_dir}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
