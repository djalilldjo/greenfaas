"""
greenfaas.traces.azure_2019
===========================

Loader for the Azure Functions 2019 dataset (Shahrad et al., USENIX ATC 2020).

This dataset is *aggregated* in two ways:
  1. Invocation counts are given per minute, per function (in
     invocations_per_function_md.anon.dXX.csv), not per individual call.
  2. Execution durations are given as percentile distributions per function
     (in function_durations_percentiles.anon.dXX.csv), not per call.

This module loads both and reconstructs a stream of `Invocation` objects by:
  - drawing arrival times within each minute uniformly (the common
    "thinning" reconstruction used in carbon-aware FaaS literature, e.g.
    Roy et al. CASPER ICPE'24);
  - sampling per-invocation durations from the empirical percentile
    distribution via inverse-CDF + linear interpolation.

The 2019 dataset is the standard reference workload for FaaS characterization
and is what reviewers will expect to see compared against. The 2021 dataset
(see azure_2021.py) is per-invocation and simpler to consume; we support
both because some experiments need 14 days of traffic, which only 2019
provides.

Schemas
-------
invocations_per_function_md.anon.dXX.csv:
    HashOwner, HashApp, HashFunction, Trigger,
    1, 2, ..., 1440           (invocations per minute of day XX)

function_durations_percentiles.anon.dXX.csv:
    HashOwner, HashApp, HashFunction, Average, Count, Minimum, Maximum,
    percentile_Average_0, percentile_Average_1, percentile_Average_25,
    percentile_Average_50, percentile_Average_75, percentile_Average_99,
    percentile_Average_100
"""
from __future__ import annotations

import csv
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..core import FunctionSpec, Invocation, LatencyClass


# Trigger -> latency class mapping. The 2019 dataset's Trigger field
# distinguishes user-facing from event-driven invocations directly.
TRIGGER_TO_CLASS = {
    "http": LatencyClass.INTERACTIVE,
    "queue": LatencyClass.DEFERRABLE,
    "event": LatencyClass.DEFERRABLE,
    "orchestration": LatencyClass.DEFERRABLE,
    "timer": LatencyClass.BACKGROUND,
    "storage": LatencyClass.BACKGROUND,
    "others": LatencyClass.DEFERRABLE,
}


def _short_id(s: str, prefix: str, length: int = 10) -> str:
    return f"{prefix}_{s[:length]}"


def _classify_by_trigger(trigger: str, mean_duration_ms: float) -> Tuple[LatencyClass, float]:
    cls = TRIGGER_TO_CLASS.get(trigger.lower().strip(), LatencyClass.DEFERRABLE)
    mean_s = mean_duration_ms / 1000.0
    if cls == LatencyClass.INTERACTIVE:
        return cls, max(1.0, mean_s * 5.0)
    if cls == LatencyClass.DEFERRABLE:
        return cls, max(60.0, mean_s * 20.0)
    return cls, max(3600.0, mean_s * 50.0)


def load_azure_2019_function_durations(path: str) -> Dict[str, Dict[str, float]]:
    """Load function_durations_percentiles.anon.dXX.csv.

    Returns
    -------
    Map: function_id -> { 'avg_ms', 'min_ms', 'max_ms',
                          'p0', 'p1', 'p25', 'p50', 'p75', 'p99', 'p100' }
    where function_id = _short_id(HashApp + HashFunction).
    """
    out: Dict[str, Dict[str, float]] = {}
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fn_id = _short_id(row["HashApp"] + row["HashFunction"], prefix="fn")
            out[fn_id] = {
                "avg_ms":  float(row["Average"]),
                "min_ms":  float(row["Minimum"]),
                "max_ms":  float(row["Maximum"]),
                "p0":      float(row["percentile_Average_0"]),
                "p1":      float(row["percentile_Average_1"]),
                "p25":     float(row["percentile_Average_25"]),
                "p50":     float(row["percentile_Average_50"]),
                "p75":     float(row["percentile_Average_75"]),
                "p99":     float(row["percentile_Average_99"]),
                "p100":    float(row["percentile_Average_100"]),
            }
    return out


