"""
Topology sweep with REAL Azure 2021 workload + REAL ElectricityMaps
or LWA carbon (selected via GREENFAAS_CARBON_DIR).

Same five topologies as run_real_topology.py but using the real
per-invocation Azure trace instead of the schema-faithful synthetic
workload.

Outputs:
  - Console table per topology
  - results/real_workload_topology.csv
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
from greenfaas.carbon import CarbonModel
from greenfaas.traces import load_azure_2021_invocations
from greenfaas.traces.azure_2021 import assign_regions_roundrobin

PROJ = Path(__file__).resolve().parents[1]
AZURE_2021_PATH = PROJ / "real_data" / "azure_2021" / "AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt"


def build_regions_subset(region_ids):
    rtt_pairs = {("FR", "DE"): 15, ("FR", "GB"): 12,
                 ("FR", "US-CAISO"): 145, ("FR", "PL"): 30,
                 ("DE", "GB"): 20, ("DE", "US-CAISO"): 155, ("DE", "PL"): 15,
                 ("GB", "US-CAISO"): 140, ("GB", "PL"): 30,
                 ("US-CAISO", "PL"): 170}
    rtt_map = {r: {} for r in region_ids}
    for (a, b), v in rtt_pairs.items():
        if a in region_ids and b in region_ids:
            rtt_map[a][b] = float(v)
            rtt_map[b][a] = float(v)
    return {r: Region(region_id=r, name=r, capacity=400,
                      network_rtt_ms=rtt_map[r], pue=1.2) for r in region_ids}


def run_topology(name, region_ids, full_carbon, duration_s=24 * 3600.0):
    # Subset the carbon model to the topology's regions only.
    cm = CarbonModel(traces={r: full_carbon.traces[r] for r in region_ids if r in full_carbon.traces})

    regions = build_regions_subset(region_ids)

    # Two-pass workload load (first to get function IDs, then to assign).
    invs_temp, fns_temp = load_azure_2021_invocations(
        str(AZURE_2021_PATH), duration_limit_s=duration_s,
    )
    function_ids = sorted(fns_temp.keys())
    region_assignment = assign_regions_roundrobin(function_ids, region_ids)
    invocations, functions = load_azure_2021_invocations(
        str(AZURE_2021_PATH),
        region_assignment=region_assignment,
        duration_limit_s=duration_s,
    )
    fn_map = {f.function_id: f for f in functions.values()}

    schedulers = [
        ("FIFO",         FifoScheduler()),
        ("Wait-Awhile",  WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0)),
        ("Lechowicz",    LechowiczScheduler()),
        ("Spatial",      SpatialScheduler(max_rtt_ms=80.0)),
        ("GreenFaaS-v1", GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0)),
        ("GreenFaaS",    GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0)),
    ]

    results = []
    for sname, sched in schedulers:
        sim = Simulator(regions=regions, functions=fn_map, carbon=cm, scheduler=sched)
        results.append((sname, sim.run(invocations).summary()))

    fifo_carbon = results[0][1]["carbon_g"]
    print(f"\n=== {name} | regions: {region_ids} | {len(invocations):,} invocations ===")
    print(f"{'scheduler':<14} {'carbon(g)':>11} {'vs FIFO':>9} {'SLA viol':>9} {'cold%':>7}")
    print("-" * 56)
    rows = []
    for n, s in results:
        red = (fifo_carbon - s["carbon_g"]) / fifo_carbon * 100.0 if fifo_carbon else 0.0
        print(f"{n:<14} {s['carbon_g']:>11.2f} {red:>+8.2f}% "
              f"{s['sla_violation_rate']:>9.2%} {s['cold_start_rate']:>7.2%}")
        rows.append({
            "topology": name, "regions": "|".join(region_ids),
            "scheduler": n,
            "carbon_g": s["carbon_g"], "reduction_pct": red,
            "sla_viol": s["sla_violation_rate"],
            "cold_rate": s["cold_start_rate"],
            "p95_ms": s["p95_latency_ms"],
            "invocations": s["invocations"],
        })
    return rows


def main():
    carbon_dir = str(PROJ / default_carbon_dir())
    duration_s = 24 * 3600.0

    print("=" * 72)
    print("Real workload + real carbon topology sweep")
    print("=" * 72)
    print(f"Workload:  Azure Functions 2021 (real per-invocation trace)")
    print(f"Carbon:    {carbon_dir}")

    full_carbon = load_carbon_model_from_dir(carbon_dir, step_s=300.0, duration_s=duration_s)

    all_rows = []
    all_rows += run_topology("Full 5-region (FR/DE/GB/CAISO/PL)",
                             ["FR", "DE", "GB", "US-CAISO", "PL"], full_carbon)
    all_rows += run_topology("EU-only (FR/DE/GB/PL)",
                             ["FR", "DE", "GB", "PL"], full_carbon)
    all_rows += run_topology("Coal-belt (DE/GB/PL)",
                             ["DE", "GB", "PL"], full_carbon)
    all_rows += run_topology("Single-region DE",
                             ["DE"], full_carbon)
    all_rows += run_topology("Single-region CAISO",
                             ["US-CAISO"], full_carbon)

    out = PROJ / "results" / "real_workload_topology.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        for row in all_rows:
            w.writerow(row)
    print(f"\nSaved {len(all_rows)} rows to {out}")


if __name__ == "__main__":
    main()
