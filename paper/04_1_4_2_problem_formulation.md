# 4. Problem Formulation

This section formalises the carbon-aware FaaS scheduling problem. §4.1 sets
up the entities, the decision variables, and the constraints. §4.2 frames
the optimisation as an online problem and discusses why it admits neither
a tractable offline optimum nor a competitive-ratio bound — motivating the
empirical evaluation strategy in §7. §4.3 (the cold-start carbon trade-off
lemma) and §4.3.9 (the temporal idle-energy correction) are the analytical
substance that the GreenFaaS algorithm in §5 builds on.

## 4.1 Problem Statement

### Entities

**Regions.** A set $\mathcal{R} = \{r_1, \ldots, r_R\}$ of geographic
regions. Each region $r$ has:

- a capacity $K_r \in \mathbb{N}$, the maximum number of concurrently
  executing invocations;
- a time-varying grid carbon intensity $C_r: \mathbb{R}_{\ge 0} \to
  \mathbb{R}_{>0}$ in g CO$_2$eq / kWh;
- a Power Usage Effectiveness $\mathrm{PUE}_r \ge 1$;
- network round-trip latencies $\rho(r, r') \ge 0$ in seconds to every
  other region $r' \in \mathcal{R}$, with $\rho(r, r) = 0$.

**Functions.** A set $\mathcal{F}$ of deployed functions. Each function
$f \in \mathcal{F}$ is characterised by:

- expected execution time $\tau_e(f)$ and per-invocation variance;
- cold-start duration $\tau_c(f)$;
- active power draw $P_a(f)$ and idle (warm-but-not-running) power draw
  $P_i(f)$, both in watts;
- memory footprint $m(f)$, used only for cost accounting;
- a latency class $\ell(f) \in \{\textsc{Interactive},
  \textsc{Deferrable}, \textsc{Background}\}$;
- an end-to-end SLA deadline $D(f) \ge \tau_e(f) + \tau_c(f)$.

The latency class determines the scheduler's degree of freedom: an
\textsc{Interactive} invocation must execute immediately in its home region,
a \textsc{Deferrable} one may be deferred up to a class-dependent horizon
and routed within a tight RTT budget, and a \textsc{Background} invocation
may use its full deadline and any region. Section 5.3 makes this precise.

**Invocations.** Function invocations arrive as a stream
$\mathcal{I} = \langle i_1, i_2, \ldots \rangle$ ordered by arrival time.
Each invocation $i$ specifies:

- a function identifier $f(i) \in \mathcal{F}$;
- an arrival time $a(i) \in \mathbb{R}_{\ge 0}$;
- a home region $h(i) \in \mathcal{R}$ — the region in which the
  user-facing request entered the platform;
- a realised runtime $\tau(i)$ drawn from $f(i)$'s execution-time
  distribution.

Crucially, $\tau(i)$ is *not* known to the scheduler at the time the
scheduling decision is made; only the function's expected runtime
$\tau_e(f(i))$ is. The same applies to future arrivals: at time $a(i)$
the scheduler sees $i$ but knows nothing about $i_{k}$ for any $k$ with
$a(i_k) > a(i)$ beyond what an arrival-rate estimator can infer.

**Warm pools.** For each $(r, f) \in \mathcal{R} \times \mathcal{F}$,
the platform maintains a non-negative integer warm-container count
$W_{r,f}(t)$. A warm container is one that has previously executed
function $f$ in region $r$ and remains alive, awaiting reuse. A warm
container is *evicted* after a TTL of $T_w$ seconds of inactivity, at
which point it ceases to consume idle power. We assume a single platform-
wide $T_w$ for clarity; per-function TTLs introduce no additional
analytical complexity.

### Decision variables

For each invocation $i$, the scheduler produces a decision
$\pi(i) = (r(i), s(i))$ where:

- $r(i) \in \mathcal{R}$ is the region in which $i$ will execute;
- $s(i) \in [a(i), a(i) + D(f(i)) - \tau_e(f(i)) - \tau_c(f(i))]$ is the
  scheduled start time (the deferral window).

A secondary outcome of the decision, observed rather than chosen, is
whether $i$ finds a warm container available at $r(i)$ at time $s(i)$:

$$
w(i) = \mathbf{1}\big[W_{r(i), f(i)}(s(i)) > 0\big].
$$

If $w(i) = 1$, the invocation reuses a warm container and incurs no cold
start; otherwise it pays $\tau_c(f(i))$ in start-up latency and energy.
The scheduler may use the *predicted* value of $w(i)$ in its scoring but
cannot control it deterministically.

### Per-invocation cost

The carbon cost of invocation $i$ under decision $\pi(i) = (r, s)$ is:

$$
\mathrm{Carbon}(i) \;=\; \frac{\mathrm{PUE}_r}{3.6 \times 10^6}\,
C_r(s) \cdot
\Big[\, P_a(f(i)) \big(\tau(i) + (1-w(i))\,\tau_c(f(i))\big)\,\Big]
$$

(active execution plus, when cold, the cold-start active period), with
$C_r$ evaluated at the execution time $s$. We measure energy in joules
internally and convert to kWh via the $3.6 \times 10^6$ factor; the
carbon unit is grams of CO$_2$ equivalent.

The end-to-end latency observed by the user is:

$$
\mathrm{Lat}(i) \;=\; \big(s - a(i)\big)\;+\;\rho\big(h(i), r\big)
\;+\;\big(1 - w(i)\big)\,\tau_c(f(i))\;+\;\tau(i).
$$

The decision $\pi(i)$ is *SLA-feasible* if $\mathrm{Lat}(i) \le D(f(i))$
holds in expectation given $\tau_e(f(i))$ in place of $\tau(i)$. The
realised $\mathrm{Lat}(i)$ may exceed $D(f(i))$ when $\tau(i) > \tau_e(f(i))$;
we count this as an SLA violation and report the rate as a primary metric
in §7.

### System cost

The aggregate carbon cost of a workload over a horizon $[0, T]$ is the
sum of per-invocation execution carbon and the idle-energy carbon
accumulated by warm containers across all (region, function) pairs:

$$
\mathrm{Total\,Carbon}([0,T]) \;=\;
\sum_{i \,:\, a(i) \in [0,T]} \mathrm{Carbon}(i)
\;+\;
\sum_{r \in \mathcal{R}}\sum_{f \in \mathcal{F}}
\frac{\mathrm{PUE}_r}{3.6 \times 10^6}\,
P_i(f) \int_0^T W_{r,f}(t)\,\bar{C}_r\,dt,
$$

where $\bar{C}_r = \frac{1}{T}\int_0^T C_r(t)\,dt$ is the mean intensity
in region $r$ over the horizon. We use $\bar{C}_r$ rather than the
instantaneous $C_r(t)$ for the idle-energy term because the period during
which any single warm container is idle spans a non-trivial fraction of
$T$, making the time-averaged intensity the appropriate accounting basis.

### Constraints

The full schedule $\pi = \{\pi(i)\}_{i \in \mathcal{I}}$ must respect:

1. **Capacity.** For every region $r$ and every time $t$,
   $\big|\{i : r(i) = r,\; s(i) \le t \le s(i) + \tau(i)\}\big| \le K_r$.
2. **SLA-feasibility in expectation.**
   $(s(i) - a(i)) + \rho(h(i), r(i)) + (1 - \hat{w}(i))\,\tau_c(f(i))
   + \tau_e(f(i)) \le D(f(i))$, where $\hat{w}(i)$ is the scheduler's
   warm-pool prediction.
3. **Class-dependent shifting limits.**
   $\ell(f(i)) = \textsc{Interactive} \Rightarrow s(i) = a(i)$ and
   $r(i) = h(i)$;
   $\ell(f(i)) = \textsc{Deferrable} \Rightarrow s(i) \le a(i) + \Delta^{\mathrm{D}}$
   and $\rho(h(i), r(i)) \le \rho^{\mathrm{D}}$;
   $\ell(f(i)) = \textsc{Background} \Rightarrow s(i) \le a(i) + \Delta^{\mathrm{B}}$
   and $\rho(h(i), r(i)) \le \rho^{\mathrm{B}}$,
   for class-specific bounds $\Delta^\cdot$ and $\rho^\cdot$.
4. **Causality.** $s(i) \ge a(i)$ for all $i$.

### Objective

The scheduler seeks to minimise total carbon over $[0, T]$ subject to
the above constraints:

$$
\boxed{\;\;
\pi^* \;=\; \arg\min_{\pi}\; \mathrm{Total\,Carbon}([0,T];\,\pi)
\quad\text{s.t. constraints (1)--(4) hold.}
\;\;}
$$

## 4.2 Online Optimisation Framing

Two structural features distinguish this problem from prior carbon-aware
scheduling work.

### Online, non-clairvoyant

Decisions $\pi(i)$ must be committed at time $a(i)$, before any subsequent
invocation is observed. The scheduler has access to past arrivals, the
current state $\{W_{r,f}(t), K_r - \mathrm{in\text{-}flight}_r(t)\}$, and
a forecast $\hat{C}_r$ of future carbon intensity over a finite horizon
(empirically up to 24 h with degrading accuracy; see §7.5). Crucially, it
does *not* see future arrivals. This rules out a number of classical
offline techniques, including LP relaxations of the optimal schedule and
Lagrangian decomposition over the full workload.

We further restrict to *non-clairvoyant* schedulers: the realised runtime
$\tau(i)$ of invocation $i$ is not revealed until execution completes.
The scheduler uses $\tau_e(f(i))$ as its working estimate, which is
unbiased but introduces SLA-violation risk for invocations whose realised
$\tau(i)$ substantially exceeds the mean. Some prior carbon-aware
schedulers for batch workloads assume per-job runtime is known up front
(e.g. Hanafy et al., CarbonScaler 2023); we cannot.

### Non-additive cost structure

The system cost is *not* separable into per-invocation contributions
because of the warm-pool idle-energy term. A scheduler's decision $\pi(i)$
affects not only $\mathrm{Carbon}(i)$ but also $W_{r,f}(t)$ for all
$t \ge s(i)$, which in turn governs whether subsequent invocations of
$f$ in $r$ pay a cold start and how much idle energy accrues. Decisions
are thus *coupled across invocations* through the warm-pool state. This
is the structural reason why batch-oriented online algorithms — which
typically assume separable per-job costs — do not directly apply.

### Computational and approximation-theoretic remarks

Even with full knowledge of future arrivals, the offline problem is
$\mathbf{NP}$-hard: a reduction from generalised assignment with side
constraints (capacity + deadlines) establishes hardness in the dimensions
of regions and invocations jointly. We do not pursue an approximation-
ratio analysis for two reasons. First, the cost function combines additive
execution carbon with a non-separable idle-energy integral, which puts the
problem outside the standard frameworks for online competitive analysis
(makespan, machine scheduling, $k$-server). Second, an arbitrarily small
adversarial perturbation of the carbon-intensity functions $C_r$ can make
any online scheduler arbitrarily worse than the offline optimum, so any
finite competitive ratio would have to assume a specific stochastic model
of $C_r$ — and the empirical literature is clear that real grid carbon is
neither stationary nor i.i.d. across regions.

We therefore adopt an *empirical* evaluation strategy, comparing GreenFaaS
against a comprehensive set of baselines on the published Azure Functions
schemas and on grid carbon-intensity traces in the Let's-Wait-Awhile /
ElectricityMaps format, across a five-axis sensitivity sweep (§7).
The analytical contribution of the paper is the *local* trade-off
characterisation of §4.3, which gives the scheduler a principled
decision rule at each invocation without claiming a global optimality
result.

### Decomposition strategy

GreenFaaS decomposes the per-invocation problem into two sub-problems
that are tractable individually:

- **Region gating** (a long-run, structural question): given the function's
  current arrival rate $\hat\lambda(f, h)$ and the present carbon
  intensities, which subset of regions could *ever* be a carbon-cheaper
  warm-pool host than the home region? Lemma 1 (§4.3) answers this in
  closed form.

- **Per-slot scoring** (a local, this-invocation question): given the
  set of admitted regions, the deferral horizon, and the per-region
  carbon forecast, which (region, start-time) pair minimises the
  expected carbon for this single invocation, charged appropriately for
  idle-energy effects (§4.3.9)?

The first sub-problem is solved once per (function, region-pair) per
scheduling epoch and cached; the second is a small enumeration over a
short forecast horizon and a handful of regions. Section 5 makes the
algorithm and its complexity precise.
