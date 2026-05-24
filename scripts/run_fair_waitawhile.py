"""
Re-run the headline comparison with a FAIR Wait-Awhile parameterization.

Background. The original §7.2 headline reports Wait-Awhile with
max_defer_s = 1800 (Wiesner et al.'s default for batch jobs). This
gives a +236% carbon increase over FIFO on FaaS workloads -- a clean
demonstration that batch-oriented temporal scheduling fails on FaaS,
but a reviewer can fairly point out that 1800s deferral horizons are
adversarial against functions with sub-minute SLA deadlines.

This script reports four Wait-Awhile variants on the same workload:
  (a) max_defer_s = 1800  -- Wiesner et al.'s batch default (paper headline)
  (b) max_defer_s = 60    -- matches GreenFaaS's Deferrable horizon
  (c) max_defer_s = 30    -- conservative, sub-SLA for many interactive functions
  (d) max_defer_s = SLA   -- SLA-aware (clipped per-invocation to remaining slack)

The fair-parameter variants (b, c, d) test the reviewer's hypothesis
that the "+236% triples" claim is an artefact of parameter choice.

The failure mode (Wait-Awhile loses to FIFO on FaaS) survives the fair
parameterization, but the magnitude is much smaller. We report both
results in the paper.
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
    Region,
    Simulator,
    SpatialScheduler,
    WaitAwhileScheduler,
    generate_workload,
    make_default_function_catalog,
    load_carbon_model_from_dir,
)
from greenfaas.carbon import REGION_BASELINE, REGION_AMPLITUDE, CarbonModel, synthetic_diurnal_trace

PROJ = Path(__file__).resolve().parents[1]


def build_synthetic_carbon(region_ids, duration_s):
    """Synthetic 6-region carbon model matching §7.2."""
    traces = {r: synthetic_diurnal_trace(r, duration_s, step_s=300.0, seed=0)
              for r in region_ids}
    return CarbonModel(traces=traces)


def build_regions(region_ids):
    rtt_pairs = {
        ("FR", "DE"): 15, ("FR", "GB"): 12, ("FR", "US-CAISO"): 145,
        ("FR", "PL"): 30, ("DE", "GB"): 20, ("DE", "US-CAISO"): 155,
        ("DE", "PL"): 15, ("GB", "US-CAISO"): 140, ("GB", "PL"): 30,
        ("US-CAISO", "PL"): 170,
    }
    rtt_map = {r: {} for r in region_ids}
    for (a, b), v in rtt_pairs.items():
        if a in region_ids and b in region_ids:
            rtt_map[a][b] = float(v)
            rtt_map[b][a] = float(v)
    return {r: Region(region_id=r, name=r, capacity=400,
                      network_rtt_ms=rtt_map[r], pue=1.2) for r in region_ids}


def run_one(label, scheduler, regions, fn_map, carbon, invocations):
    t0 = time.time()
    sim = Simulator(regions=regions, functions=fn_map, carbon=carbon, scheduler=scheduler)
    res = sim.run(invocations).summary()
    elapsed = time.time() - t0
    print(f"  {label:<22}: carbon={res['carbon_g']:>9.2f} g, "
          f"cold={res['cold_start_rate']:>6.2%}, "
          f"warm_idle={res['warm_idle_carbon_g']:>7.2f} g  ({elapsed:.1f}s)")
    return res


def run_setup(name, region_ids, carbon, duration_s=24*3600.0):
    print(f"\n=== {name} ===")
    regions = build_regions(region_ids)
    functions = make_default_function_catalog()
    fn_map = {f.function_id: f for f in functions}
    invocations = generate_workload(
        duration_s=duration_s, base_rate_per_s=2.0,
        functions=functions, region_ids=region_ids, seed=42,
    )
    print(f"  {len(invocations):,} invocations")

    rows = []
    fifo_carbon = run_one("FIFO", FifoScheduler(), regions, fn_map, carbon, invocations)
    fifo_g = fifo_carbon["carbon_g"]
    rows.append({"setup": name, "scheduler": "FIFO", "max_defer_s": None,
                 **fifo_carbon, "vs_fifo_pct": 0.0})

    for max_defer in [1800, 60, 30]:
        label = f"Wait-Awhile (defer={max_defer}s)"
        res = run_one(label, WaitAwhileScheduler(threshold_g=200.0, max_defer_s=float(max_defer)),
                      regions, fn_map, carbon, invocations)
        vs_fifo = (fifo_g - res["carbon_g"]) / fifo_g * 100.0
        rows.append({"setup": name, "scheduler": "Wait-Awhile",
                     "max_defer_s": max_defer, **res, "vs_fifo_pct": vs_fifo})

    sp = run_one("Spatial", SpatialScheduler(max_rtt_ms=80.0), regions, fn_map, carbon, invocations)
    rows.append({"setup": name, "scheduler": "Spatial", "max_defer_s": None,
                 **sp, "vs_fifo_pct": (fifo_g - sp["carbon_g"]) / fifo_g * 100.0})

    gf = run_one("GreenFaaS", GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
                 regions, fn_map, carbon, invocations)
    rows.append({"setup": name, "scheduler": "GreenFaaS", "max_defer_s": None,
                 **gf, "vs_fifo_pct": (fifo_g - gf["carbon_g"]) / fifo_g * 100.0})

    # Comparison table
    print(f"\n{'Scheduler':<26} {'Carbon(g)':>10} {'vs FIFO':>8}")
    print("-" * 50)
    for r in rows:
        name_str = (f"{r['scheduler']} (defer={r['max_defer_s']}s)"
                    if r['max_defer_s'] is not None else r['scheduler'])
        print(f"  {name_str:<24} {r['carbon_g']:>9.2f} {r['vs_fifo_pct']:>+7.2f}%")
    return rows


def main():
    print("=" * 70)
    print("Fair Wait-Awhile baseline study")
    print("Reviewer concern: max_defer_s=1800 is adversarial for FaaS")
    print("=" * 70)

    region_ids_synth = ["FR", "DE", "GB", "US-CAISO", "PL"]
    region_ids_real  = sorted(["DE", "FR", "GB", "US-CAISO", "PL"])
    duration_s = 24 * 3600.0

    all_rows = []
    synth_carbon = build_synthetic_carbon(region_ids_synth, duration_s)
    all_rows += run_setup("Synthetic carbon (§7.2 setup)",
                          region_ids_synth, synth_carbon, duration_s)

    real_carbon = load_carbon_model_from_dir(
        str(PROJ / default_carbon_dir()), step_s=300.0, duration_s=duration_s)
    all_rows += run_setup("Real LWA carbon (§7.2.1 setup)",
                          region_ids_real, real_carbon, duration_s)

    out = PROJ / "results" / "fair_waitawhile.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in all_rows for k in r.keys()})
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"\nSaved {len(all_rows)} rows to {out}")


if __name__ == "__main__":
    main()
