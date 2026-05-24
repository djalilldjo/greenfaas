"""
greenfaas.workload
==================

Workload generation. The first iteration produces synthetic, Azure-Functions-
like arrivals; the same module will later load real Azure 2019/2021 CSVs and
emit Invocation streams without changes to the rest of the pipeline.

Modelling choices:
  - Inter-arrival times follow a non-homogeneous Poisson process whose rate
    is modulated by a diurnal envelope (peak in business hours, trough at
    night).
  - Functions are drawn from a heavy-tailed popularity distribution (Zipf):
    a small number of "hot" functions account for most invocations, matching
    the Shahrad et al. (USENIX ATC 2020) characterisation.
  - Per-invocation runtime is sampled from a log-normal around the spec mean.
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Sequence

from .core import FunctionSpec, Invocation, LatencyClass


def make_default_function_catalog() -> List[FunctionSpec]:
    """A small but representative catalog of functions across SLA classes."""
    return [
        FunctionSpec(
            function_id="api_auth",
            avg_runtime_s=0.05,
            runtime_std_s=0.02,
            memory_mb=128,
            cold_start_s=0.4,
            active_power_w=2.5,
            idle_power_w=0.2,
            latency_class=LatencyClass.INTERACTIVE,
            sla_deadline_s=0.5,
        ),
        FunctionSpec(
            function_id="api_search",
            avg_runtime_s=0.15,
            runtime_std_s=0.08,
            memory_mb=256,
            cold_start_s=0.8,
            active_power_w=4.0,
            idle_power_w=0.3,
            latency_class=LatencyClass.INTERACTIVE,
            sla_deadline_s=1.0,
        ),
        FunctionSpec(
            function_id="webhook_handler",
            avg_runtime_s=0.3,
            runtime_std_s=0.15,
            memory_mb=256,
            cold_start_s=1.0,
            active_power_w=4.0,
            idle_power_w=0.3,
            latency_class=LatencyClass.DEFERRABLE,
            sla_deadline_s=30.0,
        ),
        FunctionSpec(
            function_id="thumbnail_gen",
            avg_runtime_s=1.2,
            runtime_std_s=0.5,
            memory_mb=512,
            cold_start_s=1.5,
            active_power_w=7.0,
            idle_power_w=0.5,
            latency_class=LatencyClass.DEFERRABLE,
            sla_deadline_s=120.0,
        ),
        FunctionSpec(
            function_id="log_ingest",
            avg_runtime_s=0.6,
            runtime_std_s=0.3,
            memory_mb=256,
            cold_start_s=0.8,
            active_power_w=4.0,
            idle_power_w=0.3,
            latency_class=LatencyClass.BACKGROUND,
            sla_deadline_s=3600.0,
        ),
        FunctionSpec(
            function_id="nightly_report",
            avg_runtime_s=2.5,
            runtime_std_s=1.0,
            memory_mb=1024,
            cold_start_s=2.0,
            active_power_w=10.0,
            idle_power_w=0.7,
            latency_class=LatencyClass.BACKGROUND,
            sla_deadline_s=14400.0,
        ),
    ]


def _diurnal_factor(t: float) -> float:
    """Multiplier in [0.25, 1.75] modelling business-hour load."""
    hour = (t % 86400.0) / 3600.0  # 0..24
    # Peak around 14:00 local, trough around 04:00.
    return 1.0 + 0.75 * math.sin(2 * math.pi * (hour - 8.0) / 24.0)


def generate_workload(
    duration_s: float,
    base_rate_per_s: float,
    functions: Sequence[FunctionSpec],
    region_ids: Sequence[str],
    region_weights: Sequence[float] | None = None,
    zipf_s: float = 1.2,
    seed: int = 0,
) -> List[Invocation]:
    """Generate a list of invocations covering [0, duration_s).

    Parameters
    ----------
    duration_s         : simulated wall-clock span.
    base_rate_per_s    : peak Poisson rate (will be modulated by diurnal cycle).
    functions          : function catalog to draw from.
    region_ids         : where requests can originate.
    region_weights     : prior over origin regions (defaults to uniform).
    zipf_s             : Zipf shape parameter for function popularity.
    seed               : RNG seed.
    """
    rng = random.Random(seed)
    if region_weights is None:
        region_weights = [1.0] * len(region_ids)

    # Pre-compute Zipf weights
    fn_weights = [1.0 / ((i + 1) ** zipf_s) for i in range(len(functions))]

    invocations: List[Invocation] = []
    t = 0.0
    inv_idx = 0
    while t < duration_s:
        # Non-homogeneous Poisson via thinning
        lam = base_rate_per_s * _diurnal_factor(t)
        # Sample inter-arrival from envelope max for safety
        max_lam = base_rate_per_s * 1.75
        dt = rng.expovariate(max_lam)
        t += dt
        if t >= duration_s:
            break
        if rng.random() > lam / max_lam:
            continue
        fn = rng.choices(list(functions), weights=fn_weights, k=1)[0]
        # Lognormal parameterisation: we want E[X] = avg_runtime, so set
        #   mu = log(avg) - sigma^2/2
        # rather than mu = log(avg). The latter biases the mean upward
        # by a factor of exp(sigma^2/2), inflating durations and SLA
        # violation rates uniformly across schedulers.
        avg = max(1e-3, fn.avg_runtime_s)
        sigma = max(0.05, fn.runtime_std_s / avg)
        mu = math.log(avg) - 0.5 * sigma * sigma
        runtime = max(0.005, rng.lognormvariate(mu=mu, sigma=sigma))
        region = rng.choices(list(region_ids), weights=list(region_weights), k=1)[0]
        invocations.append(Invocation(
            invocation_id=f"inv-{inv_idx}",
            function_id=fn.function_id,
            arrival_time=t,
            home_region=region,
            realized_runtime_s=runtime,
            realized_memory_mb=fn.memory_mb,
        ))
        inv_idx += 1
    return invocations
