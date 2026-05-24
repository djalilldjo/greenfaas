# 1. Introduction

Data centers consume an increasing share of global electricity. Recent estimates
place global data center demand at roughly 1.5% of worldwide consumption, with
projections of substantial growth driven by the rapid expansion of artificial
intelligence workloads. In response, hyperscale operators including Google,
Microsoft, and Amazon have made public commitments to carbon-neutral or net-zero
operation within the decade. These pledges have motivated a substantial body of
research on *carbon-aware computing*: a class of techniques that exploit spatial
and temporal variation in electrical grid carbon intensity to shift computation
toward cleaner energy.

The dominant strategy in the carbon-aware literature is *temporal shifting*,
deferring delay-tolerant work to periods of low carbon intensity, typically
when wind, solar, or hydroelectric generation is high relative to demand. A
complementary strategy, *spatial shifting*, routes work toward geographic
regions with cleaner grids at execution time. Both strategies have been shown
to deliver operational-carbon reductions of 20–45% for batch processing,
machine learning training, and other long-running workloads. Recent systems
extend these ideas to scale-elastic jobs, demand-response settings, and
operation under uncertain forecasts.

A critical assumption underlies essentially this entire body of work: that the
target workload is *batch* in character. The canonical scheduled job is minutes
to hours in duration, delay-tolerant on the order of hours, amenable to clean
suspend-and-resume, and accompanied by enough up-front information that the
scheduler can reason globally over a set of pending jobs. These assumptions
hold for ML training, scientific computing, and many enterprise batch
pipelines, and they have grounded the success of systems such as Let's Wait
Awhile, CarbonScaler, GAIA, and Google's Carbon-Intelligent Compute.

These assumptions, however, are violated profoundly by *serverless* or
*Function-as-a-Service* (FaaS) workloads, which now power a substantial
fraction of cloud-native applications. FaaS function invocations are typically
measured in tens of milliseconds to a few seconds rather than minutes; they
are often user-facing, with sub-second latency objectives; they cannot be
suspended and resumed without paying the full cost of a *cold start*, a
process during which container infrastructure, runtime, and application code
must be reloaded; their arrivals are bursty and event-driven rather than
centrally submittable; and per-invocation behavior is largely unpredictable
until execution. The granularity of scheduling decisions — per invocation
rather than per job — and the timescales involved mean that classical
carbon-aware techniques cannot simply be re-parameterized for FaaS. The
shifting horizon collapses, the suspend/resume primitive is unavailable, and
the visibility into future work is dramatically reduced.

This mismatch is consequential. FaaS represents one of the fastest-growing
categories of cloud compute, with Azure Functions, AWS Lambda, Google Cloud
Functions, and open-source platforms such as Knative and OpenFaaS underpinning
a broad range of latency-sensitive applications. Two recent works — GreenCourier
(WoSC'23) and EcoLife (SC'24) — have begun to address the gap: GreenCourier
routes Knative functions to low-carbon regions, and EcoLife co-optimises
operational and embodied carbon by exploiting heterogeneous hardware
generations. Neither, however, formalises the joint spatial/temporal/
warm-pool decision problem that FaaS schedulers actually face, and the
fundamental cold-start versus idle-energy trade-off — the focus of this
paper — has not previously been characterised in closed form.

We argue that carbon-aware scheduling for FaaS is both feasible and distinct
enough from its batch counterpart to warrant first-class treatment. Three
observations motivate our approach. First, FaaS workloads are heterogeneous in
their latency tolerance: a customer-facing API request demands sub-second
response, but many event-driven functions — log processing, queue draining,
scheduled maintenance, asynchronous notifications — tolerate seconds to
minutes of deferral without observable user impact. Second, FaaS platforms
already perform fine-grained placement and routing decisions for
load-balancing and cold-start mitigation; carbon-aware policies can be layered
onto this existing decision machinery rather than added at the application
level. Third, warm-pool management — how many idle containers to keep alive
in each region — is itself a carbon decision, because idle containers consume
non-trivial power and the choice of where to keep them warm interacts directly
with the carbon intensity of the host grid.

