# 2. Related Work

Carbon-aware scheduling has emerged as a major research direction over the
past four years, and the literature has matured rapidly. We organise prior
work into four threads: (i) carbon-aware scheduling for batch and
long-running workloads, where the dominant approaches assume delay-tolerance
and suspend/resume; (ii) theoretical foundations of online carbon-aware
scheduling, where recent work has established the first competitive-ratio
results; (iii) the small but growing set of carbon-aware schedulers
explicitly targeting serverless or FaaS workloads, with which GreenFaaS most
directly engages; and (iv) FaaS systems research on cold-starts, warm
pools, and characterisation, on which our cost model and the design of the
SLA-tiered policy depend.

## 2.1 Carbon-Aware Scheduling for Batch Workloads

The dominant strategy in the carbon-aware literature is *temporal
shifting*: deferring delay-tolerant work to periods of low grid carbon
intensity. Wiesner et al.'s *Let's Wait Awhile* (Middleware'21)
introduced threshold-based deferral for batch workloads and released the
hourly carbon-intensity dataset (Germany, Great Britain, France,
California, 2020) that has become the de facto reference for the
sub-field; we use this dataset directly in our evaluation (§7.1).
*DTPR* (2023) extended Wait-Awhile with deadline-aware temporal
priorities, and *Wait-and-Scale* (2023) added container-pool resizing on
top of deferral. *Adapting Datacenter Capacity* (Lin and Chien,
e-Energy'23) explored a complementary direction: provisioning data
centre capacity to track grid carbon. All of these works assume
minutes-to-hours job runtimes and explicit suspend/resume, neither of
which is available to a FaaS scheduler.

*CarbonScaler* (Hanafy et al., SIGMETRICS'23) scales the parallelism of
ML training jobs in response to carbon intensity, exploiting the
elasticity of data-parallel batch workloads. *GAIA* (Souza et al.,
e-Energy'23) coordinates spatial and temporal shifting across a cluster
of jobs, and the same group's *Ecovisor* (ASPLOS'23) provides a virtual
energy system abstraction that exposes per-application carbon
intensities as a first-class resource. Google's *Carbon-Intelligent
Compute* (Radovanović et al., IEEE Trans. Power Systems 2023) deploys a
Variable Capacity Curve approach at production scale across Google
data centres. *CarbonFlex* (2025) combines cluster provisioning and
job scheduling for parallel batch and ML workloads. *LACS* (Bostandoost
et al., e-Energy'24) is a learning-augmented resource scaler that
addresses uncertain demand under a competitive analysis framework.
Sukprasert et al. (2023) quantified the joint potential of temporal and
spatial shifting on real cloud workloads, and a recent
spatio-temporal study by Attenni et al. extends this analysis to water
and land-use footprints, including for FaaS-class workloads (where they
report carbon savings of up to 85% via pure spatial routing in a
multi-region setting).

These works share two structural assumptions that GreenFaaS relaxes.
First, the schedulable units are *jobs* with cost separable per-job,
which allows the schedulers to reason about each job's deferral in
isolation. FaaS invocations are not separable in this sense because
their cost is coupled through warm-pool state, which we formalise in
§4.1. Second, the schedulers operate on a timescale (minutes to hours)
where cold-start penalties are negligible. We have shown empirically in
§7 that naively transplanting these techniques to FaaS workloads — as
the Wait-Awhile baseline does — *triples* operational carbon relative
to a carbon-unaware FIFO baseline. The "batch schedulers don't transfer"
claim is therefore not only intuitively obvious from the assumption
mismatch but also empirically severe.

## 2.2 Theoretical Foundations of Online Carbon-Aware Scheduling

A recent line of theoretical work has put carbon-aware online algorithms
on firmer footing. Lechowicz et al.'s *Online Pause and Resume Problem*
(SIGMETRICS'24) studies a one-dimensional model in which a workload can
be paused during high-carbon periods and resumed during low-carbon
periods, paying a fixed switching cost. They derive double-threshold
algorithms with provably optimal competitive ratios for both the cost-
minimisation and the value-maximisation variants. *Online Conversion
with Switching Costs* (Lechowicz et al., SIGMETRICS'24) generalises
this to fractional conversion with switching costs, again with
optimal competitive ratios in both robust and learning-augmented
settings. Bostandoost et al.'s *LACS* (e-Energy'24) and the *Time
Fairness in Online Knapsack Problems* line (ICLR'24) extend the toolkit
in adjacent directions.

These theoretical results apply to a workload model that is in several
respects strictly simpler than ours: a single workload (no multi-tenant
mix), one machine (no spatial routing), and a single switching cost (no
idle-energy accumulation). The FaaS setting we study introduces three
structural features — per-invocation cold-start versus warm-pool
trade-offs, spatial routing across regions with non-stationary carbon
intensities, and tiered SLA constraints — that take us outside the
class of problems for which competitive-ratio bounds are currently
known. We are therefore explicit in §4.2 that GreenFaaS is an empirical
scheduler with a *local* analytical guarantee (Lemma 1's break-even
characterisation) rather than a competitively-optimal one. Extending
Lechowicz et al.'s techniques to handle warm-pool idle energy and SLA
tiering is an open direction we identify in §8.

## 2.3 Carbon-Aware FaaS and Serverless

Three concurrent and recent lines of work target serverless workloads
specifically, and each engages a different facet of the problem.

**GreenCourier** (Chadha et al., WoSC'23). GreenCourier is the closest
prior system in scope: a Kubernetes scheduler plugin that routes
serverless functions across geographically distributed Knative clusters
based on real-time grid carbon intensity (via WattTime and the Carbon-
Aware SDK). Evaluated on Google Kubernetes Engine across Spain, France,
Belgium, and the Netherlands, it reports 9--18% carbon reduction per
function invocation with negligible latency overhead. GreenCourier and
GreenFaaS share the high-level goal of carbon-aware FaaS scheduling but
differ in three significant respects. *First*, GreenCourier is *spatial-
only* — it scores regions by current carbon intensity and routes
functions to the cleanest available region, with no temporal deferral
and no warm-pool reasoning. Our headline contribution beyond
GreenCourier is therefore the joint spatial/temporal/warm-pool policy
and the underlying trade-off analysis. *Second*, GreenCourier has no
analytical model of the warm-pool versus cold-start carbon trade-off;
our Lemma 1 (§4.3) gives a closed-form characterisation that GreenCourier
does not need (it never keeps warm pools across regions) but that
becomes essential as soon as the scheduler reasons about *whether* to
maintain a warm pool. *Third*, GreenCourier's reported savings (9--18%)
sit at the lower end of what our headline results suggest is
achievable; we attribute this to the spatial-only scope rather than to
algorithmic deficiencies in GreenCourier itself.

**EcoLife** (Jiang et al., SC'24). EcoLife targets a different
dimension of the problem: it co-optimises *operational* and *embodied*
carbon by exploiting heterogeneous multi-generation hardware (newer
servers are faster but have higher embodied carbon per unit time;
older servers are slower but already-amortised). It uses a Particle
Swarm Optimisation-based scheduler that decides, per invocation,
which hardware generation to execute on. EcoLife explicitly reasons
about keep-alive (warm-pool) versus cold-start trade-offs, which makes
it the closest precedent for our Lemma 1 — but it does so through a
metaheuristic optimiser without a closed-form characterisation. The
two contributions are largely orthogonal: EcoLife answers "on what
hardware generation should this function execute?", and GreenFaaS
answers "in what region and at what time should this function
execute, and is a warm pool worth maintaining there?". A scheduler
combining the two axes would be a natural follow-up, and we discuss
this in §8.

**CASPER** (Souza et al., IGSC'24, arXiv:2403.14792). CASPER is
adjacent rather than directly competing: it targets *distributed web
services* (e.g., MediaWiki-class applications) under latency SLOs,
using a mixed-integer program to jointly provision servers and load-
balance requests across cloud regions. It addresses spatial routing
and provisioning with SLO constraints but treats requests at the
application level (request rates, not per-invocation arrivals) and
does not engage with cold-start economics. *CASA* (Qi et al., 2024)
applies a related probabilistic routing approach with dynamic
auto-scaling. We position GreenFaaS as the per-invocation, FaaS-native
analogue of CASPER, with the cold-start trade-off model (which has
no analogue in the web-service setting) as a key technical
distinction.

## 2.4 Serverless Cold-Starts and Workload Characterisation

The cost model in §4.1 and the SLA-tiered policy in §5.3 depend on a
substantial body of FaaS systems work. Shahrad et al.'s *Serverless in
the Wild* (USENIX ATC'20) is the canonical characterisation of
production serverless workloads on Azure Functions; it established that
function invocations are dominated by a small number of high-frequency
"hot" functions, that durations follow heavy-tailed distributions, and
that arrival processes are bursty and event-driven rather than smooth.
Our workload generator (§7.1) and the function popularity model (Zipf
with $s = 1.2$) follow this characterisation directly. The follow-up
*Azure Functions Invocation Trace 2021* (Zhang et al., SOSP'21) gives
per-invocation records over two weeks; we use its schema as the basis
for our trace loader and report headline results on schema-faithful
samples (§7.1, §7.2).

The cold-start problem itself has a rich literature. *Catalyzer*
(Du et al., ASPLOS'20) and *Firecracker* (Agache et al., NSDI'20)
attack cold-starts at the system level via micro-VM and snapshot
techniques. *FaaSCache* (Fuerst and Sharma, ASPLOS'21) frames warm-pool
management as a caching problem and derives keep-alive policies from
caching theory. We borrow the warm-pool / keep-alive abstraction
directly from FaaSCache and the Knative documentation, but we add the
carbon dimension: idle energy at intensity $C_r$ in region $r$ is
itself a cost that the scheduler must trade off against cold-start
energy at potentially different $C$. This is the substance of our
Lemma 1.

FaaS-specific simulators include `faas-sim` (edgerun), `vHive`
(vhive-serverless), and `SimFaaS` / `FaaSim` variants. We use
`faas-sim`'s function-level model as the design basis for our discrete-
event simulator. For the carbon co-simulation layer we adopt the
abstractions of `vessim` (Wiesner et al.). The Green Software
Foundation's *Carbon-Aware SDK* provides the unified API to
ElectricityMaps and WattTime that GreenCourier uses; our trace loaders
support the same hourly-CSV format used by the SDK.

## 2.5 Summary of Positioning

GreenFaaS sits at the intersection of three previously-separate strands:
the carbon-aware temporal/spatial shifting literature (§2.1, §2.2), the
FaaS systems literature on warm pools and cold starts (§2.4), and the
small but growing set of FaaS-native carbon-aware schedulers (§2.3).
Our contributions can be located precisely against this literature:

- *vs. batch-oriented carbon-aware schedulers (Wait-Awhile,
  CarbonScaler, GAIA, …)*: we target a workload model whose assumptions
  they violate, and we demonstrate empirically (§7) that those
  schedulers *do harm* when applied to FaaS.

- *vs. theoretical online algorithms for carbon-aware load shifting
  (Lechowicz et al.)*: we work in a richer problem class (warm pools,
  SLA tiers, multi-region) where competitive-ratio bounds are not
  currently available, and offer instead a local analytical guarantee
  (Lemma 1) combined with empirical evaluation.

- *vs. GreenCourier*: we extend spatial-only carbon-aware routing with
  temporal deferral, warm-pool management, and the closed-form
  cold-start trade-off. We also formalise the do-no-harm property
  (§7.3, §7.4, §7.6) which GreenCourier's spatial-only design does not
  need to address but which is essential for FaaS at production scale.

- *vs. EcoLife*: orthogonal axes. EcoLife exploits hardware generation
  heterogeneity; GreenFaaS exploits spatial + temporal grid carbon
  heterogeneity. The two could be composed.

- *vs. CASPER*: we extend the spatial-provisioning-with-SLO framing to
  the per-invocation FaaS setting, where the cold-start economics
  fundamentally change the warm-pool placement decision.

To our knowledge, no prior work has formalised the cold-start carbon
trade-off in closed form, demonstrated the *idle-energy correction*
that governs the temporal axis (§4.3.9), or established a do-no-harm
property across topology, SLA-mix, forecast-accuracy, and carbon-
variability axes. These are the empirical and analytical novelties on
which the rest of the paper builds.
