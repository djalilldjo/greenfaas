# 5. The GreenFaaS Algorithm

This section presents the GreenFaaS scheduler. §5.1 gives a high-level
narrative of the design. §5.2 presents the algorithm in pseudocode, with
each step traceable to the corresponding part of the implementation. §5.3
describes the SLA-tiered policy that governs how the algorithm's degrees
of freedom vary by latency class. §5.4 analyses time and space complexity.
§5.5 discusses arrival-rate estimation, jitter, and forecast inputs. §5.6
addresses a small set of practical design choices and their alternatives.

## 5.1 Design Overview

GreenFaaS schedules each invocation independently at its arrival time,
producing a decision $(r(i), s(i))$ giving the execution region and start
time. The design has three layers:

1. **An arrival-rate estimator** tracks per-(function, home-region) arrival
   rates online with an exponentially-weighted moving average. The rate
   $\hat\lambda$ is the only piece of cross-invocation state used by the
   algorithm.

2. **A region gate** applies Lemma 1 to each candidate region given the
   current $\hat\lambda$ and the present carbon intensities. Regions that
   fail the gate are dropped — not because they could not save carbon
   *now*, but because routing this function class to them on a sustained
   basis would lose carbon to warm-pool idle energy. This is the spatial
   axis of the cold-start trade-off, made operational.

3. **A per-slot scorer** enumerates a small grid of candidate
   (region, start-time) pairs over the admitted regions and the SLA-
   bounded deferral window, and selects the pair with minimum expected
   carbon. The score includes execution energy, this-invocation cold-
   start energy if applicable, and — crucially — an idle-energy term
   that charges deferred invocations for the additional warm-container
   holding cost (§4.3.9).

These three layers are stateless across invocations except for the
arrival-rate estimator. There is no global queue, no inter-invocation
coordination, no pile-up risk from synchronised defer slots (we use a
per-function deterministic jitter to ensure this; see §5.5). The
scheduler can run in parallel across invocations with no locks beyond
the arrival-rate update.

## 5.2 Algorithm

We present GreenFaaS as Algorithm 1, with sub-procedures for the region
gate and the per-slot scoring. The notation follows §4.1. We write
$\mathcal{S}(t)$ for the platform state at time $t$, which includes the
warm-pool counts $W_{r,f}(t)$ and the in-flight counts
$N_r(t) = |\{i : r(i) = r,\; s(i) \le t \le s(i) + \tau(i)\}|$.

The scheduler is invoked once per arrival. Given invocation $i$ at time
$a(i)$ with function $f = f(i)$ and home region $h = h(i)$:

---

**Algorithm 1.** GreenFaaS$(i, \mathcal{S}, \hat{C})$

\begin{align*}
&\textbf{Input: } \text{invocation } i,\; \text{system state }\mathcal{S},\; \text{carbon forecast }\hat{C} \\
&\textbf{Output: } \text{decision }(r(i), s(i)) \\[2pt]
&1.\quad \hat\lambda \;\leftarrow\; \textsc{UpdateRate}(f, h, a(i)) \\
&2.\quad \textbf{if } \ell(f) = \textsc{Interactive} \textbf{ then return } (h, a(i)) \\
&3.\quad (\rho^*, \Delta^*) \;\leftarrow\; \textsc{ClassLimits}(\ell(f)) \\
&4.\quad \mathcal{R}_0 \;\leftarrow\; \{r \in \mathcal{R} :\; \rho(h, r) \le \rho^* \;\wedge\; N_r(a(i))/K_r < u_{\max}\} \\
&5.\quad \mathcal{R}^* \;\leftarrow\; \{r \in \mathcal{R}_0 :\; \textsc{LemmaGate}(f, h, r, \hat\lambda, \mathcal{S}, \hat{C}, a(i))\} \\
&6.\quad \textbf{if } \mathcal{R}^* = \emptyset \textbf{ then } \mathcal{R}^* \leftarrow \{h\} \\
&7.\quad (r^*, s^*) \;\leftarrow\; \textsc{ScoreSlots}(f, h, \mathcal{R}^*, \Delta^*, \hat{C}, \mathcal{S}, a(i)) \\
&8.\quad \textbf{return } (r^*, s^*)
\end{align*}

