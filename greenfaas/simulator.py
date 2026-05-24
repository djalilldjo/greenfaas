"""
greenfaas.simulator
===================

Discrete-event simulator that consumes a stream of invocations, asks a
scheduler for a decision per invocation, advances simulated time, and tracks
warm pools, in-flight counts, and per-invocation metrics.

Design choices:
  * Event queue is ordered by event time (heapq).
  * Two event types: ARRIVAL (scheduler decides; emits a START event in the
    future) and COMPLETION (frees a slot, warms the container for a TTL).
  * Warm-pool TTL: containers stay warm for `warm_ttl_s` after their last use,
    after which they are evicted and their idle energy accounted for.
  * Carbon for a warm container's idle period is attributed to the region
    where it sat.

The simulator is single-region-agnostic; it iterates over all configured
regions when costing warm-pool idle energy.
"""
from __future__ import annotations

import heapq
import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from .carbon import CarbonModel
from .core import (
    ExecutionRecord,
    FunctionSpec,
    Invocation,
    LatencyClass,
    Region,
    ScheduleDecision,
)
from .schedulers import Scheduler, SystemState


EVENT_ARRIVAL = 0
EVENT_START = 1
EVENT_COMPLETION = 2
EVENT_WARM_EXPIRE = 3


@dataclass(order=True)
class _Event:
    time: float
    kind: int = field(compare=False)
    payload: dict = field(compare=False)


@dataclass
class SimulationResult:
    scheduler_name: str
    records: List[ExecutionRecord]
    warm_pool_idle_energy_kwh: float
    warm_pool_idle_carbon_g: float

    # -- Convenience accessors used in reporting -------------------------- #
    def total_invocations(self) -> int:
        return len(self.records)

    def total_carbon_g(self) -> float:
        return sum(r.carbon_g for r in self.records) + self.warm_pool_idle_carbon_g

    def total_energy_kwh(self) -> float:
        return sum(r.energy_kwh for r in self.records) + self.warm_pool_idle_energy_kwh

    def sla_violation_rate(self) -> float:
        if not self.records:
            return 0.0
        return sum(1 for r in self.records if r.sla_violated) / len(self.records)

    def cold_start_rate(self) -> float:
        if not self.records:
            return 0.0
        return sum(1 for r in self.records if r.cold_start) / len(self.records)

    def latency_percentiles(self) -> Tuple[float, float, float]:
        if not self.records:
            return (0.0, 0.0, 0.0)
        lats = sorted(r.latency_s for r in self.records)
        n = len(lats)
        def pct(p):
            k = max(0, min(n - 1, int(p * (n - 1))))
            return lats[k]
        return pct(0.50), pct(0.95), pct(0.99)

    def cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def summary(self) -> Dict[str, float]:
        p50, p95, p99 = self.latency_percentiles()
        return {
            "invocations": float(self.total_invocations()),
            "carbon_g": self.total_carbon_g(),
            "energy_kwh": self.total_energy_kwh(),
            "sla_violation_rate": self.sla_violation_rate(),
            "cold_start_rate": self.cold_start_rate(),
            "p50_latency_ms": p50 * 1000.0,
            "p95_latency_ms": p95 * 1000.0,
            "p99_latency_ms": p99 * 1000.0,
            "warm_idle_carbon_g": self.warm_pool_idle_carbon_g,
            "cost_usd": self.cost_usd(),
        }


