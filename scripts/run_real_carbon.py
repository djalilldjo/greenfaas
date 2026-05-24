"""
Run GreenFaaS evaluation on REAL ENTSO-E / CAISO carbon-intensity data
from the Let's-Wait-Awhile dataset (15-minute resolution, 2020).

Carbon data:   real_data/carbon/ (DE, FR, GB, US-CAISO)
Workload:      schema-correct synthetic stream (real Azure traces are not
               fetchable in this environment; substitute when available
               via run_real_traces.py --azure-2021-csv ...)

The honest disclosure to put in the paper: carbon side is real, workload
side is synthetic but calibrated to Shahrad et al. characterisation.

Output:
  - Console table of carbon reduction vs FIFO per scheduler.
  - results/real_carbon_headline.csv with the raw numbers.
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
    WaitAwhileScheduler,
    generate_workload,
    make_default_function_catalog,
    load_carbon_model_from_dir,
)

PROJ = Path(__file__).resolve().parents[1]


def build_regions(region_ids):
    """Build Region objects with realistic inter-region RTTs."""
    rtt_pairs = {
        ("FR", "DE"): 15, ("FR", "GB"): 12, ("FR", "US-CAISO"): 145,
        ("DE", "GB"): 20, ("DE", "US-CAISO"): 155,
        ("GB", "US-CAISO"): 140,
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


def main():
    # Load real LWA carbon data; restrict to a 24h window for speed.
    duration_s = 24 * 3600.0
    print(f"Loading real LWA 2020 carbon data ({duration_s/3600:.0f}h slice)...")
    carbon = load_carbon_model_from_dir(
        str(PROJ / default_carbon_dir()),
        step_s=300.0,
        duration_s=duration_s,
    )
    region_ids = sorted(carbon.regions())
    print(f"  Regions: {region_ids}")
    for r in region_ids:
        vals = carbon.traces[r].values
        print(f"    {r}: mean={sum(vals)/len(vals):.1f} g, "
              f"range=[{min(vals):.1f}, {max(vals):.1f}]")

    regions = build_regions(region_ids)
    functions = make_default_function_catalog()

    # Schema-correct synthetic workload (Azure-style).
    invocations = generate_workload(
        duration_s=duration_s,
        base_rate_per_s=2.0,
        functions=functions,
        region_ids=region_ids,
        seed=42,
    )
    print(f"\nGenerated {len(invocations):,} invocations over {duration_s/3600:.0f}h")

    schedulers = [
        FifoScheduler(),
        WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
        SpatialScheduler(max_rtt_ms=80.0),
        GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
        GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
    ]

    fn_map = {f.function_id: f for f in functions}
    results = []
    for sched in schedulers:
        t0 = time.time()
        sim = Simulator(regions=regions, functions=fn_map, carbon=carbon, scheduler=sched)
        res = sim.run(invocations)
        elapsed = time.time() - t0
        results.append((sched.name, res.summary(), elapsed))
        s = res.summary()
        print(f"  {sched.name:<14}: carbon={s['carbon_g']:>8.2f} g, "
              f"SLA={s['sla_violation_rate']:.2%}, "
              f"cold={s['cold_start_rate']:.2%}  ({elapsed:.1f}s)")

    # Comparison table.
    print()
    print(f"{'Scheduler':<14} {'Carbon(g)':>10} {'vs FIFO':>9} {'SLA':>7} {'Cold':>7} {'p95(ms)':>10}")
    print("-" * 60)
    fifo_carbon = None
    rows = []
    for name, s, _ in results:
        if fifo_carbon is None:
            fifo_carbon = s["carbon_g"]
        reduction = (fifo_carbon - s["carbon_g"]) / fifo_carbon * 100.0 if fifo_carbon else 0.0
        print(f"{name:<14} {s['carbon_g']:>10.2f} {reduction:>+8.2f}% "
              f"{s['sla_violation_rate']:>7.2%} {s['cold_start_rate']:>7.2%} "
              f"{s['p95_latency_ms']:>10.1f}")
        rows.append({
            "scheduler": name,
            "carbon_g": s["carbon_g"],
            "reduction_pct": reduction,
            "sla_viol": s["sla_violation_rate"],
            "cold_rate": s["cold_start_rate"],
            "p95_ms": s["p95_latency_ms"],
            "invocations": s["invocations"],
        })

    # Save CSV.
    out_dir = PROJ / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "real_carbon_headline.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
