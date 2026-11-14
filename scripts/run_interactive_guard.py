#!/usr/bin/env python3
"""Interactive latency-carbon guard sweep (TSC revision).

GreenFaaS pins INTERACTIVE requests to their home region; GreenCourier may
route them to a nearby cleaner region. This script compares the two AT EQUAL
GUARDS (0/20/30 ms of added RTT) on the canonical catalog, multi-region,
three seeds, and reports carbon and interactive-tier latency.

Writes results/interactive_guard.csv. Honours GREENFAAS_CARBON_DIR.
"""
from __future__ import annotations
import csv
import statistics as st

from _revision_common import (ROOT, SEEDS, DURATION, MULTI, regions_for,
                              carbon_for, canonical_catalog)
from greenfaas import (FifoScheduler, SpatialScheduler, GreenCourierScheduler,
                       GreenFaaSScheduler, Simulator, generate_workload)
from greenfaas.core import LatencyClass, ScheduleDecision


class GreenFaaSIntGuard(GreenFaaSScheduler):
    """GreenFaaS with an optional interactive routing guard (experiment only).

    With interactive_rtt_ms = 0 this is stock GreenFaaS. Non-interactive
    requests always take the unmodified GreenFaaS path.
    """

    def __init__(self, interactive_rtt_ms=0.0, **kw):
        super().__init__(**kw)
        self.interactive_rtt_ms = interactive_rtt_ms

    def schedule(self, invocation, state, carbon):
        fn = state.functions[invocation.function_id]
        if fn.latency_class == LatencyClass.INTERACTIVE:
            now = state.current_time
            home = state.regions[invocation.home_region]
            cands = [r.region_id for r in state.regions.values()
                     if home.rtt_to(r) <= self.interactive_rtt_ms] or [home.region_id]
            chosen = min(cands, key=lambda rid: (carbon.intensity(rid, now),
                                                 home.rtt_to(state.regions[rid])))
            return ScheduleDecision(chosen, now,
                                    state.warm_count(chosen, fn.function_id) > 0)
        return super().schedule(invocation, state, carbon)


def main():
    ids, cm = carbon_for(MULTI)
    regions = regions_for(ids)
    cat = canonical_catalog()
    fn = {f.function_id: f for f in cat}
    inter = {f.function_id for f in cat if f.latency_class == LatencyClass.INTERACTIVE}
    gf = dict(forecast_accuracy="perfect", deferrable_rtt_ms=80.0)
    variants = [
        ("FIFO", lambda: FifoScheduler()),
        ("Spatial", lambda: SpatialScheduler(max_rtt_ms=80.0)),
        ("GreenFaaS_guard0", lambda: GreenFaaSIntGuard(0.0, **gf)),
        ("GreenFaaS_guard20", lambda: GreenFaaSIntGuard(20.0, **gf)),
        ("GreenFaaS_guard30", lambda: GreenFaaSIntGuard(30.0, **gf)),
        ("GreenCourier_guard20", lambda: GreenCourierScheduler(20.0, 80.0)),
        ("GreenCourier_guard30", lambda: GreenCourierScheduler(30.0, 80.0)),
    ]
    acc, im, ip = {}, {}, {}
    for seed in SEEDS:
        invs = generate_workload(duration_s=DURATION, base_rate_per_s=2.0,
                                 functions=cat, region_ids=ids, seed=seed)
        for n, mk in variants:
            res = Simulator(regions=regions, functions=fn, carbon=cm,
                            scheduler=mk()).run(list(invs))
            lat = sorted(x.latency_s * 1000 for x in res.records
                         if x.invocation.function_id in inter)
            acc.setdefault(n, []).append(res.summary()["carbon_g"])
            im.setdefault(n, []).append(st.mean(lat))
            ip.setdefault(n, []).append(lat[int(0.95 * len(lat))])
    rows = []
    for n, _ in variants:
        red = [100.0 * (b - x) / b for b, x in zip(acc["FIFO"], acc[n])]
        rows.append({"variant": n, "vs_fifo_pct": round(st.mean(red), 2),
                     "vs_fifo_sd": round(st.pstdev(red), 2),
                     "int_mean_ms": round(st.mean(im[n]), 1),
                     "int_p95_ms": round(st.mean(ip[n]), 1),
                     "n_seeds": len(SEEDS)})
        print(rows[-1], flush=True)
    out = ROOT / "results" / "interactive_guard.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
