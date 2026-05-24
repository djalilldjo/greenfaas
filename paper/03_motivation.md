# 3. Motivation

We motivate carbon-aware FaaS scheduling with a joint characterisation of
the two data sources that drive our design: a representative FaaS
workload, and the grid carbon-intensity signal that determines the
carbon footprint of executing that workload.

## 3.1 Joint Characterisation

Figure 1 (`figures/motivation_carbon_vs_invocations.png`) overlays a
48-hour grid carbon-intensity trace for Germany — generated to match the
calibration of the ElectricityMaps 2020 data we use in §7 — with the
per-minute invocation rate of a representative `webhook_handler`
function, drawn from a workload generator calibrated to the Shahrad et
al. (USENIX ATC'20) Azure characterisation. Shaded bands mark the
lowest-quartile (green) and highest-quartile (red) carbon windows over
the 48-hour horizon.

Three observations emerge.

**Observation 1: FaaS arrival rates are decoupled from grid carbon
intensity.** The webhook function's invocation rate follows a
business-hours diurnal pattern, peaking in the early afternoon and
troughing overnight. Grid carbon intensity in Germany, by contrast,
follows the inverse pattern: solar and wind generation peak around
midday, depressing the marginal carbon intensity, while night-time
demand is served by base-load fossil generation. The two signals are
phase-shifted by roughly 8--12 hours, with the consequence that on this
representative day, 89% of webhook invocations land *outside* the
cleanest carbon quartile and 11% land directly in the highest-carbon
quartile. The decoupling is the structural reason carbon-aware
scheduling can help: a substantial fraction of work arrives during
periods when greener alternatives exist nearby in space or time.

**Observation 2: The decoupling is robust across function classes.**
Although Figure 1 plots a single representative function for legibility,
the same pattern holds in aggregate. Across the 60-function catalog
generated for our evaluation, the population-weighted invocation rate
correlates only weakly with the local carbon intensity (Pearson $r$ in
the range $-0.2$ to $+0.1$ across regions), confirming that arrival
patterns track user activity rather than grid economics. This is not
surprising — FaaS workloads are driven by external events (user
requests, message-queue depths, scheduled triggers) that have no
relationship to the regional generation mix — but it bears stating
because it underwrites the assumption that shifting opportunities
exist *for typical workloads*, not only for carefully selected ones.

**Observation 3: The amplitude of the carbon swing is comparable to the
amplitude of the arrival swing.** Carbon intensity in Germany swings
from roughly 200 to 500 g CO$_2$eq/kWh over the 24-hour cycle — a
ratio of 2.5×. The webhook invocation rate swings from roughly 15 to
80 invocations per minute — a ratio of 5×. The two signals have
similar dynamic range, which means a scheduler that can shift even a
modest fraction of invocations across the diurnal cycle has the
potential to capture meaningful savings. We quantify this potential
rigorously in §7.

## 3.2 What This Implies for Scheduler Design

The characterisation directly motivates the three design choices in
§5. First, the SLA-tiered policy: the existence of arrivals
distributed across the carbon cycle is only useful to a scheduler that
distinguishes between invocations that must execute immediately
(interactive) and those that can wait (deferrable, background). Without
this distinction, the scheduler is forced to treat the entire workload
as if it were the most demanding tier, eliminating the shifting
opportunity. Second, the use of *both* spatial and temporal axes: a
purely temporal scheduler can only exploit the diurnal swing within one
region, while a purely spatial scheduler ignores the substantial
within-region opportunity Figure 1 reveals. Third, the explicit
carbon-aware warm-pool reasoning of §4.3: at the timescale of FaaS
invocations (seconds), the idle-energy cost of keeping containers warm
is a first-class concern that batch-oriented schedulers can ignore but
FaaS schedulers cannot.

The motivation, in short, is *not* "carbon-aware scheduling helps FaaS"
in some generic sense — that has been shown empirically by GreenCourier
and EcoLife. The motivation is that the *specific structure* of FaaS
workloads (short, bursty, latency-tiered) combined with the *specific
structure* of grid carbon traces (diurnal, decoupled from user
activity, multi-region heterogeneous) creates a joint optimisation
problem that no prior scheduler has addressed in its full generality.
The rest of the paper formalises and solves that problem.
