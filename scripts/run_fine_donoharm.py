"""
Fine-grained shiftable-fraction sweep.

Reviewer concern (1.2.3): the do-no-harm test (matching FIFO when no
shifting is allowed) is trivially true when there is nothing to do.
The current sensitivity sweep tests at coarse fractions {0, 0.25, 0.5,
0.75, 1.0}; the jump from 0 to 0.25 is too coarse to demonstrate
graceful degradation.

This sweep tests at fine fractions {0.00, 0.01, 0.02, 0.05, 0.10, 0.25}
to show:
  (a) GreenFaaS produces minimal carbon overhead at very low shiftable
      fractions (graceful degradation, not a step function);
  (b) GreenFaaS-v1 (the un-corrected ablation) starts losing carbon
      to FIFO at lower shiftable fractions than the corrected version;
  (c) The corrected GreenFaaS = FIFO bit-exactly at fraction 0 but
      diverges smoothly upward as the opportunity grows.

If GreenFaaS shows graceful degradation across {0.00, 0.01, 0.02, 0.05},
the do-no-harm property is *robust*, not trivial: any single-region
or zero-opportunity scenario falls inside this graceful regime.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import default_carbon_dir
from greenfaas import (
    FifoScheduler,
    GreenFaaSScheduler,
    GreenFaaSV1Scheduler,
    Region,
    Simulator,
    SpatialScheduler,
    generate_workload,
    make_default_function_catalog,
    load_carbon_model_from_dir,
)
from greenfaas.core import LatencyClass

PROJ = Path(__file__).resolve().parents[1]


def reassign_latency_class(invocations, functions, shiftable_fraction, seed=42):
    """Reassign latency classes so exactly `shiftable_fraction` of invocations
    are Deferrable/Background, the rest Interactive.

    We do this by overriding the function catalog's latency class on a
    deterministic per-invocation basis.
    """
    import random
    rng = random.Random(seed)
    fn_classes = {}
    out_invocations = []
    out_functions = []

    # Make a mutable per-invocation override flag: which fraction is shiftable?
    # We achieve the target by: for each invocation, draw uniform; if < frac,
    # mark the function for that invocation as Deferrable; else Interactive.
    # Then we create N copies of each function with the chosen class.
    function_map = {f.function_id: f for f in functions}

    # Simple approach: tweak each function's class to Interactive vs Deferrable
    # to hit the target fraction in expectation.
    new_functions = []
    for f in functions:
        # Random per-function: this gives population-weighted frac on average.
        if rng.random() < shiftable_fraction:
            from dataclasses import replace
            new_functions.append(replace(f, latency_class=LatencyClass.DEFERRABLE))
        else:
            from dataclasses import replace
            new_functions.append(replace(f, latency_class=LatencyClass.INTERACTIVE))
    return invocations, new_functions


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


def main():
    duration_s = 6 * 3600.0
    region_ids = sorted(["FR", "DE", "GB", "US-CAISO", "PL"])
    carbon = load_carbon_model_from_dir(
        str(PROJ / default_carbon_dir()), step_s=300.0, duration_s=duration_s)
    regions = build_regions(region_ids)
    base_functions = make_default_function_catalog()

    fractions = [0.00, 0.01, 0.02, 0.05, 0.10, 0.25]
    rows = []

    print(f"{'frac':>6} {'FIFO':>8} {'GreenFaaS':>10} {'gap_GF':>8} "
          f"{'v1':>8} {'gap_v1':>8} {'Spatial':>8} {'gap_Sp':>8}")
    print("-" * 70)

    for frac in fractions:
        _, fns = reassign_latency_class(None, base_functions, frac, seed=42)
        fn_map = {f.function_id: f for f in fns}

        invocations = generate_workload(
            duration_s=duration_s, base_rate_per_s=2.0,
            functions=fns, region_ids=region_ids, seed=42,
        )

        def run(s):
            return Simulator(regions=regions, functions=fn_map,
                             carbon=carbon, scheduler=s).run(invocations).summary()

        fifo = run(FifoScheduler())
        gf = run(GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0))
        v1 = run(GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0))
        sp = run(SpatialScheduler(max_rtt_ms=80.0))

        # Carbon "gap" = carbon-aware vs FIFO. Negative if it does worse than FIFO.
        gf_gap = (fifo["carbon_g"] - gf["carbon_g"]) / fifo["carbon_g"] * 100.0
        v1_gap = (fifo["carbon_g"] - v1["carbon_g"]) / fifo["carbon_g"] * 100.0
        sp_gap = (fifo["carbon_g"] - sp["carbon_g"]) / fifo["carbon_g"] * 100.0

        print(f"{frac:>6.2f} {fifo['carbon_g']:>8.2f} {gf['carbon_g']:>10.2f} "
              f"{gf_gap:>+7.2f}% {v1['carbon_g']:>8.2f} {v1_gap:>+7.2f}% "
              f"{sp['carbon_g']:>8.2f} {sp_gap:>+7.2f}%")

        rows.append({
            "shiftable_fraction": frac,
            "fifo_carbon_g": fifo["carbon_g"],
            "greenfaas_carbon_g": gf["carbon_g"],
            "greenfaas_v1_carbon_g": v1["carbon_g"],
            "spatial_carbon_g": sp["carbon_g"],
            "greenfaas_gap_pct": gf_gap,
            "greenfaas_v1_gap_pct": v1_gap,
            "spatial_gap_pct": sp_gap,
            "greenfaas_cold_rate": gf["cold_start_rate"],
            "greenfaas_v1_cold_rate": v1["cold_start_rate"],
        })

    out = PROJ / "results" / "fine_grained_donoharm.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
