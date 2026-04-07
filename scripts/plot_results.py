#!/usr/bin/env python3
"""
Parse benchmark results and generate summary charts.

Usage:
    python scripts/plot_results.py results/run_20260404_120000/

Reads Locust CSV stats, Vegeta JSON reports, and produces PNG charts.
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def plot_locust_stats(results_dir: Path):
    """Plot Locust request stats from CSV."""
    for csv_file in sorted(results_dir.glob("locust_*_stats.csv")):
        name = csv_file.stem.replace("_stats", "")
        try:
            df = pd.read_csv(csv_file)
        except Exception:
            continue

        # Filter out the "Aggregated" row for per-endpoint view
        endpoints = df[df["Name"] != "Aggregated"]
        if endpoints.empty:
            continue

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle(f"Locust: {name}", fontsize=14)

        # Latency percentiles
        ax = axes[0]
        labels = endpoints["Name"].values
        p50 = endpoints["50%"].values
        p90 = endpoints["90%"].values
        p99 = endpoints["99%"].values
        x = range(len(labels))
        width = 0.25
        ax.bar([i - width for i in x], p50, width, label="p50", color="#4f8ef7")
        ax.bar(x, p90, width, label="p90", color="#f97316")
        ax.bar([i + width for i in x], p99, width, label="p99", color="#ef4444")
        ax.set_ylabel("Latency (ms)")
        ax.set_title("Latency Percentiles")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.legend()

        # Throughput
        ax = axes[1]
        rps = endpoints["Requests/s"].values
        ax.barh(labels, rps, color="#22c55e")
        ax.set_xlabel("Requests/s")
        ax.set_title("Throughput")

        plt.tight_layout()
        out = results_dir / f"{name}_chart.png"
        plt.savefig(out, dpi=150)
        plt.close()
        print(f"  Saved: {out}")


def plot_vegeta_report(results_dir: Path):
    """Plot Vegeta latency distribution from JSON report."""
    for json_file in sorted(results_dir.glob("vegeta_*.json")):
        name = json_file.stem
        try:
            data = json.loads(json_file.read_text())
        except Exception:
            continue

        latencies = data.get("latencies", {})
        if not latencies:
            continue

        fig, ax = plt.subplots(figsize=(8, 4))
        pcts = {"p50": "50th", "p90": "90th", "p95": "95th", "p99": "99th"}
        values = []
        labels = []
        for key, label in pcts.items():
            val = latencies.get(key, 0) / 1e6  # ns to ms
            values.append(val)
            labels.append(label)

        ax.bar(labels, values, color=["#4f8ef7", "#f97316", "#a855f7", "#ef4444"])
        ax.set_ylabel("Latency (ms)")
        ax.set_title(f"Vegeta: {name} — Latency Percentiles")

        # Add mean line
        mean_ms = latencies.get("mean", 0) / 1e6
        ax.axhline(y=mean_ms, color="gray", linestyle="--", label=f"mean={mean_ms:.0f}ms")
        ax.legend()

        plt.tight_layout()
        out = results_dir / f"{name}_chart.png"
        plt.savefig(out, dpi=150)
        plt.close()
        print(f"  Saved: {out}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/plot_results.py <results_dir>")
        print("Example: python scripts/plot_results.py results/run_20260404_120000/")
        sys.exit(1)

    results_dir = Path(sys.argv[1])
    if not results_dir.exists():
        print(f"Directory not found: {results_dir}")
        sys.exit(1)

    print(f"Generating charts from {results_dir}/")
    plot_locust_stats(results_dir)
    plot_vegeta_report(results_dir)
    print("Done.")


if __name__ == "__main__":
    main()
