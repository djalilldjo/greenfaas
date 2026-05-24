# 9. Conclusion

We have presented GreenFaaS, a carbon-aware scheduling framework for
serverless workloads that unifies spatial routing, temporal deferral,
and warm-pool placement under an SLA-tiered policy. The technical
substance of the paper lies in three places. First, a closed-form
characterisation of the cold-start carbon trade-off (Lemma 1, §4.3)
that gives the scheduler a principled, parameter-free rule for
deciding when a low-carbon region warrants a warm pool. Second, the
recognition that the same dimensionless idle-cost ratio governs the
analogous temporal-shift decision via a $P_i \Delta t \bar{C}_r$
correction term (§4.3.9), turning what is naively a single-axis
analysis into a coherent treatment of both spatial and temporal
decisions. Third, an SLA-tiered hybrid algorithm (§5) whose per-
invocation complexity is $O(R \cdot N)$ and which has no inter-
invocation coordination beyond a per-function arrival-rate estimator.

The empirical evaluation, on real-schema Azure Functions traces and
real grid carbon-intensity data, supports three conclusions. The most
prominent: GreenFaaS reduces operational carbon by 76–79% relative to
a carbon-unaware FIFO baseline in topologies with a low-carbon refuge,
matching pure spatial routing to within one percentage point and
beating it by 3.5 percentage points in coal-belt topologies where no
low-carbon refuge exists. The most consequential, in our view: the
*do-no-harm* property, in which GreenFaaS correctly declines to act
when no axis offers real savings, matching FIFO byte-for-byte in
single-region scenarios and at zero shiftable workload fraction —
while a heuristic ablation lacking the idle-energy correction loses
37–102% to FIFO in the same scenarios. The most surprising:
GreenFaaS's carbon reduction is *forecast-invariant* across the four
forecast horizons we tested, a structural consequence of using
instantaneous carbon intensities for the spatial gate and short
deferral windows for the temporal scoring.

We also documented a clean and reproducible failure mode of the
batch-oriented Wait-Awhile scheduler when applied to FaaS workloads:
it *triples* operational carbon relative to FIFO across every
sensitivity setting we tested. This is the empirical core of the
paper's positioning claim that the batch carbon-aware toolkit does
not transfer to FaaS without substantial redesign.

A number of directions remain open: the multi-container
generalisation of Lemma 1 (§8.1), an extension to non-Poisson
arrivals (§8.2), a unified spatial/temporal/hardware-generation
scheduler combining GreenFaaS with EcoLife (§8.5), and a
production-system validation on Knative (§8.7). The simulator, the
trace loaders, the scheduler implementations, and the manuscript
sources are released open source to support these follow-ups and
to allow direct comparison by future carbon-aware FaaS proposals.
