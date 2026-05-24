# 6. Simulator Implementation

We implemented GreenFaaS-sim, a single-process discrete-event simulator
in Python, alongside the scheduler. The simulator's design follows the
abstractions of `faas-sim` (function-level FaaS simulation) and `vessim`
(carbon co-simulation), but is a clean-room implementation rather than a
fork — written from scratch to give us tight control over the event
ordering, the warm-pool accounting, and the extension points for the
trace loaders. The full implementation, including all baseline
schedulers, is approximately 1,700 lines of substantive Python (excluding
blank lines and comments) with no required dependencies beyond the
standard library (`matplotlib` and `numpy` are used only for figure
generation, and the trace loaders use only `csv` and `datetime`).

## 6.1 Event Model

The simulator maintains a min-heap of timestamped events of four kinds:

- **ARRIVAL**: a new invocation enters the system. The scheduler is
  consulted exactly once at this point; the decision is committed for
  the lifetime of the invocation.
- **START**: the chosen start time of a previously-scheduled
  invocation. Execution begins; energy and carbon are charged from this
  point.
- **COMPLETION**: an invocation finishes execution. The container
  becomes warm-and-idle for up to $T_w$ seconds.
- **WARM_EXPIRE**: a warm container reaches its TTL without being
  reused and is evicted; the accumulated idle energy is finalised.

The simulator processes events in time order. ARRIVAL events generate
START events, which generate COMPLETION events, which generate
WARM_EXPIRE events. The decoupling of ARRIVAL from START is what makes
temporal deferral possible without special-casing in the event loop:
the scheduler returns a `start_time` that may be in the future, and the
simulator simply enqueues the START event at that time. Reusing a warm
container is signalled by the scheduler's `use_warm` flag and is
realised at the START event by decrementing the warm-pool count.

## 6.2 Warm-Pool Accounting

Warm-pool idle energy is the subtlest accounting in the simulator
because containers are warm for non-trivial durations between
invocations, and the carbon cost of that idle time accumulates against
the region's grid intensity.

For each (region, function) pair, the simulator maintains a count
$W_{r,f}(t)$ of warm containers and a queue of pending WARM_EXPIRE
events. A container becomes warm at COMPLETION time with a scheduled
expiry $T_w$ seconds later. If the container is reused before its
expiry, the warm count is decremented and the corresponding
WARM_EXPIRE is matched against the consumption at START time; the
container's lifetime $(t_{\text{end}} - t_{\text{start}})$ is logged.
If the container's expiry fires before reuse, the WARM_EXPIRE event
performs eviction and logs the full $T_w$ lifetime.

At the end of the simulation, the total warm-container lifetime per
(region, function) pair is multiplied by the function's idle power
$P_i$, the region's PUE, and the region's *mean* carbon intensity
$\bar{C}_r$ over the simulation horizon. The use of $\bar{C}_r$ rather
than instantaneous $C_r(t)$ is appropriate because the idle period
spans a non-trivial fraction of the diurnal cycle in expectation. This
is the same mean-intensity convention that the GreenFaaS scheduler
uses in its per-slot scoring (§5.2 line 14).

## 6.3 Extension Points

Three abstractions cleanly separate the algorithm from the data
sources, so that real Azure traces, ElectricityMaps CSVs, or
alternative cost models can be swapped in without changing the
scheduler code.

**`CarbonModel`** (`greenfaas/carbon.py`) provides
`intensity(region, t)` and `forecast(region, t, horizon, accuracy)`.
The default implementation reads from per-region `CarbonTrace` objects
with arbitrary step sizes; real ElectricityMaps CSVs are loaded via
`load_carbon_csv` (§7.1) into the same `CarbonTrace` type. The
scheduler does not know whether the carbon data is synthetic or real.

**Workload generators** produce `List[Invocation]`. The default
generator (`greenfaas/workload.py`) emits a non-homogeneous Poisson
stream with a Zipf function-popularity distribution. The real-trace
loaders (`greenfaas/traces/azure_2019.py`,
`greenfaas/traces/azure_2021.py`) emit the same `List[Invocation]`
type from published Azure schemas. The simulator processes either
identically.

**Schedulers** implement a single method,
`schedule(invocation, state, carbon) -> ScheduleDecision`. The five
schedulers in our evaluation (FIFO, Wait-Awhile, Spatial, GreenFaaS-v1,
GreenFaaS) all conform to this interface and are swappable. Adding a
new scheduler — for example, a port of the Lechowicz et al.
double-threshold algorithm to this setting — requires implementing
this one method.

## 6.4 Validation

The simulator's correctness rests on three orthogonal checks:

1. **Conservation.** The total execution energy reported across all
   invocations equals $\sum_i P_a(f(i)) \cdot \tau(i)$ within
   floating-point precision, and the total warm-idle energy equals
   $\sum_{(r,f)} P_i(f) \cdot \text{lifetime}_{r,f}$. We verified this
   by direct comparison with hand-computed values on small synthetic
   workloads.

2. **Schedule determinism.** Re-running a fixed scheduler on a fixed
   invocation stream produces identical decisions. We verified this
   for all five schedulers in our test suite.

3. **Lemma-implementation agreement.** The closed-form trade-off
   lemma (§4.3) and the per-invocation carbon computed by direct
   simulation agree at 56 grid points spanning $r \in [1.1, 11.7]$ and
   $\lambda \in [10^{-4}, 1]$/s. `scripts/verify_tradeoff.py` runs this
   cross-check on every build of the codebase.

The third check, in particular, gives us confidence that the
scheduler's lemma-driven decisions and the simulator's energy
accounting are mutually consistent — a worry given that the lemma was
derived analytically and the simulator was implemented independently.
