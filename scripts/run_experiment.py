"""
Run a small comparative experiment across all four schedulers.

Produces a printed table summarising operational carbon, SLA violations,
cold-start rates, latency percentiles, and cost for each scheduler on an
identical workload and carbon trace.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script from anywhere within the project.
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


def build_regions() -> dict[str, Region]:
    """A 6-region topology spanning low / medium / high carbon grids."""
    ids = ["FR", "SE", "DE", "GB", "US-CAISO", "PL"]
    # Approximate inter-region RTTs in ms. Symmetric.
    rtt_pairs = {
        ("FR", "SE"): 35, ("FR", "DE"): 15, ("FR", "GB"): 12,
        ("FR", "US-CAISO"): 145, ("FR", "PL"): 30,
        ("SE", "DE"): 25, ("SE", "GB"): 30, ("SE", "US-CAISO"): 150, ("SE", "PL"): 30,
        ("DE", "GB"): 20, ("DE", "US-CAISO"): 155, ("DE", "PL"): 15,
        ("GB", "US-CAISO"): 140, ("GB", "PL"): 30,
        ("US-CAISO", "PL"): 170,
    }
    rtt_map: dict[str, dict[str, float]] = {r: {} for r in ids}
    for (a, b), v in rtt_pairs.items():
        rtt_map[a][b] = float(v)
        rtt_map[b][a] = float(v)
    regions = {
        r: Region(
            region_id=r,
            name=r,
            capacity=400,
            network_rtt_ms=rtt_map[r],
            pue=1.2,
        )
        for r in ids
    }
    return regions


def main():
    regions = build_regions()
    region_ids = list(regions.keys())
    functions = make_default_function_catalog()
    fn_map = {f.function_id: f for f in functions}

    duration_s = 24 * 3600.0   # 24 hours of simulated time
    carbon = CarbonModel.synthetic(region_ids, duration_s, step_s=300.0, seed=7)

    # Generate a single workload used identically by every scheduler.
    invocations = generate_workload(
        duration_s=duration_s,
        base_rate_per_s=2.0,            # ~peak 3.5 invocations/sec; tractable for 5 schedulers
        functions=functions,
        region_ids=region_ids,
        seed=42,
    )
    print(f"Generated {len(invocations):,} invocations over {duration_s/3600:.0f}h")

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
        result = sim.run(invocations)
        results.append(result)

    # ------------------------------------------------------------------ #
    # Print a comparison table.
    # ------------------------------------------------------------------ #
    cols = [
        ("scheduler", 14, "{:<14}"),
        ("invocations", 12, "{:>12,.0f}"),
        ("carbon (g)", 12, "{:>12,.1f}"),
        ("energy(kWh)", 12, "{:>12.4f}"),
        ("SLA viol%", 10, "{:>10.2%}"),
        ("cold%", 8, "{:>8.2%}"),
        ("p50(ms)", 10, "{:>10.1f}"),
        ("p95(ms)", 10, "{:>10.1f}"),
        ("p99(ms)", 10, "{:>10.1f}"),
        ("cost ($)", 10, "{:>10.4f}"),
    ]
    header = " ".join(c[0].rjust(c[1]) if i else c[0].ljust(c[1]) for i, c in enumerate(cols))
    print()
    print(header)
    print("-" * len(header))
    fifo_carbon = None
    for sched, res in zip(schedulers, results):
        s = res.summary()
        row = (
            cols[0][2].format(sched.name),
            cols[1][2].format(s["invocations"]),
            cols[2][2].format(s["carbon_g"]),
            cols[3][2].format(s["energy_kwh"]),
            cols[4][2].format(s["sla_violation_rate"]),
            cols[5][2].format(s["cold_start_rate"]),
            cols[6][2].format(s["p50_latency_ms"]),
            cols[7][2].format(s["p95_latency_ms"]),
            cols[8][2].format(s["p99_latency_ms"]),
            cols[9][2].format(s["cost_usd"]),
        )
        print(" ".join(row))
        if fifo_carbon is None:
            fifo_carbon = s["carbon_g"]

    print()
    print("Relative carbon reduction vs FIFO:")
    for sched, res in zip(schedulers, results):
        cg = res.summary()["carbon_g"]
        delta = (fifo_carbon - cg) / fifo_carbon * 100.0 if fifo_carbon else 0.0
        print(f"  {sched.name:<14}  {delta:+6.2f}%")


if __name__ == "__main__":
    main()
