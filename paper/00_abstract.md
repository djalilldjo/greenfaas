# Abstract

Data centers' growing electricity footprint has motivated a body of research
on carbon-aware scheduling, in which workloads are shifted in time or space
to coincide with cleaner electricity. However, every major carbon-aware
scheduler proposed to date targets batch or long-running jobs, whose
assumptions of minutes-to-hours runtime, delay tolerance, and clean
suspend/resume are profoundly violated by serverless or Function-as-a-Service
(FaaS) workloads. FaaS functions execute in milliseconds to seconds, often
under sub-second SLAs, suffer expensive cold starts when interrupted, and
arrive in bursty, event-driven patterns. A fast-growing fraction of cloud
computation has consequently remained outside the reach of carbon-aware
techniques.

We present **GreenFaaS**, a carbon-aware scheduling framework for
serverless workloads that unifies three decisions previously treated
separately: spatial routing across regions, temporal deferral within
SLA bounds, and warm-pool placement. Prior FaaS-targeted carbon-aware
schedulers — GreenCourier (WoSC'23) and EcoLife (SC'24) — address the
spatial axis and the hardware-generation axis respectively; GreenFaaS
is the first to give a closed-form joint analysis of the spatial and
temporal axes under cold-start economics, and to demonstrate
provable robustness across topology and workload regimes. GreenFaaS
combines temporal deferral, spatial routing, and carbon-aware
warm-pool management under an SLA-tiered policy distinguishing
interactive, deferrable, and background invocations. The paper's
principal analytical contribution is a closed-form characterisation
of the *cold-start carbon trade-off*: we prove a sharp dichotomy in
which the warm-pool placement decision is governed by a dimensionless
idle-cost ratio $\beta = P_i T_w / (P_a \tau_e)$ relative to a
critical threshold $(r-1)(1+\alpha)$, with a closed-form critical
arrival rate $\lambda^*$ separating the regimes when the threshold
is exceeded. The same idle-cost ratio governs the analogous
temporal-shift trade-off with the deferral interval $\Delta t$ in
place of the warm-pool TTL $T_w$, giving the scheduler principled
decision rules along both axes.

We evaluate GreenFaaS in a discrete-event simulator driven by the Azure
Functions 2019 and 2021 traces and the Let's-Wait-Awhile / ElectricityMaps
carbon-intensity data, against four carbon-aware baselines representative
of recent batch-oriented work. The empirical findings are threefold.
*First*, the canonical Wait-Awhile temporal scheduler *triples* operational
carbon on FaaS workloads relative to a carbon-unaware FIFO baseline, a
clean and reproducible failure mode that quantifies the cost of applying
batch-oriented techniques outside their assumed regime. *Second*, GreenFaaS
captures essentially all available savings (76--79% versus FIFO) across a
range of topologies, matching pure spatial routing within 1% when a
low-carbon region is accessible and outperforming it by 3.5 percentage
points in coal-belt topologies where no low-carbon refuge exists. *Third*,
GreenFaaS preserves a *do-no-harm* property: in single-region scenarios
where temporal shifting would be naively expected to help, GreenFaaS
correctly declines to defer, matching FIFO exactly while a heuristic
ablation loses 37--102% to FIFO. The simulator, scheduler, and trace
loaders are released open source.
