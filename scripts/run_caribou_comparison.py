"""
Head-to-head comparison against Caribou (Gsteiger et al., SOSP'24).

Produces three result tables:
  1. Headline (5-region topology, real Azure 2021 + real EM Jan 2021, single 24h window)
  2. Time-varying topology (DE/GB/CAISO, where the lowest-carbon region varies through the day)
  3. Window-shift variance (5 non-overlapping 24h windows on the time-varying topology)

The key empirical question: does Caribou's periodic re-deployment match
GreenFaaS's per-invocation routing on FaaS workloads?

Run:
  python scripts/run_caribou_comparison.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from statistics import mean, stdev

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import (
    CaribouScheduler, FifoScheduler, GreenFaaSScheduler, GreenFaaSV1Scheduler,
    LechowiczScheduler, Region, Simulator, SpatialScheduler,
    WaitAwhileScheduler, load_carbon_model_from_dir, default_carbon_dir,
)
from greenfaas.carbon import CarbonModel, CarbonTrace
from greenfaas.core import Invocation
from greenfaas.traces import load_azure_2021_invocations
from greenfaas.traces.azure_2021 import assign_regions_roundrobin

PROJ = Path(__file__).resolve().parents[1]
AZURE = PROJ / "real_data" / "azure_2021" / "AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt"


def build_regions(region_ids):
    rtt_pairs = {("FR","DE"):15,("FR","GB"):12,("FR","US-CAISO"):145,("FR","PL"):30,
                 ("DE","GB"):20,("DE","US-CAISO"):155,("DE","PL"):15,
                 ("GB","US-CAISO"):140,("GB","PL"):30,("US-CAISO","PL"):170}
    rtt_map = {r: {} for r in region_ids}
    for (a, b), v in rtt_pairs.items():
        if a in region_ids and b in region_ids:
            rtt_map[a][b] = float(v); rtt_map[b][a] = float(v)
    return {r: Region(region_id=r, name=r, capacity=400,
                      network_rtt_ms=rtt_map[r], pue=1.2) for r in region_ids}


def schedulers(max_rtt_ms):
    return [
        ("FIFO",         FifoScheduler()),
        ("Wait-Awhile",  WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0)),
        ("Lechowicz",    LechowiczScheduler()),
        ("Spatial",      SpatialScheduler(max_rtt_ms=max_rtt_ms)),
        ("Caribou(1h)",  CaribouScheduler(redeploy_interval_s=3600.0, max_rtt_ms=max_rtt_ms)),
        ("Caribou(3h)",  CaribouScheduler(redeploy_interval_s=3*3600.0, max_rtt_ms=max_rtt_ms)),
        ("Caribou(6h)",  CaribouScheduler(redeploy_interval_s=6*3600.0, max_rtt_ms=max_rtt_ms)),
        ("Caribou(24h)", CaribouScheduler(redeploy_interval_s=24*3600.0, max_rtt_ms=max_rtt_ms)),
        ("GreenFaaS-v1", GreenFaaSV1Scheduler(forecast_accuracy="perfect", deferrable_rtt_ms=max_rtt_ms)),
        ("GreenFaaS",    GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=max_rtt_ms)),
    ]


def load_full_trace(region_ids):
    """Load the full 14-day trace ONCE and return (all_invocations, fn_map).
    Slicing happens later by re-anchoring arrival times."""
    _, fns_tmp = load_azure_2021_invocations(str(AZURE),
                                              duration_limit_s=14*86400.0)
    region_assignment = assign_regions_roundrobin(sorted(fns_tmp.keys()), region_ids)
    all_invs, functions = load_azure_2021_invocations(
        str(AZURE), region_assignment=region_assignment,
        duration_limit_s=14*86400.0,
    )
    return all_invs, {f.function_id: f for f in functions.values()}


def slice_invocations(all_invs, time_offset_s, duration_s):
    return [
        Invocation(invocation_id=inv.invocation_id,
                   function_id=inv.function_id,
                   arrival_time=inv.arrival_time - time_offset_s,
                   home_region=inv.home_region,
                   realized_runtime_s=inv.realized_runtime_s,
                   realized_memory_mb=inv.realized_memory_mb)
        for inv in all_invs
        if time_offset_s <= inv.arrival_time < time_offset_s + duration_s
    ]


def load_workload(region_ids, duration_s, time_offset_s=0.0):
    """Compatibility wrapper. Slower; prefer load_full_trace + slice_invocations."""
    all_invs, fn_map = load_full_trace(region_ids)
    return slice_invocations(all_invs, time_offset_s, duration_s), fn_map


def slice_carbon(full_carbon, region_ids, offset_s, duration_s):
    new_traces = {}
    for r in region_ids:
        if r not in full_carbon.traces:
            continue
        t = full_carbon.traces[r]
        step = t.step_s
        start_idx = int(offset_s / step)
        end_idx = min(len(t.values), start_idx + int(duration_s / step) + 1)
        new_traces[r] = CarbonTrace(region_id=r, values=t.values[start_idx:end_idx], step_s=step)
    return CarbonModel(traces=new_traces)


def run_table(name, region_ids, max_rtt_ms, full_carbon, time_offset_s=0.0, duration_s=24*3600.0):
    invs, fn_map = load_workload(region_ids, duration_s, time_offset_s)
    carbon = slice_carbon(full_carbon, region_ids, time_offset_s, duration_s)
    regions = build_regions(region_ids)
    print(f"\n=== {name} | regions: {region_ids} | RTT budget: {max_rtt_ms}ms ===")
    print(f"  invocations: {len(invs):,}, window: [{time_offset_s/3600:.0f}h, {(time_offset_s+duration_s)/3600:.0f}h)")
    rows = []
    for sname, sched in schedulers(max_rtt_ms):
        res = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                        scheduler=sched).run(invs).summary()
        rows.append({"topology": name, "scheduler": sname,
                     "carbon_g": res["carbon_g"], "sla_viol": res["sla_violation_rate"],
                     "cold_rate": res["cold_start_rate"]})
    fifo = rows[0]["carbon_g"]
    print(f"  {'scheduler':<14} {'carbon(g)':>11} {'vs FIFO':>9}")
    print("  " + "-" * 36)
    for r in rows:
        red = (fifo - r["carbon_g"]) / fifo * 100 if fifo else 0
        r["reduction_pct"] = red
        print(f"  {r['scheduler']:<14} {r['carbon_g']:>11.2f} {red:>+8.2f}%")
    return rows


def main():
    carbon_dir = str(PROJ / default_carbon_dir())
    full_carbon = load_carbon_model_from_dir(carbon_dir, step_s=300.0,
                                              duration_s=14*86400.0)
    print(f"Carbon source: {carbon_dir}")

    # Load full 14-day Azure trace ONCE with all 5 regions assigned.
    all_region_ids = sorted(["DE", "FR", "GB", "US-CAISO", "PL"])
    print(f"Loading full 14-day Azure trace once (5-region assignment)...")
    import time
    t0 = time.time()
    all_invs, fn_map = load_full_trace(all_region_ids)
    print(f"  Loaded {len(all_invs):,} invocations in {time.time()-t0:.1f}s")

    all_rows = []
    cached_filtered_invs = None

    # Table 1: headline 5-region (where FR dominates)
    rows1, _ = run_table_cached(
        "Full 5-region (FR dominates)",
        all_region_ids, 80.0, full_carbon, all_invs, fn_map,
    )
    all_rows += rows1

    # Table 2: time-varying topology (DE/GB/CAISO) — keep cached
    rows2, cached_filtered_invs = run_table_cached(
        "Time-varying winner (DE/GB/CAISO)",
        ["DE", "GB", "US-CAISO"], 200.0, full_carbon, all_invs, fn_map,
    )
    all_rows += rows2

    # Table 3: coal-belt
    rows3, _ = run_table_cached(
        "Coal-belt (DE/GB/PL)",
        ["DE", "GB", "PL"], 80.0, full_carbon, all_invs, fn_map,
    )
    all_rows += rows3

    out = PROJ / "results" / "caribou_comparison.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        for r in all_rows: w.writerow(r)
    print(f"\nSaved {len(all_rows)} rows to {out}")

    # Window-shift variance on the time-varying topology, using the cached filtered trace.
    # Reduced scope: 3 windows × Caribou-specific schedulers only (FIFO/Spatial/GF
    # window-variance is already characterized in §7.2.4).
    print("\n" + "=" * 72)
    print("Window-shift variance on time-varying topology (3 windows)")
    print("=" * 72)
    region_ids = ["DE", "GB", "US-CAISO"]
    max_rtt = 200.0
    regions = build_regions(region_ids)
    variance_scheds = [
        ("FIFO", FifoScheduler()),
        ("Spatial", SpatialScheduler(max_rtt_ms=max_rtt)),
        ("Caribou(1h)", CaribouScheduler(redeploy_interval_s=3600.0, max_rtt_ms=max_rtt)),
        ("Caribou(6h)", CaribouScheduler(redeploy_interval_s=6*3600.0, max_rtt_ms=max_rtt)),
        ("Caribou(24h)", CaribouScheduler(redeploy_interval_s=24*3600.0, max_rtt_ms=max_rtt)),
        ("GreenFaaS", GreenFaaSScheduler(forecast_accuracy="perfect", deferrable_rtt_ms=max_rtt)),
    ]
    raw_rows = []
    for day in [0, 2, 4]:  # 3 windows
        offset = day * 86400.0
        win_invs = slice_invocations(cached_filtered_invs, offset, 24*3600.0)
        if not win_invs: continue
        carbon = slice_carbon(full_carbon, region_ids, offset, 24*3600.0)
        for sname, sched in variance_scheds:
            res = Simulator(regions=regions, functions=fn_map,
                            carbon=carbon,
                            scheduler=sched).run(win_invs).summary()
            raw_rows.append({"window_day": day, "scheduler": sname,
                            "invocations": len(win_invs),
                            "carbon_g": res["carbon_g"]})

    from collections import defaultdict
    buckets = defaultdict(list)
    for r in raw_rows:
        buckets[r["scheduler"]].append((r["window_day"], r["carbon_g"]))
    fifo_per_w = {wd: c for wd, c in buckets["FIFO"]}
    print(f"\n{'Scheduler':<15} {'vs FIFO mean ± std':>22}")
    print("-" * 38)
    summary_rows = []
    for sname in ["Spatial", "Caribou(1h)", "Caribou(6h)", "Caribou(24h)", "GreenFaaS"]:
        reductions = [(fifo_per_w[wd] - c) / fifo_per_w[wd] * 100
                      for wd, c in buckets[sname]]
        m, s = mean(reductions), stdev(reductions)
        print(f"  {sname:<13} {m:>+8.2f}% ± {s:>4.2f}%")
        summary_rows.append({"scheduler": sname, "mean_pct": m, "std_pct": s,
                             "n_windows": len(reductions)})

    summary_out = PROJ / "results" / "caribou_window_variance.csv"
    with open(summary_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        for r in summary_rows: w.writerow(r)
    print(f"\nSaved {len(summary_rows)} variance summary rows to {summary_out}")


def run_table_cached(name, region_ids, max_rtt_ms, full_carbon,
                     all_invs, fn_map):
    # Filter invocations whose home_region is in this topology.
    filtered_invs_unsliced = [inv for inv in all_invs if inv.home_region in region_ids]
    invs = slice_invocations(filtered_invs_unsliced, 0.0, 24*3600.0)
    carbon = slice_carbon(full_carbon, region_ids, 0.0, 24*3600.0)
    regions = build_regions(region_ids)
    print(f"\n=== {name} | regions: {region_ids} | RTT budget: {max_rtt_ms}ms ===")
    print(f"  invocations: {len(invs):,}")
    rows = []
    for sname, sched in schedulers(max_rtt_ms):
        res = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                        scheduler=sched).run(invs).summary()
        rows.append({"topology": name, "scheduler": sname,
                     "carbon_g": res["carbon_g"], "sla_viol": res["sla_violation_rate"],
                     "cold_rate": res["cold_start_rate"]})
    fifo = rows[0]["carbon_g"]
    print(f"  {'scheduler':<14} {'carbon(g)':>11} {'vs FIFO':>9}")
    print("  " + "-" * 36)
    for r in rows:
        red = (fifo - r["carbon_g"]) / fifo * 100 if fifo else 0
        r["reduction_pct"] = red
        print(f"  {r['scheduler']:<14} {r['carbon_g']:>11.2f} {red:>+8.2f}%")
    return rows, filtered_invs_unsliced


if __name__ == "__main__":
    main()