def load_azure_2019_invocation_counts(
    path: str,
) -> Tuple[Dict[str, str], Dict[str, List[int]]]:
    """Load invocations_per_function_md.anon.dXX.csv.

    Returns
    -------
    triggers       : function_id -> trigger string.
    minute_counts  : function_id -> list of 1440 ints (per minute).
    """
    triggers: Dict[str, str] = {}
    counts: Dict[str, List[int]] = {}
    with open(path, "r", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        # Header: HashOwner, HashApp, HashFunction, Trigger, 1, 2, ..., 1440
        for row in reader:
            fn_id = _short_id(row[1] + row[2], prefix="fn")
            triggers[fn_id] = row[3]
            counts[fn_id] = [int(x) if x else 0 for x in row[4:4 + 1440]]
    return triggers, counts


def _percentile_sample(pcts: Dict[str, float], rng: random.Random) -> float:
    """Sample a duration (ms) from a percentile distribution by inverse-CDF.

    Linear-interpolates between the published percentiles. Returns ms.
    """
    u = rng.random() * 100.0
    knots = [(0.0,   pcts["p0"]),
             (1.0,   pcts["p1"]),
             (25.0,  pcts["p25"]),
             (50.0,  pcts["p50"]),
             (75.0,  pcts["p75"]),
             (99.0,  pcts["p99"]),
             (100.0, pcts["p100"])]
    for i in range(len(knots) - 1):
        p0, v0 = knots[i]
        p1, v1 = knots[i + 1]
        if p0 <= u <= p1:
            if p1 == p0:
                return v0
            return v0 + (v1 - v0) * (u - p0) / (p1 - p0)
    return knots[-1][1]


def sample_invocations_from_2019(
    triggers: Dict[str, str],
    minute_counts: Dict[str, List[int]],
    duration_pcts: Dict[str, Dict[str, float]],
    day_offset_s: float = 0.0,
    region_assignment: Optional[Dict[str, str]] = None,
    default_region: str = "DE",
    function_filter: Optional[Iterable[str]] = None,
    seed: int = 0,
    memory_mb: int = 256,
    cold_start_s: float = 1.0,
    active_power_w: float = 4.0,
    idle_power_w: float = 0.3,
) -> Tuple[List[Invocation], Dict[str, FunctionSpec]]:
    """Reconstruct an Invocation stream from the 2019 aggregated data.

    Arrivals within each minute are drawn uniformly. Per-invocation
    durations are sampled from the function's percentile distribution.

    Parameters
    ----------
    triggers, minute_counts : output of `load_azure_2019_invocation_counts`.
    duration_pcts           : output of `load_azure_2019_function_durations`.
    day_offset_s            : t=0 in the output stream corresponds to this
                              many seconds (useful for chaining multi-day files).
    function_filter         : optional set of function_ids to retain.
    region_assignment       : map function_id -> home_region; absent functions
                              default to `default_region`.
    """
    rng = random.Random(seed)
    region_assignment = region_assignment or {}
    if function_filter is not None:
        function_filter = set(function_filter)

    # Build FunctionSpecs.
    functions: Dict[str, FunctionSpec] = {}
    for fn_id, trigger in triggers.items():
        if function_filter is not None and fn_id not in function_filter:
            continue
        pcts = duration_pcts.get(fn_id)
        if pcts is None:
            continue
        mean_ms = pcts["avg_ms"]
        cls, sla = _classify_by_trigger(trigger, mean_ms)
        functions[fn_id] = FunctionSpec(
            function_id=fn_id,
            avg_runtime_s=mean_ms / 1000.0,
            runtime_std_s=max(1.0, (pcts["p75"] - pcts["p25"])) / 1000.0,
            memory_mb=memory_mb,
            cold_start_s=cold_start_s,
            active_power_w=active_power_w,
            idle_power_w=idle_power_w,
            latency_class=cls,
            sla_deadline_s=sla,
        )

    # Sample arrivals.
    invocations: List[Invocation] = []
    inv_idx = 0
    for fn_id, counts in minute_counts.items():
        if fn_id not in functions:
            continue
        for minute_idx, n in enumerate(counts):
            if n <= 0:
                continue
            minute_start = day_offset_s + minute_idx * 60.0
            for _ in range(n):
                arrival = minute_start + rng.random() * 60.0
                duration_ms = _percentile_sample(duration_pcts[fn_id], rng)
                invocations.append(Invocation(
                    invocation_id=f"inv-{inv_idx}",
                    function_id=fn_id,
                    arrival_time=arrival,
                    home_region=region_assignment.get(fn_id, default_region),
                    realized_runtime_s=max(0.001, duration_ms / 1000.0),
                    realized_memory_mb=memory_mb,
                ))
                inv_idx += 1
    invocations.sort(key=lambda inv: inv.arrival_time)
    return invocations, functions