---

The two sub-procedures encode the spatial and per-slot decisions.

---

**Procedure** \textsc{LemmaGate}$(f, h, r, \hat\lambda, \mathcal{S}, \hat{C}, t)$

\begin{align*}
&1.\quad \textbf{if } r = h \textbf{ then return true} \\
&2.\quad C_r \leftarrow \hat{C}_r(t),\;\; C_h \leftarrow \hat{C}_h(t) \\
&3.\quad \textbf{if } C_r \ge C_h \textbf{ then return true} \quad \text{(\(r\) offers no spatial carbon advantage)} \\
&4.\quad \alpha \leftarrow \tau_c(f)/\tau_e(f),\;\; \beta \leftarrow P_i(f)\,T_w / (P_a(f)\,\tau_e(f)),\;\; \mathrm{ratio} \leftarrow C_h / C_r \\
&5.\quad \beta_{\mathrm{crit}} \leftarrow (\mathrm{ratio} - 1)(1 + \alpha) \\
&6.\quad \textbf{if } \beta \le \beta_{\mathrm{crit}} \textbf{ then return true} \quad \text{(Lemma 1, regime 1)} \\
&7.\quad \lambda^* \leftarrow \textsc{SolveBreakEven}(\mathrm{ratio}, \alpha, \beta, T_w) \quad \text{(Lemma 1, regime 2)} \\
&8.\quad \textbf{return } \hat\lambda > \lambda^*
\end{align*}

---

**Procedure** \textsc{ScoreSlots}$(f, h, \mathcal{R}^*, \Delta^*, \hat{C}, \mathcal{S}, t_0)$

\begin{align*}
&1.\quad (r^*, s^*, S^*) \leftarrow (\bot, \bot, +\infty) \\
&2.\quad \textbf{for each } r \in \mathcal{R}^*\textbf{:} \\
&3.\qquad \delta \leftarrow \text{forecast step},\;\; N \leftarrow \lceil \Delta^* / \delta \rceil + 1 \\
&4.\qquad \bar{C}_r \leftarrow \text{long-run mean of } C_r \\
&5.\qquad w_0 \leftarrow \mathbf{1}[W_{r,f}(t_0) > 0] \\
&6.\qquad \textbf{for } k = 0, 1, \ldots, N-1 \textbf{:} \\
&7.\qquad\quad t_k \leftarrow t_0 + k\delta + \text{jitter}(f, i, k)\cdot \delta \quad \text{(jitter only when }k \ge 1\text{)} \\
&8.\qquad\quad \text{cold} \leftarrow \neg(w_0 \wedge k = 0) \\
&9.\qquad\quad \text{eta} \leftarrow (t_k - t_0) + \rho(h,r) + \text{cold}\cdot\tau_c(f) + \tau_e(f) \\
&10.\qquad\quad \textbf{if } \text{eta} > D(f) \textbf{ then continue} \\
&11.\qquad\quad C_k \leftarrow \hat{C}_r(t_k) \\
&12.\qquad\quad S_{\mathrm{exec}} \leftarrow E_{\mathrm{exec}}(f, r) \cdot C_k \\
&13.\qquad\quad S_{\mathrm{cold}} \leftarrow \text{cold}\cdot E_{\mathrm{cs}}(f, r) \cdot C_k \\
&14.\qquad\quad S_{\mathrm{idle}} \leftarrow E_{\mathrm{idle}}(f, r, t_k - t_0) \cdot \bar{C}_r \\
&15.\qquad\quad S \leftarrow S_{\mathrm{exec}} + S_{\mathrm{cold}} + S_{\mathrm{idle}} \\
&16.\qquad\quad \textbf{if } S < S^* \textbf{ then } (r^*, s^*, S^*) \leftarrow (r, t_k, S) \\
&17.\quad \textbf{if } r^* = \bot \textbf{ then return } (h, t_0) \quad \text{(safety fallback)} \\
&18.\quad \textbf{return } (r^*, s^*)
\end{align*}

---

The three energy quantities entering line 15 are:

