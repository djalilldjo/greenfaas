"""
Multi-seed run-to-run variance study.

Reviewer concern (Section 4.2 of the review): single-run results have
no error bars; GreenFaaS-vs-Spatial gaps are <1pp in most regimes, so
run-to-run variance could flip conclusions.

This script re-runs three headline experiments at SEEDS = {42, 43, 44,
45, 46} and reports mean +- std per scheduler. Each seed varies the
workload's per-function popularity weighting and Poisson timing; the
carbon trace and topology are held fixed.

Experiments:
  1. Synthetic 24h, 5 regions (Table 1 = paper §7.2 headline)
  2. Real LWA 4-region carbon, 24h (Table 2 = §7.2.1)
  3. Real-carbon coal-belt topology (DE/GB/PL) - the most contentious
     of the §7.3.1 sweep results

Output:
  - Console table with mean +- std per scheduler per experiment.
  - results/multi_seed_variance.csv with all 5*N raw rows + summary stats.
"""
from __future__ import annotations

import csv
import math
import sys
import time
from pathlib import Path
from statistics import mean, stdev

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import default_carbon_dir
from greenfaas import (
    FifoScheduler,
    GreenFaaSScheduler,
    GreenFaaSV1Scheduler,
    Region,
    Simulator,
    SpatialScheduler,
    WaitAwhileScheduler,
    generate_workload,
    make_default_function_catalog,
    load_carbon_model_from_dir,
)
from greenfaas.carbon import CarbonModel, synthetic_diurnal_trace

PROJ = Path(__file__).resolve().parents[1]
SEEDS = [42, 43, 44, 45, 46]


def build_regions(region_ids):
    rtt_pairs = {("FR", "DE"): 15, ("FR", "GB"): 12, ("FR", "US-CAISO"): 145,
                 ("FR", "PL"): 30, ("DE", "GB"): 20, ("DE", "US-CAISO"): 155,
                 ("DE", "PL"): 15, ("GB", "US-CAISO"): 140, ("GB", "PL"): 30,
                 ("US-CAISO", "PL"): 170}
    rtt_map = {r: {} for r in region_ids}
    for (a, b), v in rtt_pairs.items():
        if a in region_ids and b in region_ids:
            rtt_map[a][b] = float(v)
            rtt_map[b][a] = float(v)
    return {r: Region(region_id=r, name=r, capacity=400,
                      network_rtt_ms=rtt_map[r], pue=1.2) for r in region_ids}


def run_one_setup(name, region_ids, carbon, duration_s):
    print(f"\n=== {name} ===")
    regions = build_regions(region_ids)
    functions = make_default_function_catalog()
    fn_map = {f.function_id: f for f in functions}

    # Run each scheduler at each seed.
    sched_factories = {
        "FIFO":         lambda: FifoScheduler(),
        "Wait-Awhile":  lambda: WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
        "Spatial":      lambda: SpatialScheduler(max_rtt_ms=80.0),
        "GreenFaaS-v1": lambda: GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
        "GreenFaaS":    lambda: GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
    }

    rows = []
    per_sched_carbon = {n: [] for n in sched_factories}
    per_sched_cold = {n: [] for n in sched_factories}
    fifo_per_seed = []

    for seed in SEEDS:
        t0 = time.time()
        invs = generate_workload(
            duration_s=duration_s, base_rate_per_s=2.0,
            functions=functions, region_ids=region_ids, seed=seed,
        )
        seed_carbons = {}
        for sched_name, factory in sched_factories.items():
            sim = Simulator(regions=regions, functions=fn_map,
                            carbon=carbon, scheduler=factory())
            res = sim.run(invs).summary()
            seed_carbons[sched_name] = res["carbon_g"]
            per_sched_carbon[sched_name].append(res["carbon_g"])
            per_sched_cold[sched_name].append(res["cold_start_rate"])
            rows.append({
                "setup": name, "seed": seed, "scheduler": sched_name,
                "carbon_g": res["carbon_g"],
                "cold_rate": res["cold_start_rate"],
                "warm_idle_g": res["warm_idle_carbon_g"],
            })
        fifo_per_seed.append(seed_carbons["FIFO"])
        elapsed = time.time() - t0
        print(f"  seed {seed}: completed all 5 schedulers in {elapsed:.1f}s")

    # Compute mean +- std for carbon reduction relative to FIFO (per seed,
    # then averaged - this is the appropriate way given correlated FIFOs).
    print(f"\n{'Scheduler':<14} {'Carbon (g) mean+-std':>22} {'vs FIFO mean+-std':>22}")
    print("-" * 62)
    summary = []
    for sched_name in sched_factories:
        carbons = per_sched_carbon[sched_name]
        cmean, cstd = mean(carbons), stdev(carbons)
        # vs FIFO per seed
        reductions = [
            (fifo_per_seed[i] - carbons[i]) / fifo_per_seed[i] * 100.0
            for i in range(len(SEEDS))
        ]
        rmean, rstd = mean(reductions), stdev(reductions)
        print(f"  {sched_name:<12} {cmean:>10.2f} +- {cstd:>5.2f} g   "
              f"{rmean:>+7.2f}% +- {rstd:>4.2f}%")
        summary.append({
            "setup": name, "scheduler": sched_name,
            "carbon_mean_g": cmean, "carbon_std_g": cstd,
            "reduction_mean_pct": rmean, "reduction_std_pct": rstd,
            "n_seeds": len(SEEDS),
        })
    return rows, summary


def main():
    duration_s = 24 * 3600.0

    all_rows = []
    all_summary = []

    # --- Synthetic 5-region (paper Table 1) ---
    region_ids = ["FR", "DE", "GB", "US-CAISO", "PL"]
    synth_carbon = CarbonModel(traces={
        r: synthetic_diurnal_trace(r, duration_s, step_s=300.0, seed=0)
        for r in region_ids
    })
    rows, summary = run_one_setup(
        "Synthetic 5-region (Table 1)",
        region_ids, synth_carbon, duration_s)
    all_rows += rows
    all_summary += summary

    # --- Real LWA 4-region (paper Table 2) ---
    real_carbon = load_carbon_model_from_dir(
        str(PROJ / default_carbon_dir()), step_s=300.0, duration_s=duration_s)
    rows, summary = run_one_setup(
        "Real LWA 4-region (Table 2)",
        sorted(["DE", "FR", "GB", "US-CAISO"]),
        real_carbon, duration_s)
    all_rows += rows
    all_summary += summary

    # --- Real coal-belt topology (Table 3 = §7.3.1) ---
    rows, summary = run_one_setup(
        "Real coal-belt (DE/GB/PL)",
        sorted(["DE", "GB", "PL"]),
        real_carbon, duration_s)
    all_rows += rows
    all_summary += summary

    # Write CSVs.
    out_raw = PROJ / "results" / "multi_seed_raw.csv"
    out_summary = PROJ / "results" / "multi_seed_variance.csv"
    out_raw.parent.mkdir(parents=True, exist_ok=True)

    with open(out_raw, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"\nSaved {len(all_rows)} raw rows to {out_raw}")

    with open(out_summary, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_summary[0].keys()))
        w.writeheader()
        for r in all_summary:
            w.writerow(r)
    print(f"Saved {len(all_summary)} summary rows to {out_summary}")


if __name__ == "__main__":
    main()
