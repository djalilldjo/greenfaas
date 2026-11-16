#!/usr/bin/env python3
"""Interactive latency-carbon guard sweep (TSC revision).

GreenFaaS routes INTERACTIVE requests within an RTT budget equal to a fraction
rho of their warm-path SLA slack (default 5%); GreenCourier uses a fixed
guard. This script compares GreenFaaS with the interactive tier pinned home,
at fixed 20/30 ms guards and at its default, against GreenCourier at 20/30 ms
with and without GreenFaaS's warm-pool controls (canonical catalog,
multi-region, three seeds), and reports carbon and interactive-tier latency.

Writes results/interactive_guard.csv. Honours GREENFAAS_CARBON_DIR.
"""
from __future__ import annotations
import csv
import statistics as st

from _revision_common import (ROOT, SEEDS, DURATION, MULTI, regions_for,
                              carbon_for, canonical_catalog)
from greenfaas import (FifoScheduler, SpatialScheduler, GreenCourierScheduler,
                       GreenFaaSScheduler, WithWarmPoolControl, Simulator,
                       generate_workload)
from greenfaas.core import LatencyClass


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
        ("GreenCourier_guard20", lambda: GreenCourierScheduler(20.0, 80.0)),
        ("GreenCourier_guard30", lambda: GreenCourierScheduler(30.0, 80.0)),
        ("GreenCourier_guard20+WP", lambda: WithWarmPoolControl(GreenCourierScheduler(20.0, 80.0))),
        ("GreenCourier_guard30+WP", lambda: WithWarmPoolControl(GreenCourierScheduler(30.0, 80.0))),
        ("GreenFaaS_guard0", lambda: GreenFaaSScheduler(interactive_rtt_ms=0.0, **gf)),
        ("GreenFaaS_guard20", lambda: GreenFaaSScheduler(interactive_rtt_ms=20.0, **gf)),
        ("GreenFaaS_guard30", lambda: GreenFaaSScheduler(interactive_rtt_ms=30.0, **gf)),
        ("GreenFaaS_default", lambda: GreenFaaSScheduler(**gf)),
        ("GreenFaaS_slack10", lambda: GreenFaaSScheduler(interactive_slack_frac=0.10, **gf)),
    ]
    acc, im, ip, iv = {}, {}, {}, {}
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
            viol = [x.sla_violated for x in res.records
                    if x.invocation.function_id in inter]
            iv.setdefault(n, []).append(100.0 * sum(viol) / len(viol))
    rows = []
    for n, _ in variants:
        red = [100.0 * (b - x) / b for b, x in zip(acc["FIFO"], acc[n])]
        rows.append({"variant": n, "vs_fifo_pct": round(st.mean(red), 2),
                     "vs_fifo_sd": round(st.pstdev(red), 2),
                     "int_mean_ms": round(st.mean(im[n]), 1),
                     "int_p95_ms": round(st.mean(ip[n]), 1),
                     "int_sla_pct": round(st.mean(iv[n]), 3),
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