$$
E_{\mathrm{exec}}(f, r) \,=\, \tfrac{1}{3.6\times10^6}\,P_a(f)\,\tau_e(f)\,\mathrm{PUE}_r
$$
$$
E_{\mathrm{cs}}(f, r) \,=\, \tfrac{1}{3.6\times10^6}\,P_a(f)\,\tau_c(f)\,\mathrm{PUE}_r
$$
$$
E_{\mathrm{idle}}(f, r, \Delta t) \,=\, \tfrac{1}{3.6\times10^6}\,P_i(f)\,\Delta t\,\mathrm{PUE}_r
$$

all in kWh; multiplying by the appropriate carbon intensity gives grams
CO$_2$ equivalent. The use of $\bar{C}_r$ for the idle term (rather than
$\hat{C}_r(t_k)$) is the §4.3.9 correction: the idle energy accrues
*over* the deferral window, not at a single instant.

\textsc{SolveBreakEven} solves the transcendental equation
$1 + \alpha e^{-u} + \beta(1-e^{-u})/u = r(1+\alpha)$ for $u^* > 0$ by
bisection on the strictly decreasing LHS, returning
$\lambda^* = u^*/T_w$. The bracket is initialised at $u_{\mathrm{lo}} =
10^{-12}$ and grown geometrically; convergence to $10^{-9}$ requires
$\le 200$ iterations in practice and far fewer for realistic parameters.

## 5.3 SLA-Tiered Policy

The class limits $(\rho^*, \Delta^*)$ used in line 3 of Algorithm 1
encode the SLA tiering of §4.1. The default policy is:

| Latency class | $\rho^*$ (RTT budget) | $\Delta^*$ (defer horizon) |
|---------------|----------------------:|---------------------------:|
| \textsc{Interactive} | 0 ms (must stay home) | 0 s (must execute now) |
| \textsc{Deferrable}  | 80 ms                 | $\min(60\text{ s},\; D(f) - \tau_e(f))$ |
| \textsc{Background}  | $\infty$              | $D(f) - \tau_e(f)$ |

\textsc{Interactive} invocations short-circuit at line 2 and skip the
region gate and per-slot scoring entirely. \textsc{Deferrable}
invocations are capped at 60 seconds of deferral even when their
deadline is longer, which keeps the temporal-shift horizon below the
warm-pool TTL ($T_w = 600$ s by default) and ensures that the idle-
energy term in line 14 of \textsc{ScoreSlots} remains a small correction
rather than the dominant cost. \textsc{Background} invocations use the
full deadline, which can extend to hours.

The choice of $\rho^* = 80$ ms for \textsc{Deferrable} corresponds to
intra-continental routing in Europe or within the US. Tightening
$\rho^*$ shrinks $\mathcal{R}_0$ and shifts more savings onto the
temporal axis; relaxing it has the opposite effect. We report
sensitivity to $\rho^*$ in §7.3.

## 5.4 Complexity Analysis

Let $R = |\mathcal{R}|$, $N$ be the number of forecast slots per
region in line 3 of \textsc{ScoreSlots}, and assume the bisection in
\textsc{SolveBreakEven} terminates in $B$ iterations.

**Per-invocation time.** \textsc{UpdateRate} is $O(1)$. The candidate
filtering in line 4 is $O(R)$. The region gate (line 5) calls
\textsc{LemmaGate} once per candidate, each of which is $O(B)$ in
the worst case; the gate's total cost is $O(R \cdot B)$.
\textsc{ScoreSlots} enumerates $O(R \cdot N)$ slots, each requiring
$O(1)$ work given a precomputed mean intensity $\bar{C}_r$. The total
per-invocation time is $O(R \cdot (B + N))$. For our default settings
($R \le 9$, $N \le 12$ for \textsc{Deferrable} with $\delta = 5$ min
and $\Delta^* = 60$ s being a single slot, $N \approx 720$ for
\textsc{Background} with $\Delta^* = 1$ hour), this is well below
100 µs per invocation in practice and dominated by the carbon-forecast
lookups.

**Per-invocation space.** $O(R)$ for the candidate list and the per-region
scoring. The arrival-rate estimator uses $O(|\mathcal{F}| \cdot R)$ space
amortised over time; this is the only state that grows with the workload.

