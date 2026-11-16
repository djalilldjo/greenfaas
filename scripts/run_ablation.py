#!/usr/bin/env python3
"""Ablation of GreenFaaS's mechanisms and of its parameters (TSC revision).

Part 1 (results/ablation.csv): which mechanism buys what, and what it costs
in latency. GreenFaaS with each mechanism removed, and the Spatial,
GreenCourier and FIFO placements given GreenFaaS's warm-pool controls
("+WP"), on four setups: the canonical synthetic workload multi-region and
single-region DE (three seeds), and the Azure 2021 trace on five regions and
on DE alone.

Part 2 (results/wp_sensitivity.csv): sensitivity to the three parameters --
queue slack share kappa, queue cap theta (in cold starts) and interactive
routing share rho -- on the synthetic multi-region setup and the Azure trace.

Honours GREENFAAS_CARBON_DIR. The Azure parts are skipped if the trace file is
absent.
"""
from __future__ import annotations
import csv
import statistics as st

from _revision_common import (ROOT, SEEDS, DURATION, MULTI, regions_for,
                              carbon_for, canonical_catalog)
from greenfaas import (FifoScheduler, SpatialScheduler, GreenCourierScheduler,
                       GreenFaaSScheduler, GreenFaaSSubmittedScheduler,
                       WithWarmPoolControl, Simulator, generate_workload)
from greenfaas.core import LatencyClass

AZURE = ROOT / "real_data" / "azure_2021" / "AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt"
INF = float("inf")


def named(s, n):
    s.name = n
    return s


def ablation_scheds():
    G = GreenFaaSScheduler
    return [
        FifoScheduler(),
        SpatialScheduler(max_rtt_ms=80.0),
        GreenCourierScheduler(20.0, 80.0),
        GreenFaaSSubmittedScheduler(),
        named(G(queue=False, keep_alive="platform"), "GreenFaaS: routing only"),
        named(G(keep_alive="platform"), "GreenFaaS: no keep-alive control"),
        named(G(queue=False), "GreenFaaS: no queueing"),
        named(G(interactive_rtt_ms=0.0), "GreenFaaS: interactive pinned home"),
        named(G(temporal=False), "GreenFaaS: no carbon deferral"),
        G(),
        WithWarmPoolControl(FifoScheduler()),
        WithWarmPoolControl(SpatialScheduler(max_rtt_ms=80.0)),
        WithWarmPoolControl(GreenCourierScheduler(20.0, 80.0)),
    ]


def sens_scheds():
    G = GreenFaaSScheduler
    out = [FifoScheduler()]
    for k in (0.1, 0.25, 0.5, 0.9):
        out.append(named(G(queue_slack_frac=k), f"kappa={k}"))
    for th in (1.0, 3.0, 10.0, INF):
        out.append(named(G(queue_cold_mult=th), f"theta={th}"))
    for rho in (0.0, 0.025, 0.05, 0.10):
        out.append(named(G(interactive_slack_frac=rho), f"rho={rho}"))
    return out


def measure(regions, fn, cm, invs, sched):
    res = Simulator(regions=regions, functions=fn, carbon=cm, scheduler=sched).run(list(invs))
    s = res.summary()
    out = {"carbon_g": s["carbon_g"], "idle_g": s["warm_idle_carbon_g"],
           "cold_pct": 100 * s["cold_start_rate"], "sla_pct": 100 * s["sla_violation_rate"]}
    for lc, tag in ((LatencyClass.INTERACTIVE, "int"), (LatencyClass.DEFERRABLE, "def"),
                    (LatencyClass.BACKGROUND, "bg")):
        rec = [x for x in res.records if fn[x.invocation.function_id].latency_class == lc]
        if not rec:
            out[f"{tag}_p50_s"] = out[f"{tag}_p95_s"] = out[f"{tag}_sla_pct"] = float("nan")
            continue
        lat = sorted(x.latency_s for x in rec)
        out[f"{tag}_p50_s"] = lat[len(lat) // 2]
        out[f"{tag}_p95_s"] = lat[int(0.95 * len(lat))]
        out[f"{tag}_sla_pct"] = 100 * sum(x.sla_violated for x in rec) / len(rec)
    return out


def synthetic_envs(ids0):
    ids, cm = carbon_for(ids0)
    regions = regions_for(ids)
    cat = canonical_catalog()
    fn = {f.function_id: f for f in cat}
    for seed in SEEDS:
        yield regions, fn, cm, generate_workload(
            duration_s=DURATION, base_rate_per_s=2.0, functions=cat,
            region_ids=ids, seed=seed)


def azure_envs(ids0):
    from greenfaas.traces import load_azure_2021_invocations
    from greenfaas.traces.azure_2021 import assign_regions_roundrobin
    ids, cm = carbon_for(sorted(ids0))
    _, f0 = load_azure_2021_invocations(str(AZURE), duration_limit_s=DURATION)
    ra = assign_regions_roundrobin(sorted(f0.keys()), ids)
    invs, fns = load_azure_2021_invocations(str(AZURE), region_assignment=ra,
                                            duration_limit_s=DURATION)
    yield regions_for(ids), {f.function_id: f for f in fns.values()}, cm, invs


def run_setup(setup, envs, make_scheds):
    acc, order = {}, []
    n = 0
    for regions, fn, cm, invs in envs:
        n += 1
        for s in make_scheds():
            if s.name not in acc:
                order.append(s.name)
            acc.setdefault(s.name, []).append(measure(regions, fn, cm, invs, s))
    rows = []
    for name in order:
        red = [100 * (b["carbon_g"] - x["carbon_g"]) / b["carbon_g"]
               for b, x in zip(acc["FIFO"], acc[name])]
        row = {"setup": setup, "scheduler": name,
               "vs_fifo_pct": round(st.mean(red), 2),
               "vs_fifo_sd": round(st.pstdev(red), 2), "n": n}
        for k in acc[name][0]:
            row[k] = round(st.mean(m[k] for m in acc[name]), 4)
        rows.append(row)
        print(f"{setup:14s} {name:36s} {row['vs_fifo_pct']:+7.2f}%  cold {row['cold_pct']:5.2f}%  "
              f"sla {row['sla_pct']:.3f}%  p95 int/def/bg "
              f"{row['int_p95_s']:.3f}/{row['def_p95_s']:.2f}/{row['bg_p95_s']:.1f}", flush=True)
    return rows


def write(name, rows):
    out = ROOT / "results" / name
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")


def main():
    have_azure = AZURE.exists()
    rows = run_setup("synthetic_multi", synthetic_envs(MULTI), ablation_scheds)
    rows += run_setup("synthetic_DE", synthetic_envs(["DE"]), ablation_scheds)
    if have_azure:
        rows += run_setup("azure_multi", azure_envs(MULTI), ablation_scheds)
        rows += run_setup("azure_DE", azure_envs(["DE"]), ablation_scheds)
    write("ablation.csv", rows)
    rows = run_setup("synthetic_multi", synthetic_envs(MULTI), sens_scheds)
    if have_azure:
        rows += run_setup("azure_multi", azure_envs(MULTI), sens_scheds)
    write("wp_sensitivity.csv", rows)


if __name__ == "__main__":
    main()
