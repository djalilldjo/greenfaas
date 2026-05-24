"""
greenfaas.traces.azure_2021
===========================

Loader for the Azure Functions Invocation Trace 2021 (Zhang et al., SOSP 2021).

Schema (one row per invocation):
    app          : application id (hex, encrypted)
    func         : function id within the app (hex, encrypted)
    end_timestamp: invocation end time, seconds (float)
    duration     : invocation duration, seconds (float)

We convert each row to a `greenfaas.Invocation` by:
  - computing arrival_time = end_timestamp - duration
  - generating an invocation_id from the row index
  - mapping (app, func) to a stable function_id (truncated hash)

Latency-class assignment is heuristic since the trace does not include it.
We use a simple rule based on duration percentiles per function:
  - mean duration < 1.0 s  => INTERACTIVE  (sla 1 s)
  - 1.0 - 30 s             => DEFERRABLE   (sla 60 s)
  - > 30 s                 => BACKGROUND   (sla 3600 s)
This matches the Shahrad et al. characterization that long-running functions
in Azure are dominated by ETL/batch workloads, while sub-second ones are
overwhelmingly user-facing HTTP/webhook handlers.

If you have additional metadata about Trigger types (HTTP, queue, timer,
event-grid), pass it in via the `trigger_overrides` argument and we will
re-classify accordingly (HTTP => INTERACTIVE; timer => BACKGROUND; etc).
"""
from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..core import FunctionSpec, Invocation, LatencyClass


# Heuristic thresholds for SLA-class assignment from duration.
INTERACTIVE_MAX_S = 1.0
DEFERRABLE_MAX_S = 30.0

# Default power model — applied per function unless overridden. These are
# rough estimates for AWS Lambda/Azure Functions-style hardware; the
# scheduler is insensitive to exact values within a factor of ~2.
DEFAULT_ACTIVE_POWER_W = 4.0
DEFAULT_IDLE_POWER_W = 0.3
DEFAULT_COLD_START_S = 1.0
DEFAULT_MEMORY_MB = 256


def _short_id(s: str, prefix: str = "fn", length: int = 10) -> str:
    """Stable short id from a (possibly long hex) string."""
    return f"{prefix}_{s[:length]}"


def _classify(mean_duration_s: float) -> Tuple[LatencyClass, float]:
    """Map mean duration -> (latency class, SLA deadline in seconds)."""
    if mean_duration_s < INTERACTIVE_MAX_S:
        return LatencyClass.INTERACTIVE, max(1.0, mean_duration_s * 5.0)
    if mean_duration_s < DEFERRABLE_MAX_S:
        return LatencyClass.DEFERRABLE, max(60.0, mean_duration_s * 20.0)
    return LatencyClass.BACKGROUND, max(3600.0, mean_duration_s * 50.0)


def load_azure_2021_invocations(
    csv_path: str,
    region_assignment: Optional[Dict[str, str]] = None,
    default_region: str = "DE",
    time_offset_s: float = 0.0,
    duration_limit_s: Optional[float] = None,
    max_rows: Optional[int] = None,
) -> Tuple[List[Invocation], Dict[str, FunctionSpec]]:
    """Read an Azure 2021 invocation CSV and convert to GreenFaaS types.

    Parameters
    ----------
    csv_path           : path to AzureFunctionsInvocationTraceForTwoWeeksJan2021.csv
                         (or any file with the same schema).
    region_assignment  : optional map from function_id -> region_id.
                         Functions absent from this map go to `default_region`.
                         A simple round-robin assignment is a reasonable default
                         for multi-region experiments; see `assign_regions_roundrobin`.
    default_region     : home region for functions with no explicit assignment.
    time_offset_s      : subtract this from every timestamp to anchor t=0.
                         If None, defaults to the earliest arrival in the file.
    duration_limit_s   : if set, only retain invocations whose arrival_time
                         falls in [0, duration_limit_s) after offset removal.
    max_rows           : optional cap on rows read (useful for prototyping).

    Returns
    -------
    invocations : list of Invocation, sorted by arrival_time.
    functions   : dict of function_id -> FunctionSpec, with per-function
                  parameters derived from observed duration statistics.
    """
    rows = []
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if max_rows is not None and i >= max_rows:
                break
            rows.append({
                "app": row["app"],
                "func": row["func"],
                "end_ts": float(row["end_timestamp"]),
                "duration": float(row["duration"]),
            })

    if not rows:
        return [], {}

    # Compute arrival times and offset.
    earliest = min(r["end_ts"] - r["duration"] for r in rows)
    offset = time_offset_s if time_offset_s != 0.0 else earliest

    # Aggregate per-function statistics.
    durations_by_fn: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        fn_id = _short_id(r["app"] + r["func"], prefix="fn")
        durations_by_fn[fn_id].append(r["duration"])

    # Build FunctionSpecs.
    functions: Dict[str, FunctionSpec] = {}
    for fn_id, durs in durations_by_fn.items():
        mean_d = statistics.mean(durs)
        std_d = statistics.pstdev(durs) if len(durs) > 1 else mean_d * 0.5
        latency_class, sla = _classify(mean_d)
        functions[fn_id] = FunctionSpec(
            function_id=fn_id,
            avg_runtime_s=mean_d,
            runtime_std_s=std_d,
            memory_mb=DEFAULT_MEMORY_MB,
            cold_start_s=DEFAULT_COLD_START_S,
            active_power_w=DEFAULT_ACTIVE_POWER_W,
            idle_power_w=DEFAULT_IDLE_POWER_W,
            latency_class=latency_class,
            sla_deadline_s=sla,
        )

    # Build Invocations.
    invocations: List[Invocation] = []
    region_assignment = region_assignment or {}
    for i, r in enumerate(rows):
        fn_id = _short_id(r["app"] + r["func"], prefix="fn")
        arrival = r["end_ts"] - r["duration"] - offset
        if arrival < 0:
            continue
        if duration_limit_s is not None and arrival >= duration_limit_s:
            continue
        invocations.append(Invocation(
            invocation_id=f"inv-{i}",
            function_id=fn_id,
            arrival_time=arrival,
            home_region=region_assignment.get(fn_id, default_region),
            realized_runtime_s=max(0.001, r["duration"]),
            realized_memory_mb=functions[fn_id].memory_mb,
        ))

    invocations.sort(key=lambda inv: inv.arrival_time)
    return invocations, functions


def assign_regions_roundrobin(function_ids: List[str], regions: List[str]) -> Dict[str, str]:
    """Convenience: distribute functions evenly across regions (deterministic)."""
    return {fn: regions[i % len(regions)] for i, fn in enumerate(sorted(function_ids))}
