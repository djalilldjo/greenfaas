"""
Window-shift variance experiment on time-aligned real Azure 2021 trace
+ real ElectricityMaps Jan 2021 carbon data.

The deterministic-assignment limitation of multi-seed variance tests on
fixed real traces (round-robin function-to-region assignment produces
identical outcomes regardless of seed) is addressed here by varying the
24-hour *window* within the 14-day trace instead of varying assignment
seed. Each run uses a 24h slice starting at trace-time t = D days,
where D in {0, 1, 2, 3, 4} (5 non-overlapping or slightly overlapping
24h windows, all within the 14-day Azure trace and matching 14-day
EM carbon trace).

Each window pairs:
  - 24h slice of Azure trace starting at day D (via time_offset_s param)
  - 24h slice of carbon trace starting at day D (via values list slicing
    after CarbonModel load)

Outputs:
  - Console table with per-window and aggregate mean +- std results.
  - results/real_workload_window_variance.csv
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from statistics import mean, stdev
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import (
    FifoScheduler, GreenFaaSScheduler, GreenFaaSV1Scheduler,
    LechowiczScheduler, Region, Simulator, SpatialScheduler,
    WaitAwhileScheduler, load_carbon_model_from_dir,
    default_carbon_dir,
)
from greenfaas.carbon import CarbonModel, CarbonTrace
from greenfaas.traces import load_azure_2021_invocations
from greenfaas.traces.azure_2021 import assign_regions_roundrobin

PROJ = Path(__file__).resolve().parents[1]
AZURE_2021_PATH = PROJ / "real_data" / "azure_2021" / "AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt"


def shift_carbon_window(full_carbon, day_offset, slice_duration_s):
    """Return a new CarbonModel whose t=0 corresponds to day_offset of the
    original trace, truncated to slice_duration_s.

    The carbon trace is sampled at full_carbon.traces[r].step_s. The
    day_offset is converted to a step index, and we slice [start_idx:end_idx].
    """
    offset_s = day_offset * 86400.0
    new_traces = {}
    for r, t in full_carbon.traces.items():
        step = t.step_s
        n_full = len(t.values)
        start_idx = int(offset_s / step)
        end_idx = min(n_full, start_idx + int(slice_duration_s / step) + 1)
        new_values = t.values[start_idx:end_idx]
        new_traces[r] = CarbonTrace(region_id=r, values=new_values, step_s=step)
    return CarbonModel(traces=new_traces)


def build_regions(region_ids):
    rtt_pairs = {("FR","DE"):15,("FR","GB"):12,("FR","US-CAISO"):145,("FR","PL"):30,
                 ("DE","GB"):20,("DE","US-CAISO"):155,("DE","PL"):15,
                 ("GB","US-CAISO"):140,("GB","PL"):30,("US-CAISO","PL"):170}
    rtt_map = {r: {} for r in region_ids}
    for (a,b),v in rtt_pairs.items():
        if a in region_ids and b in region_ids:
            rtt_map[a][b] = float(v); rtt_map[b][a] = float(v)
    return {r: Region(region_id=r, name=r, capacity=400,
                      network_rtt_ms=rtt_map[r], pue=1.2) for r in region_ids}


def main():
    duration_s = 24 * 3600.0
    region_ids = sorted(["DE","FR","GB","US-CAISO","PL"])
    carbon_dir = str(PROJ / default_carbon_dir())

    print("=" * 72)
    print("Window-shift variance on real Azure 2021 + real EM Jan 2021")
    print("=" * 72)
    print(f"Carbon: {carbon_dir}")
    print(f"Windows: day offsets [0, 1, 2, 3, 4], each 24h")

    # Load full 14-day carbon trace (or as much as the CSVs cover).
    full_carbon = load_carbon_model_from_dir(carbon_dir, step_s=300.0, duration_s=14*86400.0)
    print(f"Carbon trace loaded: {len(next(iter(full_carbon.traces.values())).values)} steps")

    # Pre-build function ID list (deterministic across windows since the
    # full trace's function set is consistent).
    print("\nIndexing Azure trace function IDs...")
    t0 = time.time()
    _, fns_all = load_azure_2021_invocations(
        str(AZURE_2021_PATH), duration_limit_s=14*86400.0,
    )
    function_ids = sorted(fns_all.keys())
    region_assignment = assign_regions_roundrobin(function_ids, region_ids)
    print(f"  {len(fns_all)} functions in {time.time()-t0:.1f}s")

    regions = build_regions(region_ids)

    scheds = {
        'FIFO':         lambda: FifoScheduler(),
        'Wait-Awhile':  lambda: WaitAwhileScheduler(threshold_g=200.0, max_defer_s=1800.0),
        'Lechowicz':    lambda: LechowiczScheduler(),
        'Spatial':      lambda: SpatialScheduler(max_rtt_ms=80.0),
        'GreenFaaS-v1': lambda: GreenFaaSV1Scheduler(forecast_accuracy='perfect', deferrable_rtt_ms=80.0),
        'GreenFaaS':    lambda: GreenFaaSScheduler(forecast_accuracy='perfect', deferrable_rtt_ms=80.0),
    }

    # We need to load the full trace once with its full timestamps so we can
    # extract per-window slices via time_offset_s. The loader uses time_offset_s
    # by subtracting it from every arrival; default offset = earliest arrival.
    # To slice "day D", we want to keep only arrivals in [D*86400, (D+1)*86400)
    # of the original trace, then re-anchor.
    print("\nLoading full 14-day Azure trace once...")
    t0 = time.time()
    all_invs, fns_full = load_azure_2021_invocations(
        str(AZURE_2021_PATH),
        region_assignment=region_assignment,
        duration_limit_s=14*86400.0,
    )
    fn_map_full = {f.function_id: f for f in fns_full.values()}
    print(f"  {len(all_invs):,} invocations in {time.time()-t0:.1f}s")

    rows = []
    for day_offset in [0, 1, 2, 3, 4]:
        win_start = day_offset * 86400.0
        win_end = win_start + duration_s
        # Re-anchor: keep arrivals in window, subtract win_start so t starts at 0.
        from greenfaas.core import Invocation
        win_invs = [
            Invocation(
                invocation_id=inv.invocation_id,
                function_id=inv.function_id,
                arrival_time=inv.arrival_time - win_start,
                home_region=inv.home_region,
                realized_runtime_s=inv.realized_runtime_s,
                realized_memory_mb=inv.realized_memory_mb,
            )
            for inv in all_invs
            if win_start <= inv.arrival_time < win_end
        ]
        if not win_invs:
            print(f"  window day={day_offset}: empty (no invocations in slice)")
            continue
        win_carbon = shift_carbon_window(full_carbon, day_offset, duration_s)
        print(f"\n--- window day={day_offset}: {len(win_invs):,} invocations ---")
        for n, factory in scheds.items():
            res = Simulator(regions=regions, functions=fn_map_full,
                            carbon=win_carbon, scheduler=factory()).run(win_invs).summary()
            rows.append({
                'window_day': day_offset,
                'scheduler': n,
                'invocations': len(win_invs),
                'carbon_g': res['carbon_g'],
                'cold_rate': res['cold_start_rate'],
                'sla_viol': res['sla_violation_rate'],
            })

    # Summary
    buckets = defaultdict(list)
    for r in rows:
        buckets[r['scheduler']].append((r['window_day'], r['carbon_g'], r['cold_rate']))

    fifo_per_window = {wd: c for wd, c, _ in buckets['FIFO']}

    print(f"\n{'Scheduler':<14} {'Carbon (g) mean+-std':>22} {'vs FIFO mean+-std':>22}")
    print('-' * 60)
    summary = []
    for name in ['FIFO','Wait-Awhile','Lechowicz','Spatial','GreenFaaS-v1','GreenFaaS']:
        carbons = [c for _, c, _ in buckets[name]]
        reductions = [(fifo_per_window[wd] - c) / fifo_per_window[wd] * 100
                      for wd, c, _ in buckets[name]]
        cm, cs = mean(carbons), stdev(carbons)
        rm, rs = mean(reductions), stdev(reductions)
        print(f'  {name:<12} {cm:>10.2f} +- {cs:>5.2f} g    {rm:>+7.2f}% +- {rs:>4.2f}%')
        summary.append({'scheduler':name, 'carbon_mean_g':cm, 'carbon_std_g':cs,
                        'reduction_mean_pct':rm, 'reduction_std_pct':rs,
                        'n_windows':len(carbons)})

    out_raw = PROJ / "results" / "real_workload_window_variance_raw.csv"
    out_summary = PROJ / "results" / "real_workload_window_variance.csv"
    out_raw.parent.mkdir(parents=True, exist_ok=True)
    with open(out_raw, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows: w.writerow(r)
    with open(out_summary, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        for r in summary: w.writerow(r)
    print(f"\nSaved {len(rows)} raw rows to {out_raw}")
    print(f"Saved {len(summary)} summary rows to {out_summary}")


if __name__ == "__main__":
    main()
