"""
Sensitivity sweep for §7 of the paper.

Sweeps four axes individually, holding the others at sensible defaults:

  1. Workload intensity (base_rate from 0.5x to 4x default)
  2. SLA class mix (from all-interactive to all-background)
  3. Forecast accuracy (perfect, 24h, 1h, none)
  4. Carbon-intensity variability (low vs high amplitude regions)

For each axis we run FIFO, Wait-Awhile, Spatial, GreenFaaS-v1, GreenFaaS on
identical workloads. Output: figures/sensitivity_<axis>.png plus a CSV table
of raw numbers per sweep point.

Runtime budget: each sweep point is a 12-hour synthetic simulation across 5
regions; expect ~5-15 seconds per point on a modern laptop, ~5 minutes total.
"""
from __future__ import annotations

import csv
import math
import random
import sys
import time
import zlib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import (
    CarbonModel,
    FifoScheduler,
    GreenFaaSScheduler,
    GreenFaaSV1Scheduler,
    LatencyClass,
    Region,
    Simulator,
    SpatialScheduler,
    WaitAwhileScheduler,
    generate_workload,
    make_default_function_catalog,
    synthetic_diurnal_trace,
)
from greenfaas.carbon import REGION_BASELINE


REGION_IDS = ["FR", "DE", "GB", "US-CAISO", "PL"]

RTT_PAIRS = {
    ("FR", "DE"): 15, ("FR", "GB"): 12, ("FR", "US-CAISO"): 145, ("FR", "PL"): 30,
    ("DE", "GB"): 20, ("DE", "US-CAISO"): 155, ("DE", "PL"): 15,
    ("GB", "US-CAISO"): 140, ("GB", "PL"): 30,
    ("US-CAISO", "PL"): 170,
}


# ------------------------------ helpers ------------------------------------ #

def build_regions() -> Dict[str, Region]:
    rtt_map: Dict[str, Dict[str, float]] = {r: {} for r in REGION_IDS}
    for (a, b), v in RTT_PAIRS.items():
        rtt_map[a][b] = float(v)
        rtt_map[b][a] = float(v)
    return {
        r: Region(region_id=r, name=r, capacity=400, network_rtt_ms=rtt_map[r], pue=1.2)
        for r in REGION_IDS
    }


def build_schedulers():
    return [
        FifoScheduler(),
        WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
        SpatialScheduler(max_rtt_ms=80.0),
        GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
        GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
    ]


def run_one(
    schedulers,
    regions,
    functions,
    carbon: CarbonModel,
    invocations,
) -> Dict[str, Dict[str, float]]:
    """Run every scheduler on the same input; return name -> metric summary."""
    fn_map = {f.function_id: f for f in functions}
    out: Dict[str, Dict[str, float]] = {}
    for sched in schedulers:
        sim = Simulator(regions=regions, functions=fn_map, carbon=carbon, scheduler=sched)
        res = sim.run(invocations)
        out[sched.name] = res.summary()
    return out


