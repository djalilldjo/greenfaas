# 4.3 The Cold-Start Carbon Trade-off

In this section we formalize one of GreenFaaS's central technical contributions:
a closed-form analysis of when it is carbon-cheaper to keep a warm pool in a
low-carbon region than to cold-start in a high-carbon region. The result is
non-obvious because warm pools consume non-trivial idle energy, and at low
arrival rates that idle energy — accumulated in the low-carbon region — can
exceed the cold-start penalty paid in the high-carbon region. The empirical
existence of this trade-off has been noted in concurrent work — most
explicitly by EcoLife (Jiang et al., SC'24), which addresses it through
a metaheuristic Particle Swarm Optimisation — but to our knowledge it
has not previously been characterised in closed form. The closed form
is consequential because it gives the scheduler a parameter-free
decision rule that generalises across function profiles and region
pairs without retraining or solver invocations.

## 4.3.1 Setup

Consider a single function with execution time $\tau_e$ and cold-start
duration $\tau_c$, with active power draw $P_a$ during both execution and
cold start, and warm-idle power draw $P_i$ per container. Warm containers are
evicted after a TTL of $T_w$ seconds of inactivity. Invocations of this
function arrive as a homogeneous Poisson process with rate $\lambda$.

Two regions are available:
- **Region L** with grid carbon intensity $C_L$ (g CO$_2$eq / kWh).
- **Region H** with grid carbon intensity $C_H > C_L$.

We compare two strategies:

- **Strategy A (warm in L):** keep a warm pool in region $L$. Each arriving
  invocation either reuses a warm container, or — if it arrives after the
  TTL has expired — pays a cold start. Idle energy accumulates between
  invocations.
- **Strategy B (cold in H):** keep no warm pool. Every invocation pays a cold
  start in region $H$. No idle energy is consumed.

We compute the expected carbon per invocation under each strategy and derive
the condition under which Strategy A is preferable.

## 4.3.2 Expected energy per invocation

**Strategy A.** For Poisson inter-arrival times $X \sim \text{Exp}(\lambda)$:

- The probability that a given invocation finds no warm container available
  (because the previous invocation completed more than $T_w$ seconds ago) is
  $\Pr[X > T_w] = e^{-\lambda T_w}$.
- The expected idle time of a container between two consecutive uses, capped
  at the TTL, is $\mathbb{E}[\min(X, T_w)] = (1 - e^{-\lambda T_w})/\lambda$.

Assuming $\tau_e \ll \min(1/\lambda, T_w)$ so that execution time is
negligible against inter-arrival and TTL scales, the expected energy per
invocation under Strategy A is:

$$
E_A(\lambda) \;=\; P_a \tau_e \;+\; e^{-\lambda T_w} P_a \tau_c \;+\; \frac{1 - e^{-\lambda T_w}}{\lambda} P_i
$$

The three terms are: execution energy, expected cold-start energy (a cold
start is paid with probability $e^{-\lambda T_w}$), and expected idle energy
(the warm container sits idle for $\min(X, T_w)$ seconds between uses).

**Strategy B.** With no warm pool, every invocation cold-starts:

$$
E_B \;=\; P_a \tau_e + P_a \tau_c \;=\; P_a(\tau_e + \tau_c)
$$

independent of $\lambda$.

## 4.3.3 Carbon per invocation and the break-even condition

Per-invocation carbon (in grams CO$_2$eq, modulo unit conversion) is
$E \cdot C \cdot \text{PUE}$. Since PUE multiplies both sides identically when
the two regions have similar PUE — and we can absorb a small PUE difference
into the carbon intensities — we work in $E \cdot C$ units.

Strategy A is greener than Strategy B if and only if:

$$
E_A(\lambda) \cdot C_L \;<\; E_B \cdot C_H
\quad\Longleftrightarrow\quad
\frac{E_A(\lambda)}{E_B} \;<\; \frac{C_H}{C_L}.
$$

Let $r = C_H / C_L > 1$ denote the **carbon ratio** between the two regions.
Introduce two dimensionless parameters:

$$
\alpha \;=\; \frac{\tau_c}{\tau_e}
\qquad
\text{(cold-start-to-execution ratio)},
\qquad
\beta \;=\; \frac{P_i T_w}{P_a \tau_e}
\qquad
\text{(warm-pool idle-cost ratio)}.
$$

Both have direct physical meaning: $\alpha$ measures how expensive a cold
start is relative to a single execution, and $\beta$ measures the worst-case
idle energy a warm container can accumulate (over a full TTL) relative to a
single execution.

Substituting $u = \lambda T_w$, the inequality $E_A(\lambda) < r E_B$ becomes:

$$
\boxed{\;1 + \alpha e^{-u} + \beta\,\frac{1 - e^{-u}}{u} \;<\; r\,(1+\alpha)\;} \tag{*}
$$

## 4.3.4 Lemma (Cold-start carbon dichotomy)

> **Lemma 1.** *Define the* critical idle-cost ratio
> $\beta_{\mathrm{crit}}(r,\alpha) = (r-1)(1+\alpha)$.
>
> 1. *If $\beta \le \beta_{\mathrm{crit}}(r,\alpha)$, then strategy A is
>    greener than strategy B for* **all** *arrival rates $\lambda > 0$.*
> 2. *If $\beta > \beta_{\mathrm{crit}}(r,\alpha)$, then there exists a
>    unique critical arrival rate $\lambda^* > 0$ such that strategy A is
>    greener than strategy B precisely when $\lambda > \lambda^*$.*

**Proof.** Let $f(u) = 1 + \alpha e^{-u} + \beta(1 - e^{-u})/u$ be the LHS of
$(*)$. We study $f$ on $(0, \infty)$.

*Limits.* As $u \to 0^+$, $e^{-u} \to 1$ and $(1-e^{-u})/u \to 1$, so
$f(0^+) = 1 + \alpha + \beta$. As $u \to \infty$, $e^{-u} \to 0$ and
$(1-e^{-u})/u \to 0$, so $f(\infty) = 1$.

*Monotonicity.* Differentiating term by term:
$f'(u) = -\alpha e^{-u} + \beta \cdot \frac{d}{du}\left[\frac{1 - e^{-u}}{u}\right]$.
The second term is the derivative of $g(u) = (1-e^{-u})/u$, which is
strictly negative for $u > 0$ (this is a standard fact: $g$ is decreasing
from $g(0^+) = 1$ to $g(\infty) = 0$, since $u e^{-u} < 1 - e^{-u}$ for
$u > 0$). Hence $f'(u) < 0$ for all $u > 0$, i.e. $f$ is strictly decreasing.

*Comparison with the threshold $r(1+\alpha)$.* The condition $f(0^+) \le r(1+\alpha)$
rearranges to $\beta \le (r-1)(1+\alpha) = \beta_{\mathrm{crit}}$.

- If $\beta \le \beta_{\mathrm{crit}}$: since $f$ is decreasing and
  $f(0^+) \le r(1+\alpha)$, the inequality $(*)$ holds for all $u > 0$.
  Strategy A wins everywhere.
- If $\beta > \beta_{\mathrm{crit}}$: $f(0^+) > r(1+\alpha) > 1 = f(\infty)$,
  so by the intermediate-value theorem and strict monotonicity, there is a
  unique $u^* > 0$ with $f(u^*) = r(1+\alpha)$. Strategy A wins iff $u > u^*$,
  i.e. $\lambda > \lambda^* = u^*/T_w$. $\blacksquare$

## 4.3.5 Approximation near the threshold

In the regime where $\beta$ only slightly exceeds $\beta_{\mathrm{crit}}$,
$u^*$ is small and we can Taylor-expand the LHS of $(*)$. Using
$e^{-u} \approx 1 - u$ and $(1 - e^{-u})/u \approx 1 - u/2$:

$$
f(u) \;\approx\; 1 + \alpha(1 - u) + \beta(1 - u/2) \;=\; (1 + \alpha + \beta) - u\Big(\alpha + \tfrac{\beta}{2}\Big).
$$

Setting this equal to $r(1+\alpha)$ and solving:

$$
u^* \;\approx\; \frac{\beta - \beta_{\mathrm{crit}}}{\alpha + \beta/2},
\qquad
\lambda^* \;\approx\; \frac{\beta - \beta_{\mathrm{crit}}}{T_w(\alpha + \beta/2)}.
$$

This linearized form is useful for scheduler-side estimation when full
numerical root-finding is undesirable, and shows that $\lambda^*$ scales
linearly with the excess $\beta - \beta_{\mathrm{crit}}$ near the boundary.

## 4.3.6 Worked example with FaaS-realistic parameters

Take a function typical of our `webhook_handler` profile:
$\tau_e = 0.3$ s, $\tau_c = 1.0$ s, $P_a = 4$ W, $P_i = 0.3$ W,
$T_w = 600$ s. This gives:

$$
\alpha = \frac{1.0}{0.3} \approx 3.33, \qquad
\beta = \frac{0.3 \cdot 600}{4 \cdot 0.3} = 150.
$$

The dominant scale of $\beta$ — over a hundred — reflects a fundamental fact
about FaaS: a warm container left idle for the full TTL consumes far more
energy than a single execution of the function. Idle cost is not a small
correction; it is the largest term in the comparison whenever invocations
are infrequent.

For the France/Germany region pair, $C_L \approx 60$, $C_H \approx 350$, so
$r \approx 5.8$ and $\beta_{\mathrm{crit}} = 4.8 \cdot 4.33 \approx 20.8$.
Since $\beta = 150 \gg \beta_{\mathrm{crit}}$, a finite break-even rate
$\lambda^*$ exists. Numerical solution of $(*)$ gives $u^* \approx 6.2$,
hence:

$$
\lambda^* \;\approx\; \frac{6.2}{600\,\text{s}} \;\approx\; 0.010\,\text{s}^{-1}.
$$

**Interpretation.** A function invoked more than roughly once every 100
seconds should keep a warm pool in France; a function invoked less
frequently is carbon-cheaper to cold-start in Germany. The linear
approximation in §4.3.5 gives $\lambda^* \approx 0.0027$/s, which is roughly
$4\times$ smaller than the true rate of $0.010$/s — confirming that the
threshold $\beta_{\mathrm{crit}}$ is exceeded by enough ($\beta = 150$ vs
$\beta_{\mathrm{crit}} \approx 21$) that the linearization is outside its
valid regime here. The linearization remains useful as a conservative lower
bound on $\lambda^*$.

For France/Poland ($r \approx 11.7$, $\beta_{\mathrm{crit}} \approx 46$), the
same calculation yields $u^* \approx 2.87$ and $\lambda^* \approx 0.0048$/s
(period $\approx 210$s) — the much larger carbon ratio shifts the break-even
down by roughly $2\times$, expanding the regime in which Poland-side cold
starts lose to France-side warm pools.

## 4.3.7 Consequences for the GreenFaaS scheduler

The lemma is constructive: it tells the scheduler, on a per-function basis,
which side of the trade-off each function sits on. We use it as follows.

For each (function, region-pair) tuple, the scheduler maintains an estimate
$\hat\lambda$ of the function's recent arrival rate (an exponentially
weighted moving average over the last few minutes). Given $\hat\lambda$ and
the current pair $(C_L, C_H)$ from the carbon model, the scheduler computes
$\lambda^*$ from $(*)$ once per scheduling epoch and selects:

