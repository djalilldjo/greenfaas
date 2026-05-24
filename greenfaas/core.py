"""
greenfaas.core
==============

Core data model for the GreenFaaS simulator.

Defines the entities that flow through the simulator: regions, function
specifications, invocations, scheduling decisions, and system state. Kept
deliberately framework-agnostic so the same types can be lifted into a
faas-sim / vessim integration later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class LatencyClass(str, Enum):
    """SLA tier of a function invocation.

    INTERACTIVE  - user-facing; sub-second deadlines; cannot be deferred or
                   routed to a distant region.
    DEFERRABLE   - event-driven but with user-visible effect on a short time
                   scale (seconds to a minute or two).
    BACKGROUND   - asynchronous, long-deadline (minutes to hours); fully
                   eligible for temporal and spatial shifting.
    """

    INTERACTIVE = "interactive"
    DEFERRABLE = "deferrable"
    BACKGROUND = "background"


@dataclass(frozen=True)
class Region:
    """A geographic region in which functions can execute.

    Attributes
    ----------
    region_id        : short identifier, e.g. "FR", "DE", "US-CAISO".
    name             : human-readable name.
    capacity         : maximum concurrently executing invocations.
    network_rtt_ms   : map from other region_id to round-trip latency in ms.
                       Used to penalise spatial routing of latency-sensitive
                       invocations.
    pue              : Power Usage Effectiveness of the data center
                       (multiplier on IT power to get total facility power).
    price_per_gb_s   : public-cloud-style price for memory * runtime, USD.
    """

    region_id: str
    name: str
    capacity: int
    network_rtt_ms: Dict[str, float] = field(default_factory=dict)
    pue: float = 1.2
    price_per_gb_s: float = 0.0000166667  # AWS Lambda-style baseline

    def rtt_to(self, other: "Region") -> float:
        if other.region_id == self.region_id:
            return 0.0
        return self.network_rtt_ms.get(other.region_id, 100.0)


@dataclass(frozen=True)
class FunctionSpec:
    """Static description of a function deployed on the platform.

    Attributes
    ----------
    function_id      : unique identifier.
    avg_runtime_s    : mean execution time on a warm container, in seconds.
    runtime_std_s    : standard deviation of runtime.
    memory_mb        : provisioned memory.
    cold_start_s     : additional latency on a cold start.
    active_power_w   : power draw while executing.
    idle_power_w     : power draw of a warm-but-idle container (per container).
    latency_class    : LatencyClass governing scheduling freedom.
    sla_deadline_s   : end-to-end deadline from arrival to completion.
    """

    function_id: str
    avg_runtime_s: float
    runtime_std_s: float
    memory_mb: int
    cold_start_s: float
    active_power_w: float
    idle_power_w: float
    latency_class: LatencyClass
    sla_deadline_s: float


@dataclass
class Invocation:
    """A single function invocation observed at a point in time."""

    invocation_id: str
    function_id: str
    arrival_time: float                # seconds since simulation epoch
    home_region: str                   # region the request entered from
    realized_runtime_s: float          # sampled per-invocation runtime
    realized_memory_mb: int            # may equal spec.memory_mb


@dataclass
class ScheduleDecision:
    """Output of a scheduler for a single invocation.

    Attributes
    ----------
    region_id  : where the invocation will execute.
    start_time : when execution begins (>= arrival_time).
    use_warm   : whether a warm container is reused; if False a cold start is
                 paid.
    """

    region_id: str
    start_time: float
    use_warm: bool


@dataclass
class ExecutionRecord:
    """Outcome of a scheduled invocation, used to compute metrics."""

    invocation: Invocation
    decision: ScheduleDecision
    end_time: float
    cold_start: bool
    carbon_g: float
    energy_kwh: float
    sla_violated: bool
    latency_s: float
    cost_usd: float
