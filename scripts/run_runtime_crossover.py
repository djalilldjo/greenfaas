#!/usr/bin/env python3
"""Runtime crossover: when does temporal shifting start to pay? (TSC revision)

Single-region runs (Spatial == FIFO by construction) with one background
function whose mean runtime tau_e is swept from FaaS scale (2.5 s) to batch
scale (1 h), deadline 6 h, active/idle power 10 W / 0.7 W. Reports, per
region and tau_e, the carbon change vs FIFO of batch-default Wait-Awhile and
of GreenFaaS, the share of background invocations GreenFaaS defers, and SLA
violations. Three seeds.

Writes results/runtime_crossover.csv. Honours GREENFAAS_CARBON_DIR.
"""
from __future__ import annotations
import csv
import statistics as st

from _revision_common import ROOT, SEEDS, DURATION, regions_for, carbon_for
from greenfaas import (FifoScheduler, WaitAwhileScheduler, GreenFaaSScheduler,
                       Simulator, generate_workload)
from greenfaas.core import FunctionSpec, LatencyClass

# (tau_e seconds, arrival rate /s) -- rate lowered for long jobs to stay
# well inside region capacity.
SWEEP = [(2.5, 0.1), (30.0, 0.1), (120.0, 0.1), (600.0, 0.1),
         (1800.0, 0.05), (3600.0, 0.05)]
DEADLINE = 21600.0


def main():
    rows = []
    for region in ("DE", "GB", "US-CAISO"):
        ids, cm = carbon_for([region])
        regions = regions_for(ids)
        for tau, rate in SWEEP:
            cat = [
                FunctionSpec("api_auth", 0.05, 0.02, 128, 0.4, 2.5, 0.2,
                             LatencyClass.INTERACTIVE, 0.5),
                FunctionSpec("batch_job", tau, tau * 0.2, 1024, 2.0, 10.0, 0.7,
                             LatencyClass.BACKGROUND, DEADLINE),
            ]
            fn = {f.function_id: f for f in cat}
            wa, gf, dfr, gsla, fsla = [], [], [], [], []
            for seed in SEEDS:
                invs = generate_workload(duration_s=DURATION, base_rate_per_s=rate,
                                         functions=cat, region_ids=ids, seed=seed,
                                         zipf_s=0.0)
                out = {}
                for s in (FifoScheduler(),
                          WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
                          GreenFaaSScheduler(forecast_accuracy="perfect",
                                             deferrable_rtt_ms=80.0)):
                    out[s.name] = Simulator(regions=regions, functions=fn, carbon=cm,
                                            scheduler=s).run(list(invs))
                b = out["FIFO"].summary()["carbon_g"]
                wa.append(100 * (b - out["Wait-Awhile"].summary()["carbon_g"]) / b)
                gf.append(100 * (b - out["GreenFaaS"].summary()["carbon_g"]) / b)
                bg = [x for x in out["GreenFaaS"].records
                      if x.invocation.function_id == "batch_job"]
                dfr.append(100 * sum(
                    1 for x in bg
                    if x.decision.start_time - x.invocation.arrival_time > 1.0) / len(bg))
                gsla.append(100 * out["GreenFaaS"].summary()["sla_violation_rate"])
                fsla.append(100 * out["FIFO"].summary()["sla_violation_rate"])
            rows.append({
                "region": region, "tau_e_s": tau, "rate_per_s": rate,
                "waitawhile_vs_fifo_pct": round(st.mean(wa), 2),
                "waitawhile_sd": round(st.pstdev(wa), 2),
                "greenfaas_vs_fifo_pct": round(st.mean(gf), 2),
                "greenfaas_sd": round(st.pstdev(gf), 2),
                "greenfaas_deferred_pct": round(st.mean(dfr), 1),
                "greenfaas_sla_pct": round(st.mean(gsla), 2),
                "fifo_sla_pct": round(st.mean(fsla), 2),
                "n_seeds": len(SEEDS)})
            print(rows[-1], flush=True)
    out = ROOT / "results" / "runtime_crossover.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