class Simulator:
    """Single-pass discrete-event simulator."""

    def __init__(
        self,
        regions: Dict[str, Region],
        functions: Dict[str, FunctionSpec],
        carbon: CarbonModel,
        scheduler: Scheduler,
        warm_ttl_s: float = 600.0,
    ):
        self.regions = regions
        self.functions = functions
        self.carbon = carbon
        self.scheduler = scheduler
        self.warm_ttl_s = warm_ttl_s

        self.state = SystemState(
            current_time=0.0,
            regions=regions,
            functions=functions,
            warm_pool={r: {f: 0 for f in functions} for r in regions},
            in_flight={r: 0 for r in regions},
        )

        # Pending warm expirations per (region, function): list of expiry times.
        self._warm_expires: Dict[Tuple[str, str], List[float]] = {}

    # ------------------------------------------------------------------ #
    # Warm-pool accounting
    # ------------------------------------------------------------------ #
    def _add_warm(self, region: str, function: str, until: float):
        self.state.warm_pool[region][function] = self.state.warm_pool[region].get(function, 0) + 1
        self._warm_expires.setdefault((region, function), []).append(until)

    def _consume_warm(self, region: str, function: str):
        if self.state.warm_pool[region].get(function, 0) > 0:
            self.state.warm_pool[region][function] -= 1
            expiries = self._warm_expires.get((region, function), [])
            if expiries:
                expiries.pop(0)

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def run(self, invocations: Iterable[Invocation]) -> SimulationResult:
        records: List[ExecutionRecord] = []
        # Idle-energy segments per (region, function): we accumulate at the
        # end based on warm container lifetimes.
        warm_lifetimes_s: Dict[Tuple[str, str], float] = {}

        events: List[_Event] = []
        for inv in invocations:
            heapq.heappush(events, _Event(inv.arrival_time, EVENT_ARRIVAL, {"inv": inv}))

        while events:
            ev = heapq.heappop(events)
            self.state.current_time = ev.time

            if ev.kind == EVENT_ARRIVAL:
                inv = ev.payload["inv"]
                fn = self.functions[inv.function_id]
                decision = self.scheduler.schedule(inv, self.state, self.carbon)
                # Enforce capacity at the chosen start time by deferring slightly
                # if utilisation would exceed 1.0. We accept the simple model.
                heapq.heappush(events, _Event(
                    decision.start_time, EVENT_START,
                    {"inv": inv, "decision": decision},
                ))

            elif ev.kind == EVENT_START:
                inv = ev.payload["inv"]
                decision: ScheduleDecision = ev.payload["decision"]
                fn = self.functions[inv.function_id]
                region = self.regions[decision.region_id]

                # Capacity enforcement: if region utilisation is at or above
                # capacity at this start time, defer this start by a small
                # backoff. The scheduler chose this region/time based on
                # the state at decision time; physical resources may not
                # be available immediately, so we queue. A 50ms backoff is
                # well below FaaS-relevant timescales and avoids busy-spinning
                # the event loop.
                in_flight = self.state.in_flight.get(region.region_id, 0)
                if in_flight >= region.capacity:
                    heapq.heappush(events, _Event(
                        self.state.current_time + 0.05, EVENT_START,
                        {"inv": inv, "decision": decision},
                    ))
                    continue

                # Resolve cold/warm at the ACTUAL start time, not at the
                # decision time. If the scheduler chose `use_warm=True` but
                # no warm container is available right now (because the warm
                # container expired during a capacity backoff, for instance),
                # we fall back to a cold start.
                warm_available = self.state.warm_pool[region.region_id].get(fn.function_id, 0) > 0
                cold = not (decision.use_warm and warm_available)
                if not cold:
                    self._consume_warm(region.region_id, fn.function_id)

                # Compute energy & carbon for the execution + cold start.
                runtime = inv.realized_runtime_s
                ci = self.carbon.intensity(region.region_id, self.state.current_time)
                exec_kwh = fn.active_power_w * runtime / 3600.0 / 1000.0 * region.pue
                cs_kwh = (fn.active_power_w * fn.cold_start_s / 3600.0 / 1000.0 * region.pue) if cold else 0.0
                total_kwh = exec_kwh + cs_kwh
                carbon_g = total_kwh * ci

                added_net_latency = self.regions[inv.home_region].rtt_to(region) / 1000.0
                completion_time = self.state.current_time + (fn.cold_start_s if cold else 0.0) + runtime
                latency = completion_time - inv.arrival_time + added_net_latency
                sla_violated = latency > fn.sla_deadline_s

                cost = (fn.memory_mb / 1024.0) * runtime * region.price_per_gb_s

                records.append(ExecutionRecord(
                    invocation=inv,
                    decision=decision,
                    end_time=completion_time,
                    cold_start=cold,
                    carbon_g=carbon_g,
                    energy_kwh=total_kwh,
                    sla_violated=sla_violated,
                    latency_s=latency,
                    cost_usd=cost,
                ))

                self.state.in_flight[region.region_id] = self.state.in_flight.get(region.region_id, 0) + 1
                heapq.heappush(events, _Event(
                    completion_time, EVENT_COMPLETION,
                    {"region": region.region_id, "function": fn.function_id},
                ))

            elif ev.kind == EVENT_COMPLETION:
                region_id = ev.payload["region"]
                function_id = ev.payload["function"]
                self.state.in_flight[region_id] = max(0, self.state.in_flight.get(region_id, 0) - 1)
                # Container becomes warm-and-idle for warm_ttl_s.
                expire = self.state.current_time + self.warm_ttl_s
                self._add_warm(region_id, function_id, expire)
                heapq.heappush(events, _Event(
                    expire, EVENT_WARM_EXPIRE,
                    {"region": region_id, "function": function_id, "start": self.state.current_time},
                ))

            elif ev.kind == EVENT_WARM_EXPIRE:
                region_id = ev.payload["region"]
                function_id = ev.payload["function"]
                start = ev.payload["start"]
                # If this warm container was still present (not reused), evict it.
                expiries = self._warm_expires.get((region_id, function_id), [])
                if expiries and abs(expiries[0] - ev.time) < 1e-9:
                    expiries.pop(0)
                    self.state.warm_pool[region_id][function_id] = max(
                        0, self.state.warm_pool[region_id][function_id] - 1
                    )
                    duration = ev.time - start
                    warm_lifetimes_s[(region_id, function_id)] = (
                        warm_lifetimes_s.get((region_id, function_id), 0.0) + duration
                    )

        # Warm pool idle energy and carbon.
        warm_idle_kwh = 0.0
        warm_idle_carbon = 0.0
        for (region_id, function_id), total_s in warm_lifetimes_s.items():
            fn = self.functions[function_id]
            region = self.regions[region_id]
            kwh = fn.idle_power_w * total_s / 3600.0 / 1000.0 * region.pue
            warm_idle_kwh += kwh
            # Attribute carbon at the average intensity over the simulated span.
            trace = self.carbon.traces[region_id]
            mean_ci = sum(trace.values) / len(trace.values)
            warm_idle_carbon += kwh * mean_ci

        return SimulationResult(
            scheduler_name=self.scheduler.name,
            records=records,
            warm_pool_idle_energy_kwh=warm_idle_kwh,
            warm_pool_idle_carbon_g=warm_idle_carbon,
        )
