"""
Lechowicz double-threshold baseline study.

Reviewer concern (1.2.5 of the review): the paper cites Lechowicz et al.
SIGMETRICS'24 as the state-of-the-art provable online carbon-aware
algorithm but does not implement any FaaS adaptation. This script
runs a FaaS-adapted port of the Lechowicz double-threshold algorithm
on the same three setups as run_multi_seed.py and reports
mean +- std across 5 seeds.

The Lechowicz scheduler in greenfaas/schedulers.py implements the
one-way trading threshold Phi* = sqrt(U*L) over the deadline-window
forecast for each invocation. It is single-region (Lechowicz et al.
framework is purely temporal); we run it in the home region.

Expected finding: Lechowicz beats FIFO in the single-region carbon-
variability regime its theory targets, but loses to Spatial/GreenFaaS
in multi-region settings because it cannot route. This is the
"closest theoretical baseline" comparison the review requested.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from statistics import mean, stdev
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import default_carbon_dir
from greenfaas import (
    FifoScheduler,
    GreenFaaSScheduler,
    GreenFaaSV1Scheduler,
    LechowiczScheduler,
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


def run_setup(name, region_ids, carbon, duration_s):
    print(f"\n=== {name} ===")
    regions = build_regions(region_ids)
    functions = make_default_function_catalog()
    fn_map = {f.function_id: f for f in functions}

    scheds = {
        "FIFO":        lambda: FifoScheduler(),
        "Wait-Awhile": lambda: WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
        "Lechowicz":   lambda: LechowiczScheduler(),
        "Spatial":     lambda: SpatialScheduler(max_rtt_ms=80.0),
        "GreenFaaS":   lambda: GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
    }

    rows = []
    for seed in SEEDS:
        t0 = time.time()
        invs = generate_workload(
            duration_s=duration_s, base_rate_per_s=2.0,
            functions=functions, region_ids=region_ids, seed=seed,
        )
        for sname, factory in scheds.items():
            sim = Simulator(regions=regions, functions=fn_map,
                            carbon=carbon, scheduler=factory())
            res = sim.run(invs).summary()
            rows.append({
                "setup": name, "seed": seed, "scheduler": sname,
                "carbon_g": res["carbon_g"],
                "cold_rate": res["cold_start_rate"],
                "warm_idle_g": res["warm_idle_carbon_g"],
            })
        print(f"  seed {seed} done in {time.time()-t0:.1f}s", flush=True)
    return rows


def summarize(rows):
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r["setup"], r["scheduler"])].append(
            (int(r["seed"]), float(r["carbon_g"])))
    setups = sorted({r["setup"] for r in rows})

    print(f"\n{'Setup':<30} {'Scheduler':<12} "
          f"{'Carbon (g) mean+-std':>22} {'vs FIFO mean+-std':>22}")
    print("-" * 92)
    out = []
    for setup in setups:
        fifo_per_seed = {s: c for s, c in buckets[(setup, "FIFO")]}
        for name in ["FIFO", "Wait-Awhile", "Lechowicz", "Spatial", "GreenFaaS"]:
            carbons = [c for _, c in buckets[(setup, name)]]
            reductions = [(fifo_per_seed[s] - c) / fifo_per_seed[s] * 100
                          for s, c in buckets[(setup, name)]]
            cm, cs = mean(carbons), stdev(carbons)
            rm, rs = mean(reductions), stdev(reductions)
            print(f"  {setup:<28} {name:<10} {cm:>10.2f} +- {cs:>5.2f} g  "
                  f"{rm:>+7.2f}% +- {rs:>4.2f}%")
            out.append({"setup": setup, "scheduler": name,
                        "carbon_mean_g": cm, "carbon_std_g": cs,
                        "reduction_mean_pct": rm, "reduction_std_pct": rs,
                        "n_seeds": 5})
    return out


def main():
    duration_s = 24 * 3600.0
    all_rows = []

    # Synthetic 5-region
    region_ids = ["FR", "DE", "GB", "US-CAISO", "PL"]
    synth_carbon = CarbonModel(traces={
        r: synthetic_diurnal_trace(r, duration_s, step_s=300.0, seed=0)
        for r in region_ids
    })
    all_rows += run_setup("Synthetic 5-region", region_ids, synth_carbon, duration_s)

    # Real LWA 4-region
    real_carbon = load_carbon_model_from_dir(
        str(PROJ / default_carbon_dir()), step_s=300.0, duration_s=duration_s)
    all_rows += run_setup("Real LWA 4-region",
                          sorted(["DE", "FR", "GB", "US-CAISO"]),
                          real_carbon, duration_s)

    # Real single-region DE (where Lechowicz's theory applies cleanest)
    all_rows += run_setup("Real single-region DE",
                          ["DE"], real_carbon, duration_s)

    summary = summarize(all_rows)

    out_raw = PROJ / "results" / "lechowicz_raw.csv"
    out_summary = PROJ / "results" / "lechowicz_variance.csv"
    out_raw.parent.mkdir(parents=True, exist_ok=True)
    with open(out_raw, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    with open(out_summary, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        for r in summary:
            w.writerow(r)
    print(f"\nSaved {len(all_rows)} raw rows to {out_raw}")
    print(f"Saved {len(summary)} summary rows to {out_summary}")


if __name__ == "__main__":
    main()
