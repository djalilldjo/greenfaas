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
    after which they are evicted.
  * Idle energy (v1.2.0): every second a container spends warm-but-idle is
    charged at the function's idle power, whether the container is later
    reused or expires. This is the W_{r,f}(t) integral of the paper's
    total-carbon equation.
  * Reuse order (v1.2.0): an invocation takes the MOST recently used warm
    container, so containers beyond what current concurrency needs sit unused
    and expire after the TTL. (Taking the oldest container first, as before,
    round-robins the whole pool and keeps every container alive forever once
    the arrival rate exceeds pool size / TTL.)
  * Warm/cold binding (v1.2.0): whether an invocation starts warm is resolved
    when it actually STARTS: it uses a warm container if one is available.
    A scheduler cannot commit a future start to a cold start.

  * Queue-for-reuse and keep-alive (v1.3.0): a decision may carry a queue
    wait (`reuse_wait_s`) and a keep-alive (`keep_warm_s`). A request with a
    queue wait that finds no free warm container but a busy one of the same
    function waits and is handed the first to complete (FIFO), or cold-starts
    when the wait expires. A completing container stays warm for the
    decision's keep-alive (default: `warm_ttl_s`).
  * Idle carbon (v1.3.0): the intensity trace is integrated over each idle
    interval (`idle_intensity="trace"`); `"mean"` restores the v1.2.0
    attribution at the region's mean intensity.

