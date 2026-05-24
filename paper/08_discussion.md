# 8. Discussion and Limitations

This section discusses the principal limitations of the work and the
directions we see as most promising for follow-up. We organise the
discussion around the assumptions made by the analytical contribution
(§4.3) and the empirical methodology (§7), and identify five specific
limitations that constrain the generality of the claims.

## 8.1 Single-Container Warm Pools

Lemma 1 is stated and proved for a *single* warm container per
(region, function) pair. Real FaaS platforms maintain warm *pools* of
size $n \ge 1$, where the size adapts to observed concurrency. The
multi-container generalisation introduces two changes to the analysis:

- The probability that a given invocation finds a warm container
  available is no longer $\Pr[X > T_w] = e^{-\lambda T_w}$ but is a
  function of the steady-state distribution of warm containers in an
  M/M/$n$-like queue. For large $n$ relative to $\lambda T_w$, this
  probability approaches 1, and the cold-start term in $E_A(\lambda)$
  vanishes; for small $n$, the probability is bounded below by the
  single-container case.

- The idle-energy term scales linearly with the expected number of
  idle containers, $\mathbb{E}[n - \text{busy}]$, which depends on the
  same steady-state distribution.

Both changes preserve the *structure* of the dichotomy — there is
still a critical idle-cost ratio $\beta_{\text{crit}}(n, r, \alpha)$
that separates the regimes — but the closed form of $\beta_{\text{crit}}$
depends on $n$. We have deferred the multi-container analysis to a
follow-up paper because the single-container result is already
expressive enough to drive the scheduler's per-pair gating decisions
(the scheduler can apply the single-container lemma to each
*incremental* container in the pool), and because the empirical impact
of the multi-container generalisation is small in the regimes we
tested. We caveat this in §7.3 and elaborate in Appendix A of the
extended technical report.

## 8.2 Non-Poisson Arrivals

The lemma assumes Poisson inter-arrival times, which is the standard
simplifying assumption in FaaS theory but is empirically known to be
violated by real production workloads. Shahrad et al. (USENIX ATC'20)
document heavy-tailed inter-arrival distributions on Azure Functions,
and our own Azure 2019 reconstructed trace exhibits the same
heavy-tailedness (§7.1). The empirical evaluation on the Azure 2021
schema-faithful trace (§7.2 headline results) shows that the scheduler
still achieves 67.6% reduction relative to FIFO under non-Poisson
arrivals, within 0.4 percentage points of pure spatial routing. We
interpret this as evidence that the lemma's *qualitative* prescription
(warm in the low-carbon region above a critical rate, cold-start in
the high-carbon region below it) is robust to the arrival-process
assumption, even though the *exact* break-even rate $\lambda^*$ shifts
under bursty arrivals.

A more rigorous treatment would extend the lemma to general renewal
processes, where $\Pr[X > T_w]$ would be replaced by the survival
function of the inter-arrival distribution. We expect the dichotomy
structure to survive this extension, since the underlying argument
(strict monotonicity of the per-invocation carbon as a function of
arrival rate) does not depend on the Poisson assumption. We have not
pursued the formal extension in this paper.

## 8.3 PUE Heterogeneity Across Regions

The lemma assumes similar Power Usage Effectiveness (PUE) across
regions, allowing the small PUE differences to be absorbed into
effective carbon intensities. Real data centres span a non-trivial PUE
range — hyperscale facilities in Sweden and Norway operate at PUE
$\approx 1.1$ while older sites can be at PUE $\approx 1.5$ — and
this affects the warm-pool decision because idle energy is multiplied
by PUE before being charged. The lemma extends straightforwardly by
replacing $r = C_H / C_L$ with $r' = (C_H \cdot \text{PUE}_H) / (C_L \cdot
\text{PUE}_L)$, but the empirical evaluation in this paper uses a
uniform $\text{PUE} = 1.2$ across regions. A PUE-heterogeneous
evaluation, ideally with measured PUE values from real
hyperscale providers, is a natural follow-up.

## 8.4 No Competitive-Ratio Bound

As discussed in §4.2, we make no claim of competitive optimality
against the offline schedule. The non-separable cost structure (idle
energy couples decisions across invocations through the warm-pool
state) and the adversarial-perturbation argument together rule out a
finite competitive ratio in the worst case. The Lechowicz et al.
(SIGMETRICS'24) double-threshold framework gives optimal competitive
ratios for a strictly simpler model (single workload, pause/resume
with fixed switching cost) and is a natural starting point for a
future theoretical extension. The principal obstacle is the
warm-pool idle-energy term, which has no analogue in the
pause/resume model. We view this as the most interesting open
theoretical question raised by the paper.

## 8.5 Embodied Carbon

GreenFaaS optimises *operational* carbon — the carbon emitted by the
electrical energy used to execute and keep functions warm — and
ignores *embodied* carbon, the carbon emitted during the manufacture
of the underlying hardware. EcoLife (Jiang et al., SC'24) addresses
embodied carbon directly by routing functions to older, already-
amortised hardware where the marginal embodied cost is zero. This is
an orthogonal axis to the spatial/temporal grid-carbon axes we
exploit, and a natural composition would route an invocation first by
GreenFaaS's spatial/temporal logic to a region/time, and then within
that region by EcoLife's hardware-generation logic. We have not built
this composition; it is the most concrete next-paper-sized direction
this work suggests.

## 8.6 Scope of the Real-Trace Validation

The Azure Functions traces we use date from 2019 and 2021. The
serverless workload mix has evolved since then — most notably with
the explosion of LLM inference functions, which have substantially
longer durations and higher per-invocation energy than the workloads
those traces capture. Our latency-class assignment heuristics in
§7.1 would classify LLM inference as background, which is technically
correct under our definition (long deadlines, asynchronous use cases
predominate) but understates the schedulable opportunity for
*interactive* LLM applications such as chatbots. We expect the
qualitative findings to carry over — GreenFaaS's do-no-harm property
is workload-independent — but the absolute numbers would shift if we
re-ran the evaluation on a contemporary LLM-heavy trace. We hope
that the recent release of more LLM-focused workload traces will
enable this follow-up.

## 8.7 Production-System Validation

GreenFaaS is evaluated entirely in simulation. The Lemma 1
break-even computations are cheap enough ($O(B)$ for $B$
bisection iterations, less than 100 µs per call in our
measurements) that integration into a production scheduler such as
Knative or AWS Lambda is plausible, but we have not attempted it.
The closest production-system point of comparison is GreenCourier
(Chadha et al.), which is a Kubernetes scheduler plugin; an
equivalent GreenFaaS plugin would inherit the same
binding-latency overhead (~24 ms above default scheduler latency,
per their measurements). A real-system validation, ideally on a
multi-region Knative deployment with measured grid carbon
intensities, would be the strongest possible confirmation of the
simulator results.

## 8.8 What These Limitations Mean for the Paper's Claims

We interpret these limitations not as caveats that weaken the
contributions, but as *scope statements* that delimit what we have
shown. The closed-form trade-off characterisation, the SLA-tiered
algorithm, the do-no-harm empirical property, and the
forecast-invariance result are robust within the assumptions stated,
and we have been explicit throughout the paper about where those
assumptions apply. The interesting next steps are the multi-container
generalisation (§8.1), the embodied-carbon composition with EcoLife
(§8.5), and the production-system validation (§8.7) — each of which
is a tractable follow-up rather than a fundamental obstacle.
