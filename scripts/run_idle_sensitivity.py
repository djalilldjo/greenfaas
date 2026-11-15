#!/usr/bin/env python3
"""Sensitivity of the scheduler comparison to the two idle-energy assumptions:
the per-container idle power and the keep-alive time (warm TTL).

Canonical workload, seed 42, multi-region and single-region GB. Idle power is
scaled by {0.25, 0.5, 1, 2} at the default 600 s keep-alive, and the
keep-alive is set to {60, 300, 1800} s at the default idle power.

Writes results/idle_sensitivity.csv. Honours GREENFAAS_CARBON_DIR.
"""
from __future__ import annotations
import csv
from dataclasses import replace

from _revision_common import ROOT, DURATION, MULTI, regions_for, carbon_for, canonical_catalog
from greenfaas import (FifoScheduler, WaitAwhileScheduler, LechowiczScheduler,
                       SpatialScheduler, GreenCourierScheduler, GreenFaaSV1Scheduler,
                       GreenFaaSScheduler, Simulator, generate_workload)

CONFIGS = [(0.25, 600.0), (0.5, 600.0), (1.0, 600.0), (2.0, 600.0),
           (1.0, 60.0), (1.0, 300.0), (1.0, 1800.0)]
SEED = 42


def scheds():
    return [
        FifoScheduler(),
        WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
        LechowiczScheduler(),
        SpatialScheduler(max_rtt_ms=80.0),
        GreenCourierScheduler(interactive_rtt_ms=20.0, deferrable_rtt_ms=80.0),
        GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
        GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
    ]


def main():
    rows = []
    for regime, ids0 in (("multi_region", MULTI), ("single_GB", ["GB"])):
        ids, cm = carbon_for(ids0)
        regions = regions_for(ids)
        base_cat = canonical_catalog()
        invs = generate_workload(duration_s=DURATION, base_rate_per_s=2.0,
                                 functions=base_cat, region_ids=ids, seed=SEED)
        for scale, ttl in CONFIGS:
            cat = [replace(f, idle_power_w=f.idle_power_w * scale) for f in base_cat]
            fn = {f.function_id: f for f in cat}
            base = None
            for s in scheds():
                r = Simulator(regions=regions, functions=fn, carbon=cm, scheduler=s,
                              warm_ttl_s=ttl).run(list(invs)).summary()
                if base is None:
                    base = r["carbon_g"]
                rows.append({
                    "regime": regime, "idle_power_scale": scale, "warm_ttl_s": ttl,
                    "scheduler": s.name, "carbon_g": round(r["carbon_g"], 2),
                    "idle_carbon_g": round(r["warm_idle_carbon_g"], 2),
                    "vs_fifo_pct": round(100 * (base - r["carbon_g"]) / base, 2),
                    "cold_pct": round(100 * r["cold_start_rate"], 2),
                    "sla_pct": round(100 * r["sla_violation_rate"], 2)})
                print(rows[-1], flush=True)
    out = ROOT / "results" / "idle_sensitivity.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