- the **warm-in-L** strategy if $\hat\lambda > \lambda^*$, sizing the warm
  pool in $L$ to expected demand;
- the **cold-in-H** strategy if $\hat\lambda < \lambda^*$, declining to keep
  a warm pool and accepting cold starts in $H$.

This is the principled replacement for the hand-tuned cold-start penalty in
the first-cut scheduler of §5. We will see in §7 that adopting it directly
recovers a measurable carbon improvement over pure spatial routing and
explains the empirical pattern observed in our 48-hour comparison.

## 4.3.8 Remarks and limitations

**Multiple warm containers.** The lemma is stated for a single warm container.
Generalizing to a warm pool of size $n$ with concurrent invocations changes
the idle-energy term to one involving the steady-state distribution of warm
containers in an M/M/n-style model, but the dichotomy structure — and the
form of $\beta_{\mathrm{crit}}$ — survives, with $n$ entering linearly in
$\beta$. We defer the full multi-container statement to Appendix A.

**Non-Poisson arrivals.** Real FaaS workloads are bursty and not Poisson;
the Azure 2019/2021 traces in particular exhibit heavy-tailed inter-arrival
distributions. The lemma should therefore be read as a *guideline for
expected behavior*, not an exact prescription. Our evaluation (§7) uses real
traces and tests the lemma empirically; we find the qualitative dichotomy
holds robustly even under burstier arrivals.

**PUE differences.** We assumed similar PUE between regions. For regions
with materially different PUE — for instance hyperscale data centers in
Sweden (PUE $\approx 1.1$) versus older sites (PUE $\approx 1.5$) — the
analysis extends by replacing $r$ with $r' = (C_H \cdot \text{PUE}_H)/(C_L \cdot \text{PUE}_L)$.