**Comparison to baselines.** FIFO is $O(1)$. Wait-Awhile is $O(N)$.
Spatial is $O(R)$. GreenFaaS is asymptotically equivalent to running
Spatial and Wait-Awhile in series, plus the constant-factor cost of the
lemma test. None of the schedulers consult a global queue or perform
inter-invocation coordination.

## 5.5 Arrival-Rate Estimation and Jitter

**Rate estimation.** \textsc{UpdateRate} maintains an EWMA per
(function, home-region) pair. On arrival at time $t$:

$$
\hat\lambda \leftarrow \alpha \cdot \frac{1}{t - t_{\mathrm{prev}}}
\;+\; (1 - \alpha)\,\hat\lambda_{\mathrm{prev}}
$$

with $\alpha = 0.2$ as the default smoothing weight. Before the first
update, $\hat\lambda$ is initialised to a small default rate
(0.01/s) chosen to make the lemma gate conservative at cold start:
on a function with no observed history, the gate prefers the home
region until evidence accumulates that another region is a sustained
better choice. The estimator is unbiased for stationary Poisson arrivals
and degrades gracefully under burstiness; we evaluate robustness to
the non-Poisson character of Azure traces in §7.

**Per-function jitter.** Without jitter, all invocations of the same
function in the same deferral window would target the same defer slot
— exactly the Wait-Awhile failure mode of synchronised pile-up. We
apply a deterministic per-function offset:

$$
\mathrm{jitter}(f, i, k) \;=\; \tfrac{H(f_{\mathrm{id}} \oplus i_{\mathrm{id}}) \bmod M}{M} \cdot \phi
\quad (k \ge 1)
$$

where $H$ is a hash, $M = 65{,}535$, and $\phi = 0.25$ is the maximum
fraction of a slot width by which jitter shifts the candidate time. The
jitter is zero at $k = 0$ so that immediate execution remains a candidate;
this matters for \textsc{Deferrable} invocations whose deadlines are
tight.

**Forecasts.** $\hat{C}$ may be the true carbon trace (`perfect`), the
true trace within a 1- or 24-hour cutoff with Gaussian-noise decay
beyond (`1h`, `24h`), or a constant equal to each region's historical
mean (`none`). The forecast accuracy is a sensitivity axis in §7.5.

## 5.6 Design Decisions and Alternatives

**Why not a global optimiser?** We could in principle formulate the
per-invocation decision as a small ILP over (region, slot) pairs with
warm-pool state. We do not, because the inputs to the score are already
floating-point (carbon intensities, forecasts, rate estimates) and the
ILP would not yield a different decision in any case where the enumeration
in \textsc{ScoreSlots} is well-posed. An ILP is needed only when
constraints couple invocations, and we have deliberately decomposed the
problem to avoid that coupling.

**Why use the long-run mean $\bar{C}_r$ for idle energy?** Because the
idle period of a warm container spans the gap until the next invocation,
which has no specific scheduled time. The mean intensity is the unbiased
estimator of the average grid intensity over that interval given no
further information. The alternative — using $\hat{C}_r(t_k)$, the
instantaneous intensity at the start of the idle period — systematically
under- or over-charges the idle energy depending on the local trend, and
we observed empirically that doing so destabilises the temporal-shift
decision near the carbon-cycle peak and trough (§7.6).

**Why a Lemma 1 gate rather than per-invocation lemma application?**
The lemma describes the long-run regime: given a stationary arrival rate
and stationary intensities, which region is the carbon-cheaper warm-pool
host? This is the right question for a region-gating decision but not for
a per-invocation temporal decision, which is governed by the §4.3.9
idle-energy condition instead. Conflating the two — as our first
integration attempt did — produces a scheduler that loses 20-40 percentage
points to FIFO in single-region scenarios. We discuss this empirical
finding and the resulting separation of concerns in §4.3.9.

**Why not learn the policy?** Reinforcement learning has been applied to
related cloud scheduling problems (e.g. Mao et al., Decima 2019). For
GreenFaaS, the analytical structure of Lemma 1 gives a closed-form
decision rule with parameter-free generalisation: a new region pair or
function profile can be evaluated immediately without retraining. A
learned policy would inherit the workload distribution of its training
set, which for FaaS is a problem because workload composition varies
dramatically across tenants. We view a learned policy as complementary
future work, layered on top of the lemma-based gate.
