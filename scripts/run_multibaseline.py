#!/usr/bin/env python3
"""Multi-baseline comparison (TSC revision).

Eight schedulers -- FIFO, Wait-Awhile, Lechowicz, Spatial, Caribou,
GreenCourier, GreenFaaS-v1 (ablation), GreenFaaS -- on real carbon traces in
four regimes: multi-region (FR/DE/GB/US-CAISO/PL) and single-region DE, GB,
CAISO. Three seeds (42-44), 24 h, 2 invocations/s.

    python scripts/run_multibaseline.py                      # canonical catalog
    python scripts/run_multibaseline.py --catalog long-deadline   # stress test

Writes results/multibaseline_<catalog>.csv. Honours GREENFAAS_CARBON_DIR.
"""
from __future__ import annotations
import argparse
import csv
import statistics as st

from _revision_common import (ROOT, SEEDS, DURATION, MULTI, regions_for,
                              carbon_for, canonical_catalog, long_deadline_catalog)
from greenfaas import (
    FifoScheduler, WaitAwhileScheduler, LechowiczScheduler, SpatialScheduler,
    CaribouScheduler, GreenCourierScheduler, GreenFaaSV1Scheduler,
    GreenFaaSScheduler, Simulator, generate_workload,
)

REGIMES = {
    "multi_region": MULTI,
    "single_DE": ["DE"],
    "single_GB": ["GB"],
    "single_CAISO": ["US-CAISO"],
}


def all_scheds():
    return [
        FifoScheduler(),
        WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
        LechowiczScheduler(),
        SpatialScheduler(max_rtt_ms=80.0),
        CaribouScheduler(redeploy_interval_s=3600.0, max_rtt_ms=80.0),
        GreenCourierScheduler(interactive_rtt_ms=20.0, deferrable_rtt_ms=80.0),
        GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
        GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=80.0),
    ]


def run(regime, ids, cat):
    ids, cm = carbon_for(ids)
    regions = regions_for(ids)
    fn = {f.function_id: f for f in cat}
    acc, sla, cold, order = {}, {}, {}, []
    for seed in SEEDS:
        invs = generate_workload(duration_s=DURATION, base_rate_per_s=2.0,
                                 functions=cat, region_ids=ids, seed=seed)
        for s in all_scheds():
            r = Simulator(regions=regions, functions=fn, carbon=cm,
                          scheduler=s).run(list(invs)).summary()
            if s.name not in acc:
                order.append(s.name)
            acc.setdefault(s.name, []).append(r["carbon_g"])
            sla.setdefault(s.name, []).append(r["sla_violation_rate"])
            cold.setdefault(s.name, []).append(r["cold_start_rate"])
    rows = []
    print(f"\n=== {regime} {ids} ===", flush=True)
    for n in order:
        red = [100.0 * (b - x) / b for b, x in zip(acc["FIFO"], acc[n])]
        row = {"regime": regime, "scheduler": n,
               "carbon_g": round(st.mean(acc[n]), 2),
               "vs_fifo_pct": round(st.mean(red), 2),
               "vs_fifo_sd": round(st.pstdev(red), 2),
               "sla_pct": round(100 * st.mean(sla[n]), 2),
               "cold_pct": round(100 * st.mean(cold[n]), 2),
               "n_seeds": len(SEEDS)}
        rows.append(row)
        print(f"{n:14s}{row['carbon_g']:10.2f} g {row['vs_fifo_pct']:+9.2f}% "
              f"(sd {row['vs_fifo_sd']:.2f})  sla {row['sla_pct']:.2f}%  "
              f"cold {row['cold_pct']:.2f}%", flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", choices=["canonical", "long-deadline"],
                    default="canonical")
    args = ap.parse_args()
    cat = canonical_catalog() if args.catalog == "canonical" else long_deadline_catalog()
    rows = []
    for regime, ids in REGIMES.items():
        rows += run(regime, ids, cat)
    out = ROOT / "results" / f"multibaseline_{args.catalog.replace('-', '_')}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