def reduction_vs_fifo(point: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    fifo = point["FIFO"]["carbon_g"]
    if fifo <= 0:
        return {name: 0.0 for name in point}
    return {name: (fifo - s["carbon_g"]) / fifo * 100.0 for name, s in point.items()}


# ------------------------------ axis 1: intensity ------------------------- #

def sweep_workload_intensity(out_dir: Path, duration_s=6 * 3600.0):
    """Vary peak arrival rate from 0.5/s to 4.0/s (all classes preserved)."""
    print("\n[1/4] Sweeping workload intensity (peak rate)...")
    rates = [0.5, 1.0, 2.0, 3.0, 4.0]
    functions = make_default_function_catalog()
    regions = build_regions()
    carbon = CarbonModel.synthetic(REGION_IDS, duration_s, step_s=300.0, seed=7)

    rows = []
    for rate in rates:
        invocations = generate_workload(
            duration_s=duration_s, base_rate_per_s=rate,
            functions=functions, region_ids=REGION_IDS, seed=42,
        )
        schedulers = build_schedulers()
        t0 = time.time()
        point = run_one(schedulers, regions, functions, carbon, invocations)
        elapsed = time.time() - t0
        reds = reduction_vs_fifo(point)
        print(f"  rate={rate:.1f}/s  invocations={len(invocations):>7,d}  "
              f"GreenFaaS={reds['GreenFaaS']:+.1f}%  Spatial={reds['Spatial']:+.1f}%  "
              f"({elapsed:.1f}s)")
        for name, summary in point.items():
            rows.append({"axis": "intensity", "x": rate,
                         "scheduler": name,
                         "carbon_g": summary["carbon_g"],
                         "reduction_pct": reds[name],
                         "sla_viol": summary["sla_violation_rate"],
                         "cold_rate": summary["cold_start_rate"],
                         "invocations": summary["invocations"]})
    write_csv(out_dir, "sensitivity_intensity.csv", rows)
    plot_axis(out_dir, "Workload Intensity", "Peak rate (invocations/s)",
              rates, rows, "sensitivity_intensity.png")
    return rows


# ------------------------------ axis 2: SLA mix --------------------------- #

def sweep_sla_mix(out_dir: Path, duration_s=6 * 3600.0):
    """Vary fraction of interactive / deferrable / background invocations.

    We parametrise by the fraction of *deferrable + background* (i.e. shiftable)
    invocations. 0.0 = all interactive (no shifting possible); 1.0 = all
    background (maximal shifting). Within the shiftable portion, deferrable
    and background are split 60/40.
    """
    print("\n[2/4] Sweeping SLA class mix (shiftable fraction)...")
    shiftable_fracs = [0.0, 0.25, 0.5, 0.75, 1.0]
    regions = build_regions()
    carbon = CarbonModel.synthetic(REGION_IDS, duration_s, step_s=300.0, seed=7)
    full_catalog = make_default_function_catalog()

    rows = []
    for frac in shiftable_fracs:
        # Filter the catalog by the desired class composition.
        interactive = [f for f in full_catalog if f.latency_class == LatencyClass.INTERACTIVE]
        deferrable = [f for f in full_catalog if f.latency_class == LatencyClass.DEFERRABLE]
        background = [f for f in full_catalog if f.latency_class == LatencyClass.BACKGROUND]

        # Build a custom catalog by sampling per the desired fraction.
        # We do this by generating the workload with the full catalog and then
        # rewriting each invocation's function_id to match the target ratio.
        invocations = generate_workload(
            duration_s=duration_s, base_rate_per_s=2.0,
            functions=full_catalog, region_ids=REGION_IDS, seed=42,
        )
        # Reassign function_ids so the realised fraction matches `frac`.
        rng = random.Random(13)
        for inv in invocations:
            if rng.random() < (1.0 - frac):
                pick = rng.choice(interactive)
            elif rng.random() < 0.6:
                pick = rng.choice(deferrable)
            else:
                pick = rng.choice(background)
            inv.function_id = pick.function_id
            inv.realized_runtime_s = max(0.005, rng.lognormvariate(
                mu=math.log(max(1e-3, pick.avg_runtime_s)),
                sigma=max(0.05, pick.runtime_std_s / max(1e-3, pick.avg_runtime_s)),
            ))
            inv.realized_memory_mb = pick.memory_mb

        schedulers = build_schedulers()
        t0 = time.time()
        point = run_one(schedulers, regions, full_catalog, carbon, invocations)
        elapsed = time.time() - t0
        reds = reduction_vs_fifo(point)
        print(f"  shiftable={frac:.2f}  GreenFaaS={reds['GreenFaaS']:+.1f}%  "
              f"Spatial={reds['Spatial']:+.1f}%  ({elapsed:.1f}s)")
        for name, summary in point.items():
            rows.append({"axis": "sla_mix", "x": frac,
                         "scheduler": name,
                         "carbon_g": summary["carbon_g"],
                         "reduction_pct": reds[name],
                         "sla_viol": summary["sla_violation_rate"],
                         "cold_rate": summary["cold_start_rate"],
                         "invocations": summary["invocations"]})
    write_csv(out_dir, "sensitivity_sla_mix.csv", rows)
    plot_axis(out_dir, "SLA Class Mix",
              "Shiftable fraction (deferrable + background)",
              shiftable_fracs, rows, "sensitivity_sla_mix.png")
    return rows


# ------------------------------ axis 3: forecast accuracy ----------------- #

def sweep_forecast_accuracy(out_dir: Path, duration_s=6 * 3600.0):
    """Vary GreenFaaS's forecast quality from perfect to none.

    Other schedulers are unaffected (FIFO and Spatial don't use forecasts;
    Wait-Awhile uses a hardcoded threshold). Only GreenFaaS and GreenFaaS-v1
    vary across this sweep.
    """
    print("\n[3/4] Sweeping forecast accuracy...")
    accuracies = ["perfect", "24h", "1h", "none"]
    functions = make_default_function_catalog()
    regions = build_regions()
    carbon = CarbonModel.synthetic(REGION_IDS, duration_s, step_s=300.0, seed=7)
    invocations = generate_workload(
        duration_s=duration_s, base_rate_per_s=2.0,
        functions=functions, region_ids=REGION_IDS, seed=42,
    )

    rows = []
    for acc in accuracies:
        schedulers = [
            FifoScheduler(),
            WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
            SpatialScheduler(max_rtt_ms=80.0),
            GreenFaaSV1Scheduler(forecast_accuracy=acc, deferrable_rtt_ms=80.0),
            GreenFaaSScheduler(forecast_accuracy=acc, deferrable_rtt_ms=80.0),
        ]
        t0 = time.time()
        point = run_one(schedulers, regions, functions, carbon, invocations)
        elapsed = time.time() - t0
        reds = reduction_vs_fifo(point)
        print(f"  accuracy={acc:>7}  GreenFaaS={reds['GreenFaaS']:+.1f}%  "
              f"GreenFaaS-v1={reds['GreenFaaS-v1']:+.1f}%  ({elapsed:.1f}s)")
        for name, summary in point.items():
            rows.append({"axis": "forecast", "x": acc,
                         "scheduler": name,
                         "carbon_g": summary["carbon_g"],
                         "reduction_pct": reds[name],
                         "sla_viol": summary["sla_violation_rate"],
                         "cold_rate": summary["cold_start_rate"],
                         "invocations": summary["invocations"]})
    write_csv(out_dir, "sensitivity_forecast.csv", rows)
    plot_axis_categorical(out_dir, "Forecast Accuracy",
                          "Forecast horizon", accuracies, rows,
                          "sensitivity_forecast.png")
    return rows


# ------------------------------ axis 4: carbon variability ---------------- #

def sweep_carbon_variability(out_dir: Path, duration_s=6 * 3600.0):
    """Vary the diurnal amplitude of every region's synthetic carbon trace.

    Amplitude controls the relative size of the diurnal swing (fraction of
    mean intensity). Higher amplitude = more headroom for temporal shifting.
    """
    print("\n[4/4] Sweeping carbon-intensity variability (diurnal amplitude)...")
    amplitudes = [0.0, 0.1, 0.25, 0.5, 0.75]
    functions = make_default_function_catalog()
    regions = build_regions()
    invocations = generate_workload(
        duration_s=duration_s, base_rate_per_s=2.0,
        functions=functions, region_ids=REGION_IDS, seed=42,
    )

    rows = []
    for amp in amplitudes:
        # Build a custom carbon model with controlled diurnal amplitude.
        # We inline the formula from synthetic_diurnal_trace so we can set
        # the amplitude directly rather than relying on REGION_AMPLITUDE.
        traces = {}
        for r in REGION_IDS:
            base = REGION_BASELINE.get(r, 300.0)
            # Deterministic region hash (Python's hash() is salted by PYTHONHASHSEED).
            region_hash = zlib.adler32(r.encode("utf-8"))
            rng = random.Random(7 ^ region_hash)
            n_steps = int(duration_s / 300.0) + 1
            phase = region_hash % 86400
            values = []
            for i in range(n_steps):
                t_ = i * 300.0
                diurnal = math.sin(2 * math.pi * (t_ - phase) / 86400.0)
                weekly = 0.05 * math.sin(2 * math.pi * t_ / (7 * 86400.0))
                v = base * (1.0 + amp * diurnal + weekly)
                v += rng.gauss(0.0, 0.03 * base)
                values.append(max(5.0, v))
            from greenfaas.carbon import CarbonTrace
            traces[r] = CarbonTrace(region_id=r, step_s=300.0, values=values)
        carbon = CarbonModel(traces=traces)

        schedulers = build_schedulers()
        t0 = time.time()
        point = run_one(schedulers, regions, functions, carbon, invocations)
        elapsed = time.time() - t0
        reds = reduction_vs_fifo(point)
        print(f"  amplitude={amp:.2f}  GreenFaaS={reds['GreenFaaS']:+.1f}%  "
              f"Spatial={reds['Spatial']:+.1f}%  ({elapsed:.1f}s)")
        for name, summary in point.items():
            rows.append({"axis": "variability", "x": amp,
                         "scheduler": name,
                         "carbon_g": summary["carbon_g"],
                         "reduction_pct": reds[name],
                         "sla_viol": summary["sla_violation_rate"],
                         "cold_rate": summary["cold_start_rate"],
                         "invocations": summary["invocations"]})
    write_csv(out_dir, "sensitivity_variability.csv", rows)
    plot_axis(out_dir, "Carbon Variability",
              "Diurnal amplitude (fraction of mean intensity)",
              amplitudes, rows, "sensitivity_variability.png")
    return rows


# ------------------------------ plotting + IO ----------------------------- #

SCHED_COLORS = {
    "FIFO":         "#888888",
    "Wait-Awhile":  "#c0392b",
    "Spatial":      "#2980b9",
    "GreenFaaS-v1": "#f39c12",
    "GreenFaaS":    "#27ae60",
}


# Module-level: track where to write figures (set in main()).
_FIGURE_DIR: Path = Path(".")


def plot_axis(out_dir: Path, title: str, xlabel: str, xs, rows, filename: str):
    """Line plot of carbon reduction vs FIFO. Renders both full-range and
    zoomed versions; the zoom drops Wait-Awhile to make the
    carbon-aware schedulers' differences visible.
    """
    for zoom in (False, True):
        fig, ax = plt.subplots(figsize=(8.0, 4.6))
        for sched in SCHED_COLORS:
            if zoom and sched == "Wait-Awhile":
                continue
            ys = []
            for x in xs:
                ys_x = [r["reduction_pct"] for r in rows
                        if r["scheduler"] == sched and abs(r["x"] - x) < 1e-9]
                ys.append(ys_x[0] if ys_x else float("nan"))
            ax.plot(xs, ys, marker="o", lw=1.8, label=sched,
                    color=SCHED_COLORS[sched])
        ax.axhline(0, color="#444", lw=0.6, ls="--")
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Operational carbon reduction vs FIFO (%)")
        suffix = " (zoom: carbon-aware schedulers)" if zoom else ""
        ax.set_title(f"§7: Sensitivity — {title}{suffix}")
        ax.legend(loc="best", fontsize=9, framealpha=0.92)
        ax.grid(True, alpha=0.25)
        plt.tight_layout()
        _FIGURE_DIR.mkdir(parents=True, exist_ok=True)
        out_name = filename if not zoom else filename.replace(".png", "_zoom.png")
        path = _FIGURE_DIR / out_name
        fig.savefig(path, dpi=300)
        plt.close(fig)
        print(f"  wrote {path}")


def plot_axis_categorical(out_dir: Path, title: str, xlabel: str,
                          categories, rows, filename: str):
    """Bar plot for categorical axes. Produces both full-range and zoomed
    versions, the zoom omitting Wait-Awhile.
    """
    for zoom in (False, True):
        fig, ax = plt.subplots(figsize=(8.0, 4.6))
        x_idx = np.arange(len(categories))
        sched_list = [s for s in SCHED_COLORS if not (zoom and s == "Wait-Awhile")]
        width = 0.85 / max(1, len(sched_list))
        for i, sched in enumerate(sched_list):
            ys = []
            for cat in categories:
                ys_c = [r["reduction_pct"] for r in rows
                        if r["scheduler"] == sched and r["x"] == cat]
                ys.append(ys_c[0] if ys_c else float("nan"))
            offset = (i - (len(sched_list) - 1) / 2.0) * width
            ax.bar(x_idx + offset, ys, width, label=sched, color=SCHED_COLORS[sched])
        ax.axhline(0, color="#444", lw=0.6, ls="--")
        ax.set_xticks(x_idx)
        ax.set_xticklabels(categories)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Operational carbon reduction vs FIFO (%)")
        suffix = " (zoom: carbon-aware schedulers)" if zoom else ""
        ax.set_title(f"§7: Sensitivity — {title}{suffix}")
        ax.legend(loc="best", fontsize=9, framealpha=0.92, ncol=2)
        ax.grid(True, axis="y", alpha=0.25)
        plt.tight_layout()
        _FIGURE_DIR.mkdir(parents=True, exist_ok=True)
        out_name = filename if not zoom else filename.replace(".png", "_zoom.png")
        path = _FIGURE_DIR / out_name
        fig.savefig(path, dpi=300)
        plt.close(fig)
        print(f"  wrote {path}")


def write_csv(out_dir: Path, filename: str, rows):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"  wrote {path}")


# ------------------------------ main -------------------------------------- #

def main():
    global _FIGURE_DIR
    _FIGURE_DIR = Path(__file__).resolve().parents[1] / "figures"
    csv_dir = Path(__file__).resolve().parents[1] / "results"
    csv_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("GreenFaaS §7 Sensitivity Sweep")
    print("=" * 72)
    print("Each sweep runs 5 schedulers on 12h synthetic workloads.")

    t_start = time.time()
    sweep_workload_intensity(csv_dir)
    sweep_sla_mix(csv_dir)
    sweep_forecast_accuracy(csv_dir)
    sweep_carbon_variability(csv_dir)

    print(f"\nTotal sweep time: {time.time() - t_start:.1f}s")
    print(f"CSVs in {csv_dir}")
    print(f"Figures in {_FIGURE_DIR}")


if __name__ == "__main__":
    main()