In this work, we present **GreenFaaS**, a carbon-aware scheduling
framework for serverless workloads that unifies spatial routing,
temporal deferral, and warm-pool placement under a single principled
policy. Relative to GreenCourier — which addresses only the spatial
axis — we add temporal deferral and warm-pool reasoning. Relative to
EcoLife — which addresses the orthogonal axis of hardware-generation
heterogeneity — we work along the spatial and temporal carbon axes.
GreenFaaS combines temporal deferral for asynchronous and event-driven
invocations, spatial routing for latency-tolerant classes, and
carbon-aware warm-pool management, all under an SLA-tiered policy that
distinguishes interactive, deferrable, and background functions. A key
technical contribution is the explicit modeling of the *cold-start
carbon trade-off*: keeping containers warm in a low-carbon region can,
in some regimes, cost more carbon (through idle power) than
cold-starting in a higher-carbon region. We derive analytical
break-even points for this trade-off and incorporate them directly
into the scheduler.

We evaluate GreenFaaS in **GreenFaaS-sim**, a discrete-event simulator
whose design follows the abstractions of `faas-sim` (function-level FaaS
simulation) and `vessim` (carbon co-simulation), driven by the Azure
Functions 2019 and 2021 traces and grid carbon traces from
Let's-Wait-Awhile / ElectricityMaps. We compare against four
carbon-aware baselines drawn from the recent literature, evaluating
along five axes: workload intensity, number of available regions, SLA
class mix, carbon-intensity variability, and forecast accuracy.

Our key findings are threefold. First, the canonical Wait-Awhile temporal
scheduler *triples* operational carbon under FaaS workloads relative to a
carbon-unaware FIFO baseline, an empirically sharp demonstration that
batch-oriented carbon-aware techniques do not transfer to FaaS. Second,
GreenFaaS reduces operational carbon by 76--79% across topologies
containing a low-carbon refuge (e.g. France, Sweden) — matching pure
spatial routing to within one percentage point — and outperforms spatial
routing by 3.5 percentage points in coal-belt topologies where no
low-carbon refuge exists. Third, and we believe most consequentially,
GreenFaaS preserves a *do-no-harm* property: in single-region scenarios
and in flat-carbon regimes where shifting offers no real opportunity,
GreenFaaS correctly declines to act and matches FIFO byte-for-byte,
while a heuristic ablation (lacking the cold-start trade-off correction)
loses 37--102% to FIFO in the same scenarios. This robustness across
regimes — rather than dominance in any single regime — is the central
practical claim of the paper.

This paper makes the following contributions:

1. **Problem formalization.** A formal model of carbon-aware FaaS
   scheduling as an online optimization problem with capacity, SLA, and
   warm-pool constraints, and an honest discussion of why classical
   competitive-ratio bounds do not apply (Section 4).

2. **The cold-start carbon trade-off lemma.** A closed-form
   characterisation of warm-pool versus cold-start carbon as a function
   of the function's arrival rate, run-time and cold-start durations,
   active and idle power, warm-pool TTL, and the carbon-intensity ratio
   between regions (Section 4.3). The same dimensionless idle-cost
   ratio governs the analogous temporal-shift decision via an
   idle-energy correction (Section 4.3.9).

3. **The GreenFaaS scheduler.** A hybrid online algorithm combining
   temporal deferral, spatial routing, and lemma-driven warm-pool
   management under an SLA-tiered policy, with $O(R \cdot N)$
   per-invocation cost (Section 5).

4. **An open-source simulator and reproducibility artefact.**
   A discrete-event simulator with trace loaders for Azure Functions
   2019, Azure Functions 2021, and ElectricityMaps carbon traces
   matching their published schemas exactly (Section 6).

5. **An empirical evaluation** against four carbon-aware baselines
   (FIFO, Wait-Awhile, Spatial routing, and a heuristic GreenFaaS-v1
   ablation) on the published Azure Functions 2019 and 2021 schemas
   and a five-axis sensitivity sweep
   establishing the do-no-harm property across topology, SLA-class mix,
   forecast accuracy, carbon variability, and workload intensity
   (Section 7).

The remainder of this paper is organized as follows. Section 2 surveys related
work. Section 3 motivates the problem with a joint characterization of FaaS
and carbon traces. Section 4 formalizes the problem. Section 5 presents the
GreenFaaS algorithm. Section 6 describes the simulator. Section 7 reports
experimental results. Section 8 discusses limitations and future work, and
Section 9 concludes.
