"""
Headline experiment with REAL data on both axes:
  - Real Azure 2021 per-invocation trace (per-function arrival times, durations)
  - Real ElectricityMaps 2024 carbon-intensity data (DE, FR, GB, US-CAISO, PL)

NOTE ON TIME-WINDOW MISMATCH: the Azure trace is January 2021; the
ElectricityMaps data is January 2024. We treat the workload arrival
pattern and the carbon-intensity time series as a *Cartesian product*:
the trace runs for 24h of FaaS arrivals against 24h of carbon data,
without claiming temporal correspondence between the two. This is
common practice for trace-driven simulation (the workload generators
in Azure's own dataset paper do not assume a specific contemporary
carbon trace). The qualitative findings should be robust to this
mismatch.

Outputs:
  - Console table per scheduler
  - results/real_workload_headline.csv
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import (
    FifoScheduler,
    GreenFaaSScheduler,
    GreenFaaSV1Scheduler,
    LechowiczScheduler,
    Region,
    Simulator,
    SpatialScheduler,
    WaitAwhileScheduler,
    load_carbon_model_from_dir,
    default_carbon_dir,
)
from greenfaas.traces import load_azure_2021_invocations
from greenfaas.traces.azure_2021 import assign_regions_roundrobin

PROJ = Path(__file__).resolve().parents[1]

AZURE_2021_PATH = PROJ / "real_data" / "azure_2021" / "AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt"


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
    duration_s = 24 * 3600.0
    region_ids = sorted(["DE", "FR", "GB", "US-CAISO", "PL"])
    carbon_dir = str(PROJ / default_carbon_dir())

    print("=" * 72)
    print("Real workload + real carbon headline")
    print("=" * 72)
    print(f"Workload:  Azure Functions 2021 (real per-invocation trace)")
    print(f"Carbon:    {carbon_dir}")
    print(f"Regions:   {region_ids}")
    print(f"Duration:  {duration_s/3600:.0f}h")
    print()

    # Carbon: real EM data with hourly resolution interpolated to 5-min steps.
    print("Loading carbon data...")
    carbon = load_carbon_model_from_dir(carbon_dir, step_s=300.0, duration_s=duration_s)
    for r in sorted(carbon.regions()):
        v = carbon.traces[r].values
        print(f"  {r}: mean={sum(v)/len(v):.1f} g, range=[{min(v):.1f}, {max(v):.1f}]")

    # Workload: real Azure trace, 24h slice.
    print(f"\nLoading Azure 2021 trace...")
    t0 = time.time()
    # Two-pass: first pass to inventory function IDs (so we can round-robin
    # them across regions); second pass to actually load with that assignment.
    invs_temp, fns_temp = load_azure_2021_invocations(
        str(AZURE_2021_PATH),
        duration_limit_s=duration_s,
    )
    function_ids = sorted(fns_temp.keys())
    region_assignment = assign_regions_roundrobin(function_ids, region_ids)

    invocations, functions = load_azure_2021_invocations(
        str(AZURE_2021_PATH),
        region_assignment=region_assignment,
        duration_limit_s=duration_s,
    )
    fn_map = {f.function_id: f for f in functions.values()}
    print(f"  Loaded {len(invocations):,} invocations, {len(fn_map)} functions in {time.time()-t0:.1f}s")
    print(f"  Latency classes:", end=" ")
    from collections import Counter
    c = Counter(f.latency_class.name for f in functions.values())
    print(dict(c))

    regions = build_regions(region_ids)

    # Run each scheduler.
    schedulers = [
        ("FIFO",         FifoScheduler()),
        ("Wait-Awhile",  WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0)),
        ("Lechowicz",    LechowiczScheduler()),
        ("Spatial",      SpatialScheduler(max_rtt_ms=80.0)),
        ("GreenFaaS-v1", GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0)),
        ("GreenFaaS",    GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0)),
    ]

    print()
    rows = []
    for name, sched in schedulers:
        t0 = time.time()
        sim = Simulator(regions=regions, functions=fn_map, carbon=carbon, scheduler=sched)
        res = sim.run(invocations).summary()
        elapsed = time.time() - t0
        print(f"  {name:<14}: carbon={res['carbon_g']:>8.2f} g, "
              f"SLA={res['sla_violation_rate']:.2%}, "
              f"cold={res['cold_start_rate']:.2%}  ({elapsed:.1f}s)")
        rows.append({
            "scheduler": name,
            "carbon_g": res["carbon_g"],
            "sla_viol": res["sla_violation_rate"],
            "cold_rate": res["cold_start_rate"],
            "p95_ms": res["p95_latency_ms"],
            "warm_idle_g": res["warm_idle_carbon_g"],
            "invocations": res["invocations"],
        })

    # Headline table.
    fifo_carbon = rows[0]["carbon_g"]
    print()
    print(f"{'Scheduler':<14} {'Carbon (g)':>10} {'vs FIFO':>10} {'SLA':>7} {'Cold':>7} {'p95 (ms)':>10}")
    print("-" * 64)
    for r in rows:
        red = (fifo_carbon - r["carbon_g"]) / fifo_carbon * 100.0
        print(f"  {r['scheduler']:<12} {r['carbon_g']:>10.2f} {red:>+8.2f}% "
              f"{r['sla_viol']:>7.2%} {r['cold_rate']:>7.2%} {r['p95_ms']:>10.1f}")
        r["reduction_pct"] = red

    out = PROJ / "results" / "real_workload_headline.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
