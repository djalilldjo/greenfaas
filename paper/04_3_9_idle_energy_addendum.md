# 4.3.9 Addendum: Idle-energy correction for temporal shifting

The Lemma 1 analysis above addresses the *spatial* placement question:
should a warm pool live in the low-carbon region L, or should we accept cold
starts in the high-carbon region H? It does not directly address the
*temporal* question: should we defer an invocation by $\Delta t$ seconds
within a single region?

These are distinct decisions, and conflating them is a mistake we made in
our first integration attempt — with empirical consequences worth reporting,
because they expose a subtle aspect of the warm-pool/temporal trade-off that
batch-oriented carbon-aware schedulers do not face.

## The temporal idle-energy cost

Deferring an invocation by $\Delta t$ seconds extends the warm-container
lifetime by $\Delta t$ (the container that would have completed the work
must remain warm to serve the deferred invocation, or be reinstated). The
incremental idle energy attributable to this deferral is $P_i \Delta t$,
contributing $P_i \Delta t \bar{C}_r$ carbon at region $r$'s mean intensity
$\bar{C}_r$.

For deferral to be carbon-beneficial, the savings from executing at the
lower-intensity future slot $C(t + \Delta t)$ versus the current slot
$C(t)$ must exceed this idle cost:

$$
P_a \tau_e \big(C(t) - C(t + \Delta t)\big) \;>\; P_i \Delta t\, \bar{C}_r.
$$

Dividing through by $P_a \tau_e \bar{C}_r$ and defining the local carbon
swing $\delta = (C(t) - C(t + \Delta t))/\bar{C}_r$:

$$
\delta \;>\; \frac{P_i \Delta t}{P_a \tau_e}.
$$

The RHS is exactly the dimensionless idle-cost ratio from Lemma 1, but with
$\Delta t$ in place of $T_w$ in the numerator. For our `webhook_handler`
profile and a one-minute deferral, this gives $\delta > 0.3 \cdot 60 /
(4 \cdot 0.3) = 15$, i.e. the carbon intensity must drop by at least
$15\bar{C}$ over the deferral window — clearly impossible. For a
shorter-running, lower-active-power function the threshold is correspondingly
smaller, but the conclusion is robust: *short-horizon temporal deferral is
rarely carbon-beneficial in a single region, regardless of the local diurnal
swing.*

## Practical implication

The scheduler should not blindly enumerate future time slots and pick the
lowest-intensity one; it should charge each candidate deferral by the
idle-energy cost of holding the warm container during the wait. We implement
this by adding the term $P_i \Delta t \bar{C}_r / 3.6 \times 10^6$ (in grams
CO$_2$eq, for $P_i$ in watts) to the per-slot score in
`GreenFaaSScheduler.schedule`. With this correction, GreenFaaS exhibits the
following key behaviors observed in §7:

1. **Do-no-harm in single-region scenarios.** When no cleaner region is
   accessible (e.g. a single-region deployment, or all regions on a
   coal-heavy grid), GreenFaaS correctly chooses *not* to defer, matching
   FIFO's carbon profile rather than degrading it. This is a stronger
   property than the Wait-Awhile baseline, which always defers when the
   threshold is met and consequently burns excess idle energy for negligible
   savings.

2. **Temporal shifting dominates in low-spatial-heterogeneity topologies.**
   In a coal-belt-only topology (DE/GB/PL), where inter-region carbon ratios
   are at most $\sim 3\times$ and intra-region diurnal swings approach the
   same magnitude, GreenFaaS beats pure spatial routing by ~3.5 percentage
   points. The correction enables the scheduler to identify the rare cases
   where intra-region deferral is actually profitable.

3. **Spatial dominates in high-spatial-heterogeneity topologies.** When the
   topology includes a very-low-carbon region such as France or Sweden, the
   spatial axis captures the lion's share of available savings and the
   marginal contribution of temporal shifting is small. GreenFaaS does not
   underperform Spatial in this regime; the two are within 1% on our
   evaluation. The hybrid policy's value here is robustness across
   regimes rather than dominance in any single regime.

This addendum demonstrates that the temporal/spatial axes of carbon-aware
FaaS scheduling are not interchangeable, and that the cold-start carbon
trade-off — which we initially framed as a spatial question — has a direct
temporal analogue with the same dimensionless idle-cost ratio governing
the boundary. We will return to this point in §7 when we report the
sensitivity sweep over topology size.
