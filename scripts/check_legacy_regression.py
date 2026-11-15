#!/usr/bin/env python3
"""Confirm the legacy simulator switches reproduce the v1.1.0 results.

Re-runs the single-region DE setup (canonical catalog, seed 42) for FIFO,
Wait-Awhile and Lechowicz with the legacy model and compares the carbon
totals with results/legacy_v1.1.0/lechowicz_real_singleregion_DE.csv.
"""
from __future__ import annotations
import csv
import sys

from _revision_common import ROOT, DURATION, regions_for, carbon_for, canonical_catalog
from greenfaas import (FifoScheduler, WaitAwhileScheduler, LechowiczScheduler,
                       Simulator, generate_workload)

LEGACY = dict(warm_binding="decision", idle_accounting="expired_only", reuse_order="oldest")


def main():
    ref = {r["scheduler"]: float(r["carbon_g"])
           for r in csv.DictReader(open(ROOT / "results" / "legacy_v1.1.0" /
                                        "lechowicz_real_singleregion_DE.csv"))
           if r["seed"] == "42"}
    ids, cm = carbon_for(["DE"])
    regions = regions_for(ids)
    cat = canonical_catalog()
    fn = {f.function_id: f for f in cat}
    invs = generate_workload(duration_s=DURATION, base_rate_per_s=2.0, functions=cat,
                             region_ids=ids, seed=42)
    ok = True
    for s in (FifoScheduler(), WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
              LechowiczScheduler()):
        got = Simulator(regions=regions, functions=fn, carbon=cm, scheduler=s,
                        **LEGACY).run(list(invs)).summary()["carbon_g"]
        match = abs(got - ref[s.name]) < 1e-6
        ok &= match
        print(f"{s.name:12s} legacy run {got:.6f} g   committed {ref[s.name]:.6f} g   "
              f"{'OK' if match else 'MISMATCH'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
