"""
Test GreenFaaS in a constrained-topology scenario.

Hypothesis: when spatial routing is restricted (e.g., GDPR data residency
in the EU; single-region deployments; small-scale providers), GreenFaaS
out-performs pure spatial routing because temporal shifting becomes the
dominant source of savings rather than a marginal addition.

We test two restricted topologies:
  1. EU-only      : FR, DE, GB, PL (no SE, no transatlantic). Spatial routing
                    still has a low-carbon target (FR) but less extreme.
  2. Single-region: DE only. Spatial routing has NOTHING to work with;
                    GreenFaaS's temporal shifting should now dominate.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import (
    CarbonModel,
    FifoScheduler,
    GreenFaaSScheduler,
    GreenFaaSV1Scheduler,
    Region,
    Simulator,
    SpatialScheduler,
    WaitAwhileScheduler,
    generate_workload,
    make_default_function_catalog,
)


def build_regions_subset(region_ids):
    rtt_pairs = {
        ("FR", "SE"): 35, ("FR", "DE"): 15, ("FR", "GB"): 12,
        ("FR", "US-CAISO"): 145, ("FR", "PL"): 30,
        ("SE", "DE"): 25, ("SE", "GB"): 30, ("SE", "US-CAISO"): 150, ("SE", "PL"): 30,
        ("DE", "GB"): 20, ("DE", "US-CAISO"): 155, ("DE", "PL"): 15,
        ("GB", "US-CAISO"): 140, ("GB", "PL"): 30,
        ("US-CAISO", "PL"): 170,
    }
    rtt_map = {r: {} for r in region_ids}
    for (a, b), v in rtt_pairs.items():
        if a in region_ids and b in region_ids:
            rtt_map[a][b] = float(v)
            rtt_map[b][a] = float(v)
    return {
        r: Region(region_id=r, name=r, capacity=400,
                  network_rtt_ms=rtt_map[r], pue=1.2)
        for r in region_ids
    }


def run_scenario(name, region_ids, duration_s=24 * 3600.0, base_rate=2.0):
    regions = build_regions_subset(region_ids)
    functions = make_default_function_catalog()
    fn_map = {f.function_id: f for f in functions}
    carbon = CarbonModel.synthetic(region_ids, duration_s, step_s=300.0, seed=7)

    invocations = generate_workload(
        duration_s=duration_s,
        base_rate_per_s=base_rate,
        functions=functions,
        region_ids=region_ids,
        seed=42,
    )

    schedulers = [
        FifoScheduler(),
        WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
        SpatialScheduler(max_rtt_ms=80.0),
        GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
        GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
    ]
    results = []
    for sched in schedulers:
        sim = Simulator(regions=regions, functions=fn_map, carbon=carbon, scheduler=sched)
        results.append((sched.name, sim.run(invocations)))

    print(f"\n=== {name} | regions: {region_ids} | {len(invocations):,} invocations ===")
    fifo_carbon = None
    print(f"{'scheduler':<14} {'carbon(g)':>11} {'vs FIFO':>9} {'SLA viol':>9} {'cold%':>7} {'p95(ms)':>10}")
    print("-" * 64)
    for name_s, res in results:
        s = res.summary()
        if fifo_carbon is None:
            fifo_carbon = s["carbon_g"]
        reduction = (fifo_carbon - s["carbon_g"]) / fifo_carbon * 100.0 if fifo_carbon else 0.0
        print(f"{name_s:<14} {s['carbon_g']:>11.1f} {reduction:>+8.2f}% "
              f"{s['sla_violation_rate']:>9.2%} {s['cold_start_rate']:>7.2%} "
              f"{s['p95_latency_ms']:>10.1f}")
    return results


def main():
    print("=" * 70)
    print("Scenario sweep: does GreenFaaS dominate when spatial is constrained?")
    print("=" * 70)

    # Baseline: full 6-region topology (already in run_experiment.py).
    run_scenario("Full 6-region (FR/SE/DE/GB/CAISO/PL)",
                 ["FR", "SE", "DE", "GB", "US-CAISO", "PL"])

    # EU only (data residency).
    run_scenario("EU-only (FR/DE/GB/PL)",
                 ["FR", "DE", "GB", "PL"])

    # No low-carbon refuge.
    run_scenario("Coal-belt only (DE/GB/PL)",
                 ["DE", "GB", "PL"])

    # Single region — pure temporal shifting territory.
    run_scenario("Single-region DE only",
                 ["DE"])

    # Single region with high diurnal variability.
    run_scenario("Single-region CAISO only (high variability)",
                 ["US-CAISO"])


if __name__ == "__main__":
    main()