Legacy behaviour (releases up to v1.1.0) is kept for reproducing the results
of the originally submitted manuscript: `idle_accounting="expired_only"`
charges idle energy only for containers that expire unused,
`reuse_order="oldest"` reuses the oldest warm container first, and
`warm_binding="decision"` freezes the warm/cold choice at decision time via
`ScheduleDecision.use_warm`, so a deferred invocation decided while the pool
was empty cold-starts even if a warm container exists when it starts.

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
EVENT_WAIT_TIMEOUT = 4


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
        warm_binding: str = "start",
        idle_accounting: str = "full",
        reuse_order: str = "newest",
        idle_intensity: str = "trace",
    ):
        if idle_intensity not in ("trace", "mean"):
            raise ValueError("idle_intensity must be 'trace' or 'mean'")
        self.idle_intensity = idle_intensity
        if reuse_order not in ("newest", "oldest"):
            raise ValueError("reuse_order must be 'newest' or 'oldest'")
        self.reuse_order = reuse_order
        if warm_binding not in ("start", "decision"):
            raise ValueError("warm_binding must be 'start' or 'decision'")
        if idle_accounting not in ("full", "expired_only"):
            raise ValueError("idle_accounting must be 'full' or 'expired_only'")
        self.warm_binding = warm_binding
        self.idle_accounting = idle_accounting
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
        self._warm: Dict[Tuple[str, str], List[dict]] = {}
        # Invocations queued for a busy container, per (region, function).
        self._waiters: Dict[Tuple[str, str], List[dict]] = {}

    # ------------------------------------------------------------------ #
    # Warm-pool accounting
    # ------------------------------------------------------------------ #
    def _add_warm(self, region: str, function: str, start: float, until: float) -> dict:
        """Add a warm-idle container; returns its record."""
        c = {"start": start, "expiry": until, "alive": True}
        self.state.warm_pool[region][function] = self.state.warm_pool[region].get(function, 0) + 1
        self._warm.setdefault((region, function), []).append(c)
        return c

    def _consume_warm(self, region: str, function: str) -> float:
        """Take one warm container; return how long it had been idle (s)."""
        idle_s = 0.0
        if self.state.warm_pool[region].get(function, 0) > 0:
            self.state.warm_pool[region][function] -= 1
            pool = self._warm.get((region, function), [])
            if pool:
                # The pool is ordered by the time each container went idle.
                c = pool.pop() if self.reuse_order == "newest" else pool.pop(0)
                c["alive"] = False
                idle_s = max(0.0, self.state.current_time - c["start"])
        return idle_s

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def run(self, invocations: Iterable[Invocation]) -> SimulationResult:
        records: List[ExecutionRecord] = []
        # Idle-energy segments per (region, function): we accumulate at the
        # end based on warm container lifetimes.
        warm_lifetimes_s: Dict[Tuple[str, str], float] = {}
        # Integral of carbon intensity over those idle intervals (g/kWh * s).
        idle_ci_s: Dict[Tuple[str, str], float] = {}

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

                # Resolve cold/warm at the ACTUAL start time (see module
                # docstring for the legacy decision-time binding).
                warm_available = self.state.warm_pool[region.region_id].get(fn.function_id, 0) > 0
                key = (region.region_id, fn.function_id)
                if (not warm_available and not ev.payload.get("handoff")
                        and not ev.payload.get("timed_out")
                        and decision.reuse_wait_s > 0.0
                        and self.state.busy.get(key, 0) > 0):
                    # Queue for a busy container of this function rather
                    # than cold-starting a new one.
                    w = {"inv": inv, "decision": decision, "active": True}
                    self._waiters.setdefault(key, []).append(w)
                    self.state.queued[key] = self.state.queued.get(key, 0) + 1
                    heapq.heappush(events, _Event(
                        self.state.current_time + decision.reuse_wait_s,
                        EVENT_WAIT_TIMEOUT, {"waiter": w, "key": key},
                    ))
                    continue
                if ev.payload.get("handoff"):
                    # Handed a container straight from a completing
                    # invocation: warm, with no idle time in between.
                    cold = False
                elif self.warm_binding == "start":
                    cold = not warm_available
                else:  # legacy: choice frozen at decision time
                    cold = not (decision.use_warm and warm_available)
                if not cold and not ev.payload.get("handoff"):
                    idle_s = self._consume_warm(region.region_id, fn.function_id)
                    if self.idle_accounting == "full":
                        warm_lifetimes_s[key] = warm_lifetimes_s.get(key, 0.0) + idle_s
                        now_ = self.state.current_time
                        idle_ci_s[key] = idle_ci_s.get(key, 0.0) + self.carbon.traces[
                            region.region_id].integral(now_ - idle_s, now_)

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
                self.state.busy[key] = self.state.busy.get(key, 0) + 1
                heapq.heappush(events, _Event(
                    completion_time, EVENT_COMPLETION,
                    {"region": region.region_id, "function": fn.function_id,
                     "keep_warm_s": decision.keep_warm_s},
                ))

            elif ev.kind == EVENT_COMPLETION:
                region_id = ev.payload["region"]
                function_id = ev.payload["function"]
                self.state.in_flight[region_id] = max(0, self.state.in_flight.get(region_id, 0) - 1)
                key = (region_id, function_id)
                self.state.busy[key] = max(0, self.state.busy.get(key, 0) - 1)
                waiters = self._waiters.get(key)
                if waiters:
                    # Hand the container to the longest-waiting invocation.
                    w = waiters.pop(0)
                    w["active"] = False
                    self.state.queued[key] -= 1
                    heapq.heappush(events, _Event(
                        self.state.current_time, EVENT_START,
                        {"inv": w["inv"], "decision": w["decision"], "handoff": True},
                    ))
                    continue
                # Container becomes warm-and-idle for its keep-alive time
                # (the platform TTL unless the scheduler set one).
                keep = ev.payload.get("keep_warm_s")
                ttl = self.warm_ttl_s if keep is None else max(0.0, keep)
                if ttl <= 0.0:
                    continue                      # released immediately
                now_ = self.state.current_time
                c = self._add_warm(region_id, function_id, now_, now_ + ttl)
                heapq.heappush(events, _Event(
                    now_ + ttl, EVENT_WARM_EXPIRE,
                    {"region": region_id, "function": function_id, "container": c},
                ))

            elif ev.kind == EVENT_WAIT_TIMEOUT:
                w = ev.payload["waiter"]
                if w["active"]:
                    key = ev.payload["key"]
                    w["active"] = False
                    self._waiters[key].remove(w)
                    self.state.queued[key] -= 1
                    heapq.heappush(events, _Event(
                        self.state.current_time, EVENT_START,
                        {"inv": w["inv"], "decision": w["decision"], "timed_out": True},
                    ))

            elif ev.kind == EVENT_WARM_EXPIRE:
                region_id = ev.payload["region"]
                function_id = ev.payload["function"]
                c = ev.payload["container"]
                # If this warm container is still present (not reused), evict it.
                if c["alive"]:
                    c["alive"] = False
                    self._warm[(region_id, function_id)].remove(c)
                    self.state.warm_pool[region_id][function_id] = max(
                        0, self.state.warm_pool[region_id][function_id] - 1
                    )
                    duration = ev.time - c["start"]
                    warm_lifetimes_s[(region_id, function_id)] = (
                        warm_lifetimes_s.get((region_id, function_id), 0.0) + duration
                    )
                    idle_ci_s[(region_id, function_id)] = (
                        idle_ci_s.get((region_id, function_id), 0.0)
                        + self.carbon.traces[region_id].integral(c["start"], ev.time)
                    )

        # Warm pool idle energy and carbon.
        warm_idle_kwh = 0.0
        warm_idle_carbon = 0.0
        for (region_id, function_id), total_s in warm_lifetimes_s.items():
            fn = self.functions[function_id]
            region = self.regions[region_id]
            kwh = fn.idle_power_w * total_s / 3600.0 / 1000.0 * region.pue
            warm_idle_kwh += kwh
            if self.idle_intensity == "trace":
                # Exact: intensity integrated over each idle interval.
                warm_idle_carbon += (fn.idle_power_w / 3600.0 / 1000.0 * region.pue
                                     * idle_ci_s.get((region_id, function_id), 0.0))
            else:
                # v1.2.0: region mean intensity over the simulated span.
                trace = self.carbon.traces[region_id]
                mean_ci = sum(trace.values) / len(trace.values)
                warm_idle_carbon += kwh * mean_ci

        return SimulationResult(
            scheduler_name=self.scheduler.name,
            records=records,
            warm_pool_idle_energy_kwh=warm_idle_kwh,
            warm_pool_idle_carbon_g=warm_idle_carbon,
        )
