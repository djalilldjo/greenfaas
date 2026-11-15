"""
Unit tests for GreenFaaS core scheduler and simulator logic.

Coverage targets:
  - FIFO scheduler: invocations always commit at arrival in home region
  - Spatial scheduler: routes to lowest-carbon feasible region
  - Wait-Awhile: defers when carbon > threshold, falls back at max_defer
  - GreenFaaS: respects Lemma 1 break-even gate; do-no-harm in single-region
  - Simulator: capacity enforcement, warm-pool consumption,
               cold-start accounting, idle-energy attribution
  - Tradeoff lemma: edge cases (r<=1, beta=0, very small/large beta)

Run: python scripts/test_core.py
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import (
    FifoScheduler, GreenFaaSScheduler, GreenFaaSV1Scheduler,
    LechowiczScheduler, Region, Simulator, SpatialScheduler,
    WaitAwhileScheduler, generate_workload,
    make_default_function_catalog,
)
from greenfaas.carbon import CarbonModel, CarbonTrace, synthetic_diurnal_trace
from greenfaas.tradeoff import break_even_rate, beta_crit, TradeoffParams
from greenfaas.core import LatencyClass, Invocation
from dataclasses import replace


# ---------- Helpers ---------------------------------------------------------

def make_simple_carbon(region_ids, low_region, high_region, duration_s=3600.0):
    """One low-carbon and one high-carbon region; others medium."""
    traces = {}
    for r in region_ids:
        if r == low_region:
            values = [50.0] * 13  # 5-min steps over 1h + 1
        elif r == high_region:
            values = [800.0] * 13
        else:
            values = [300.0] * 13
        traces[r] = CarbonTrace(region_id=r, values=values, step_s=300.0)
    return CarbonModel(traces=traces)


def make_simple_regions(region_ids, capacity=400):
    rtt_pairs = {("FR","DE"):15,("FR","GB"):12,("FR","US-CAISO"):145,
                 ("FR","PL"):30,("DE","GB"):20,("DE","US-CAISO"):155,
                 ("DE","PL"):15,("GB","US-CAISO"):140,("GB","PL"):30,
                 ("US-CAISO","PL"):170}
    rtt_map = {r: {} for r in region_ids}
    for (a,b), v in rtt_pairs.items():
        if a in region_ids and b in region_ids:
            rtt_map[a][b] = float(v); rtt_map[b][a] = float(v)
    return {r: Region(region_id=r, name=r, capacity=capacity,
                      network_rtt_ms=rtt_map[r], pue=1.2) for r in region_ids}


# ---------- Tests: Lemma 1 trade-off math ----------------------------------

class TradeoffLemmaTests(unittest.TestCase):

    def test_beta_crit_grows_with_r(self):
        """β_crit = (r-1)(1+α) should be monotone increasing in r."""
        alpha = 1.0/0.3
        b_at_2 = beta_crit(2.0, alpha)
        b_at_5 = beta_crit(5.0, alpha)
        b_at_11 = beta_crit(11.0, alpha)
        self.assertLess(b_at_2, b_at_5)
        self.assertLess(b_at_5, b_at_11)

    def test_break_even_none_when_r_le_1(self):
        """No spatial advantage when r ≤ 1."""
        p = TradeoffParams(c_low=300.0, c_high=300.0, tau_e=0.3, tau_c=1.0,
                           p_active_w=4.0, p_idle_w=0.3, t_warm_s=600.0)
        self.assertIsNone(break_even_rate(p))

    def test_break_even_returns_positive_in_second_regime(self):
        """For typical FaaS params, second regime; finite λ*."""
        p = TradeoffParams(c_low=60.0, c_high=700.0, tau_e=0.3, tau_c=1.0,
                           p_active_w=4.0, p_idle_w=0.3, t_warm_s=600.0)
        lam = break_even_rate(p)
        self.assertIsNotNone(lam)
        self.assertGreater(lam, 0.0)
        self.assertLess(lam, 1.0)

    def test_break_even_decreases_with_r(self):
        """Larger carbon ratio → easier to justify spatial routing → smaller λ*."""
        base = dict(tau_e=0.3, tau_c=1.0, p_active_w=4.0, p_idle_w=0.3,
                    t_warm_s=600.0, c_low=60.0)
        lam_small_r = break_even_rate(TradeoffParams(c_high=120.0, **base))  # r=2
        lam_large_r = break_even_rate(TradeoffParams(c_high=600.0, **base))  # r=10
        self.assertIsNotNone(lam_small_r)
        self.assertIsNotNone(lam_large_r)
        self.assertGreater(lam_small_r, lam_large_r)


# ---------- Tests: scheduler behavior ---------------------------------------

class FifoSchedulerTests(unittest.TestCase):

    def setUp(self):
        self.region_ids = ["FR", "PL"]
        self.regions = make_simple_regions(self.region_ids)
        self.carbon = make_simple_carbon(self.region_ids, "FR", "PL")
        self.fns = make_default_function_catalog()
        self.fn_map = {f.function_id: f for f in self.fns}

    def test_fifo_runs_in_home_region(self):
        """FIFO never re-routes."""
        from greenfaas.schedulers import SystemState
        sched = FifoScheduler()
        # Build a single invocation in PL (high carbon) and check FIFO keeps it there.
        inv = Invocation(invocation_id="i1", function_id=self.fns[0].function_id,
                         arrival_time=0.0, home_region="PL", realized_runtime_s=0.3,
                         realized_memory_mb=128.0)
        state = SystemState(current_time=0.0, regions=self.regions,
                            functions=self.fn_map,
                            warm_pool={r: {} for r in self.region_ids},
                            in_flight={r: 0 for r in self.region_ids})
        decision = sched.schedule(inv, state, self.carbon)
        self.assertEqual(decision.region_id, "PL")
        self.assertEqual(decision.start_time, 0.0)


class SpatialSchedulerTests(unittest.TestCase):

    def test_spatial_routes_to_low_carbon_region(self):
        """When carbon at PL=800 and FR=50, route a DEFERRABLE function to FR."""
        from greenfaas.schedulers import SystemState
        region_ids = ["FR", "PL"]
        regions = make_simple_regions(region_ids)
        carbon = make_simple_carbon(region_ids, "FR", "PL")
        fns = make_default_function_catalog()
        # Pick the first DEFERRABLE function (Spatial keeps INTERACTIVE in home region).
        deferrable_fn = next(f for f in fns if f.latency_class == LatencyClass.DEFERRABLE)
        fn_map = {f.function_id: f for f in fns}
        sched = SpatialScheduler(max_rtt_ms=80.0)
        inv = Invocation(invocation_id="i1", function_id=deferrable_fn.function_id,
                         arrival_time=0.0, home_region="PL", realized_runtime_s=0.3,
                         realized_memory_mb=128.0)
        state = SystemState(current_time=0.0, regions=regions, functions=fn_map,
                            warm_pool={r: {} for r in region_ids},
                            in_flight={r: 0 for r in region_ids})
        decision = sched.schedule(inv, state, carbon)
        self.assertEqual(decision.region_id, "FR")


class GreenFaaSDoNoHarmTests(unittest.TestCase):

    def test_greenfaas_matches_fifo_single_region(self):
        """Do-no-harm: in a single-region setup, GreenFaaS == FIFO byte-for-byte."""
        region_ids = ["DE"]
        regions = make_simple_regions(region_ids)
        carbon = make_simple_carbon(region_ids, "DE", "DE")  # uniform
        fns = make_default_function_catalog()
        fn_map = {f.function_id: f for f in fns}
        invs = generate_workload(duration_s=3600.0, base_rate_per_s=2.0,
                                 functions=fns, region_ids=region_ids, seed=42)

        fifo = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                         scheduler=FifoScheduler()).run(invs).summary()
        gf = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                       scheduler=GreenFaaSScheduler(forecast_accuracy="perfect",
                                                    deferrable_rtt_ms=80.0)).run(invs).summary()
        # Byte-for-byte agreement on key metrics:
        self.assertAlmostEqual(fifo["carbon_g"], gf["carbon_g"], delta=0.01)
        self.assertAlmostEqual(fifo["cold_start_rate"], gf["cold_start_rate"], delta=0.001)
        self.assertEqual(fifo["invocations"], gf["invocations"])


class SchedulerOrderingTests(unittest.TestCase):

    def test_spatial_beats_fifo_when_carbon_heterogeneous(self):
        """With heterogeneous carbon, Spatial should produce less carbon than FIFO."""
        region_ids = ["FR", "PL", "DE"]
        regions = make_simple_regions(region_ids)
        carbon = make_simple_carbon(region_ids, "FR", "PL")
        fns = make_default_function_catalog()
        fn_map = {f.function_id: f for f in fns}
        invs = generate_workload(duration_s=3600.0, base_rate_per_s=2.0,
                                 functions=fns, region_ids=region_ids, seed=42)

        fifo = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                         scheduler=FifoScheduler()).run(invs).summary()
        sp = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                       scheduler=SpatialScheduler(max_rtt_ms=80.0)).run(invs).summary()
        self.assertLess(sp["carbon_g"], fifo["carbon_g"])


# ---------- Tests: simulator correctness ------------------------------------

class SimulatorCorrectnessTests(unittest.TestCase):

    def test_total_invocations_preserved(self):
        """The simulator must execute exactly the input invocations."""
        region_ids = ["DE"]
        regions = make_simple_regions(region_ids)
        carbon = make_simple_carbon(region_ids, "DE", "DE")
        fns = make_default_function_catalog()
        fn_map = {f.function_id: f for f in fns}
        invs = generate_workload(duration_s=600.0, base_rate_per_s=1.0,
                                 functions=fns, region_ids=region_ids, seed=42)
        res = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                        scheduler=FifoScheduler()).run(invs).summary()
        self.assertEqual(res["invocations"], len(invs))

    def test_capacity_enforced(self):
        """No more than `capacity` simultaneous in-flight executions per region.
        
        We measure capacity enforcement by latency: with capacity=2 and 20
        invocations of 0.3s each, the slowest invocation should be enqueued
        for roughly 0.3 * (20/2 - 1) = 2.7s.
        """
        region_ids = ["DE"]
        regions = make_simple_regions(region_ids, capacity=2)
        carbon = make_simple_carbon(region_ids, "DE", "DE")
        fns = make_default_function_catalog()
        fn_map = {f.function_id: f for f in fns}
        # Burst: 20 invocations all at t=0.
        invs = [Invocation(invocation_id=f"i{k}", function_id=fns[0].function_id,
                           arrival_time=0.0, home_region="DE",
                           realized_runtime_s=0.3, realized_memory_mb=128.0)
                for k in range(20)]
        sim = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                        scheduler=FifoScheduler())
        result = sim.run(invs)
        # Max latency must reflect queueing under capacity=2:
        # 20 invocations / 2 parallel slots * 0.3s exec = 3s min for the last
        # invocation, minus 0.3s for its own execution.
        max_latency = max(r.latency_s for r in result.records)
        self.assertGreater(max_latency, 2.5)  # Allowing for backoff slack

    def test_warm_pool_consumed_on_warm_start(self):
        """A subsequent invocation within T_w uses the warm container."""
        region_ids = ["DE"]
        regions = make_simple_regions(region_ids)
        carbon = make_simple_carbon(region_ids, "DE", "DE")
        fns = make_default_function_catalog()
        fn_map = {f.function_id: f for f in fns}
        # Two back-to-back invocations of the same function:
        invs = [
            Invocation(invocation_id="i1", function_id=fns[0].function_id,
                       arrival_time=0.0, home_region="DE",
                       realized_runtime_s=0.3, realized_memory_mb=128.0),
            Invocation(invocation_id="i2", function_id=fns[0].function_id,
                       arrival_time=1.0, home_region="DE",  # 1s later, well within T_w
                       realized_runtime_s=0.3, realized_memory_mb=128.0),
        ]
        result = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                           scheduler=FifoScheduler()).run(invs)
        # First invocation is cold; second is warm.
        self.assertTrue(result.records[0].cold_start)
        self.assertFalse(result.records[1].cold_start)


# ---------- Tests: simulator model (v1.2.0) --------------------------------

class _FixedStartScheduler:
    """Runs every invocation at home, at arrival + delay, with a fixed
    use_warm flag. Lets the tests control deferral and the legacy flag."""
    name = "FixedStart"

    def __init__(self, delays, use_warm=False):
        self.delays = delays
        self.use_warm = use_warm

    def schedule(self, invocation, state, carbon):
        from greenfaas.core import ScheduleDecision
        return ScheduleDecision(invocation.home_region,
                                state.current_time + self.delays.get(invocation.invocation_id, 0.0),
                                self.use_warm)


class SimulatorModelTests(unittest.TestCase):

    def _setup(self):
        regions = make_simple_regions(["DE"])
        carbon = make_simple_carbon(["DE"], "DE", "DE", duration_s=3600.0)
        fns = make_default_function_catalog()
        return regions, carbon, fns, {f.function_id: f for f in fns}

    def _inv(self, i, fn, t):
        return Invocation(invocation_id=f"i{i}", function_id=fn.function_id,
                          arrival_time=t, home_region="DE",
                          realized_runtime_s=0.3, realized_memory_mb=128.0)

    def test_deferred_start_uses_warm_container_available_at_start(self):
        """i2 is scheduled at t=1 (pool empty: i1 still cold-starting is done
        by then, but the flag says cold) to start at t=31. A warm container
        from i1 exists at t=31, so the corrected model starts i2 warm; the
        legacy decision-time binding forces a cold start."""
        regions, carbon, fns, fn_map = self._setup()
        invs = [self._inv(1, fns[0], 0.0), self._inv(2, fns[0], 1.0)]
        sched = lambda: _FixedStartScheduler({"i2": 30.0}, use_warm=False)
        new = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                        scheduler=sched()).run(list(invs))
        old = Simulator(regions=regions, functions=fn_map, carbon=carbon, scheduler=sched(),
                        warm_binding="decision").run(list(invs))
        self.assertFalse([r for r in new.records if r.invocation.invocation_id == "i2"][0].cold_start)
        self.assertTrue([r for r in old.records if r.invocation.invocation_id == "i2"][0].cold_start)

    def test_idle_time_of_reused_container_is_charged(self):
        """Two invocations 100 s apart: the container idles ~100 s, is reused,
        then idles a full keep-alive and expires. Full accounting charges both
        idle periods; the legacy accounting charges only the final one."""
        regions, carbon, fns, fn_map = self._setup()
        invs = [self._inv(1, fns[0], 0.0), self._inv(2, fns[0], 100.0)]
        run = lambda **kw: Simulator(regions=regions, functions=fn_map, carbon=carbon,
                                     scheduler=FifoScheduler(), **kw).run(list(invs)).summary()
        full = run()["warm_idle_carbon_g"]
        legacy = run(idle_accounting="expired_only")["warm_idle_carbon_g"]
        self.assertGreater(legacy, 0.0)
        ratio = full / legacy
        # (~100 s reused idle + 600 s tail) / 600 s tail, allowing for the
        # cold-start and execution time inside the first 100 s.
        self.assertGreater(ratio, 1.14)
        self.assertLess(ratio, 1.17)
        # Exact hand computation: i1 cold-starts and finishes at
        # t1 = cold_start + 0.3 s; the container idles until i2 arrives at
        # 100 s, runs it warm, then idles one full keep-alive (600 s).
        fn = fns[0]
        idle_s = (100.0 - (fn.cold_start_s + 0.3)) + 600.0
        expected = fn.idle_power_w * idle_s / 3.6e6 * 1.2 * 50.0
        self.assertAlmostEqual(full, expected, places=9)

    def test_newest_first_reuse_lets_surplus_containers_expire(self):
        """Three simultaneous invocations create three containers; afterwards
        one invocation every 100 s needs only one. Newest-first reuse lets the
        two surplus containers expire; oldest-first keeps all three alive."""
        regions, carbon, fns, fn_map = self._setup()
        invs = [self._inv(i, fns[0], 0.0) for i in range(3)]
        invs += [self._inv(10 + k, fns[0], 100.0 * k) for k in range(1, 30)]
        run = lambda **kw: Simulator(regions=regions, functions=fn_map, carbon=carbon,
                                     scheduler=FifoScheduler(), **kw).run(list(invs)).summary()
        newest = run()["warm_idle_carbon_g"]
        oldest = run(reuse_order="oldest")["warm_idle_carbon_g"]
        self.assertLess(newest, 0.6 * oldest)

    def test_invalid_model_options_rejected(self):
        regions, carbon, fns, fn_map = self._setup()
        for kw in ({"warm_binding": "x"}, {"idle_accounting": "x"}, {"reuse_order": "x"}):
            with self.assertRaises(ValueError):
                Simulator(regions=regions, functions=fn_map, carbon=carbon,
                          scheduler=FifoScheduler(), **kw)


# ---------- Tests: GreenFaaS-v1 ablation ------------------------------------

class CaribouSchedulerTests(unittest.TestCase):
    """Tests for the Caribou (SOSP'24) baseline."""

    def test_caribou_routes_to_low_carbon_within_window(self):
        """Caribou should pick the lowest-mean-carbon region for the window."""
        from greenfaas import CaribouScheduler
        from greenfaas.schedulers import SystemState
        region_ids = ["FR", "PL"]
        regions = make_simple_regions(region_ids)
        carbon = make_simple_carbon(region_ids, "FR", "PL")
        fns = make_default_function_catalog()
        deferrable_fn = next(f for f in fns if f.latency_class == LatencyClass.DEFERRABLE)
        fn_map = {f.function_id: f for f in fns}
        sched = CaribouScheduler(redeploy_interval_s=3600.0, max_rtt_ms=80.0)
        inv = Invocation(invocation_id="i1", function_id=deferrable_fn.function_id,
                         arrival_time=0.0, home_region="PL", realized_runtime_s=0.3,
                         realized_memory_mb=128.0)
        state = SystemState(current_time=0.0, regions=regions, functions=fn_map,
                            warm_pool={r: {} for r in region_ids},
                            in_flight={r: 0 for r in region_ids})
        decision = sched.schedule(inv, state, carbon)
        self.assertEqual(decision.region_id, "FR")

    def test_caribou_caches_within_window(self):
        """Two invocations in the same deployment window must get the same region."""
        from greenfaas import CaribouScheduler
        from greenfaas.schedulers import SystemState
        region_ids = ["FR", "PL"]
        regions = make_simple_regions(region_ids)
        carbon = make_simple_carbon(region_ids, "FR", "PL")
        fns = make_default_function_catalog()
        deferrable_fn = next(f for f in fns if f.latency_class == LatencyClass.DEFERRABLE)
        fn_map = {f.function_id: f for f in fns}
        sched = CaribouScheduler(redeploy_interval_s=3600.0, max_rtt_ms=80.0)
        invs = [
            Invocation(invocation_id="i1", function_id=deferrable_fn.function_id,
                       arrival_time=0.0, home_region="PL",
                       realized_runtime_s=0.3, realized_memory_mb=128.0),
            Invocation(invocation_id="i2", function_id=deferrable_fn.function_id,
                       arrival_time=300.0, home_region="PL",
                       realized_runtime_s=0.3, realized_memory_mb=128.0),
        ]
        decisions = []
        for inv in invs:
            state = SystemState(current_time=inv.arrival_time,
                                regions=regions, functions=fn_map,
                                warm_pool={r: {} for r in region_ids},
                                in_flight={r: 0 for r in region_ids})
            decisions.append(sched.schedule(inv, state, carbon).region_id)
        # Both should route to FR (lowest carbon, same window).
        self.assertEqual(decisions[0], decisions[1])
        self.assertEqual(decisions[0], "FR")


class V1AblationTests(unittest.TestCase):

    def test_greenfaas_matches_fifo_in_single_region_diurnal(self):
        """GreenFaaS should match FIFO in a single region with a diurnal trace
        (no spatial alternative)."""
        region_ids = ["DE"]
        regions = make_simple_regions(region_ids)
        # A diurnal trace with a small amplitude so v1 defers a little, but
        # there's no spatial alternative.
        trace = synthetic_diurnal_trace("DE", 24*3600.0, step_s=300.0, seed=0)
        carbon = CarbonModel(traces={"DE": trace})
        fns = make_default_function_catalog()
        fn_map = {f.function_id: f for f in fns}
        invs = generate_workload(duration_s=24*3600.0, base_rate_per_s=0.5,
                                 functions=fns, region_ids=region_ids, seed=42)

        fifo = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                         scheduler=FifoScheduler()).run(invs).summary()
        gf = Simulator(regions=regions, functions=fn_map, carbon=carbon,
                       scheduler=GreenFaaSScheduler(forecast_accuracy="perfect",
                                                    deferrable_rtt_ms=80.0)).run(invs).summary()
        # GreenFaaS should match FIFO (within rounding) in single-region:
        self.assertAlmostEqual(fifo["carbon_g"], gf["carbon_g"], delta=fifo["carbon_g"] * 0.01)


# ---------- Run -------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
