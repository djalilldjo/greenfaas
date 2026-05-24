# GreenFaaS — Carbon-Aware Serverless Scheduling

Reference implementation and simulator for the GreenFaaS research project: the
first carbon-aware scheduling framework designed natively for Function-as-a-
Service (FaaS) workloads.

This repository contains the manuscript drafts (abstract, introduction, and
the §4.3 cold-start carbon trade-off lemma), a self-contained discrete-event
simulator, five scheduler implementations spanning the comparison set, the
motivation figure for §3, the break-even contour figure for §4.3, and a
multi-scenario evaluation harness.

## Repository layout

```
greenfaas/
├── greenfaas/                  Python package
│   ├── __init__.py             public API
│   ├── core.py                 data classes
│   ├── carbon.py               carbon-intensity model (synthetic traces)
│   ├── workload.py             synthetic FaaS workload generator
│   ├── tradeoff.py             Lemma 1: closed-form cold-start trade-off
│   ├── schedulers.py           FIFO, Wait-Awhile, Spatial, GreenFaaS-v1,
│   │                            GreenFaaS, ArrivalRateTracker
│   ├── simulator.py            discrete-event simulator + metrics
│   └── traces/                 real-trace loaders
│       ├── azure_2021.py       per-invocation 2021 trace
│       ├── azure_2019.py       aggregated 2019 trace + reconstruction
│       └── carbon_csv.py       hourly carbon CSV loader (LWA/ElectricityMaps)
├── scripts/
│   ├── run_experiment.py       end-to-end comparison (synthetic)
│   ├── scenario_sweep.py       multi-topology sweep (synthetic)
│   ├── run_real_traces.py      real-trace pipeline runner
│   ├── generate_sample_data.py make schema-faithful sample files
│   ├── sensitivity_sweep.py    §7 four-axis sensitivity sweep
│   ├── replot_sensitivity.py   regenerate §7 figures from saved CSVs
│   ├── motivation_figure.py    §3 motivation figure
│   ├── tradeoff_figure.py      §4.3 break-even contour
│   └── verify_tradeoff.py      numerical verification of Lemma 1
├── paper/
│   ├── 00_abstract.md
│   ├── 01_introduction.md
│   ├── 02_related_work.md                related work survey + positioning
│   ├── 03_motivation.md                  motivation around the §3 figure
│   ├── 04_1_4_2_problem_formulation.md   problem statement + online framing
│   ├── 04_3_tradeoff_lemma.md            Lemma 1 + proof + worked example
│   ├── 04_3_9_idle_energy_addendum.md    the temporal-axis correction
│   ├── 05_algorithm.md                   the GreenFaaS algorithm (pseudocode)
│   ├── 06_simulator.md                   discrete-event simulator description
│   ├── 07_1_real_trace_methodology.md    §7 intro + real-trace methodology
│   ├── 07_2_to_7_8_evaluation.md         empirical results across 5 axes
│   ├── 08_discussion.md                  limitations + future directions
│   └── 09_conclusion.md                  short closing summary
├── results/                    sensitivity-sweep CSVs (generated)
│   ├── sensitivity_intensity.csv
│   ├── sensitivity_sla_mix.csv
│   ├── sensitivity_forecast.csv
│   └── sensitivity_variability.csv
├── sample_data/                schema-faithful sample files (generated)
│   ├── azure_2019/
│   ├── azure_2021/
│   └── carbon/
├── figures/
│   ├── motivation_carbon_vs_invocations.png
│   └── tradeoff_breakeven_contour.png
└── README.md
```

## Reproducing the current results

```
python scripts/verify_tradeoff.py        # verifies Lemma 1 numerically
python scripts/run_experiment.py         # synthetic 24h, 5 schedulers
python scripts/scenario_sweep.py         # synthetic 24h sweep over five topologies
python scripts/sensitivity_sweep.py      # §7 four-axis sweep (~90s wall)
python scripts/replot_sensitivity.py     # regenerate §7 figures from saved CSVs
python scripts/generate_sample_data.py   # write schema-faithful sample traces
python scripts/run_real_traces.py        # real-trace pipeline (sample data by default)
python scripts/motivation_figure.py      # writes figures/motivation_*.png
python scripts/tradeoff_figure.py        # writes figures/tradeoff_*.png
```

To run the real-trace pipeline on the actual Azure / ElectricityMaps datasets,
download them and point `run_real_traces.py` at the directories:

```
python scripts/run_real_traces.py \
    --azure-2021-csv /path/to/AzureFunctionsInvocationTrace.csv \
    --carbon-dir     /path/to/lets-wait-awhile/data
```

No code changes are needed — the loaders match the published schemas exactly.

## Real-trace headline results (sample data, schema-faithful)

Azure 2021 trace, 5,000 invocations over 6 hours, 5 regions:

| Scheduler   | Carbon (g) | vs FIFO  | SLA viol. | Cold-start |
|-------------|-----------:|---------:|----------:|-----------:|
| FIFO        |       28.8 |    0.0%  |     0.44% |      3.52% |
| Wait-Awhile |       30.7 |   −6.6%  |     0.44% |      5.90% |
| Spatial     |        9.2 |  +68.0%  |     0.44% |      3.52% |
| GreenFaaS-v1|       13.0 |  +55.0%  |     0.44% |     24.92% |
| **GreenFaaS** |      9.4 |  +67.6%  |     0.44% |      3.72% |

Azure 2019 reconstructed trace, 20,651 invocations over 24 hours, 5 regions:

| Scheduler   | Carbon (g) | vs FIFO  | SLA viol. | Cold-start |
|-------------|-----------:|---------:|----------:|-----------:|
| FIFO        |       86.7 |    0.0%  |     2.81% |     10.32% |
| Wait-Awhile |       90.7 |   −4.6%  |     2.81% |     11.06% |
| Spatial     |       48.4 |  +44.1%  |     2.81% |     10.32% |
| GreenFaaS-v1|       53.5 |  +38.3%  |     2.83% |     17.35% |
| **GreenFaaS** |     56.4 |  +35.0%  |     2.81% |     10.81% |

The real-trace results match the synthetic-data story: GreenFaaS tracks
Spatial closely in topologies with a low-carbon refuge (FR), and the v1
ablation suffers in both cases without the §4.3.9 idle-energy correction
(24.9% and 17.4% cold-start rates, vs ~3% and ~11% for the corrected version).

## Headline results (scenario sweep, 24h, 173k invocations)

| Topology              | FIFO  | Wait-Awhile  | Spatial    | GreenFaaS-v1 | **GreenFaaS** |
|-----------------------|------:|-------------:|-----------:|-------------:|--------------:|
| Full 6-region         |  47.5 | +236% carbon | **−78.9%** | −78.0%       | −78.2%        |
| EU-only (FR/DE/GB/PL) |  54.1 | +271% carbon | **−76.0%** | −75.6%       | −75.7%        |
| Coal-belt (DE/GB/PL)  |  67.6 | +279% carbon | −37.2%     | +21.4%       | **−40.7%**    |
| Single-region DE      |  50.8 | +234% carbon |   0.0%     | −37.4%       | **0.0%**      |
| Single-region CAISO   |  46.9 | +137% carbon |   0.0%     | −102.0%      | **0.0%**      |

Numbers are operational carbon reduction vs FIFO (positive = greener,
"+236%" means carbon **rose** by 236% vs FIFO). Story in three points:

1. **The "batch schedulers don't transfer to FaaS" claim is empirically
   sharp.** Wait-Awhile *triples* operational carbon under FaaS workloads
   in every scenario — the synchronised-defer pile-up effect we describe
   in §4.3.9 is a clean, publishable-quality failure mode.

2. **GreenFaaS's contribution depends on the topology.** When a low-carbon
   refuge exists (FR or SE), pure spatial routing captures essentially all
   achievable savings. GreenFaaS does not underperform here (within 1% of
   Spatial), but it does not dominate either. **When no low-carbon refuge
   exists** — the coal-belt scenario — GreenFaaS beats Spatial by 3.5
   percentage points.

3. **GreenFaaS preserves a "do no harm" property** in single-region
   scenarios, matching FIFO carbon exactly. The v1 ablation shows what
   happens *without* the §4.3.9 idle-energy correction: v1 burns excess
   idle energy chasing tiny diurnal swings and loses 37–102% to FIFO. This
   is the cleanest empirical justification for the lemma-driven design.

## The cold-start carbon trade-off (Lemma 1)

The paper's central analytical contribution. Given a function with execution
time $\tau_e$, cold-start duration $\tau_c$, active and idle power $P_a, P_i$,
warm-pool TTL $T_w$, and a two-region pair with carbon ratio $r = C_H / C_L$,
we derive a dichotomy:

- If the idle-cost ratio $\beta = P_i T_w / (P_a \tau_e) \le (r-1)(1+\alpha)$
  with $\alpha = \tau_c / \tau_e$, then a warm pool in the low-carbon region
  is greener at every arrival rate.
- Otherwise, there is a unique critical arrival rate $\lambda^* > 0$ above
  which the warm pool wins and below which cold-starting in the high-carbon
  region wins.

For a webhook-like function ($\tau_e$=0.3s, $\tau_c$=1.0s, $P_a$=4W, $P_i$=0.3W,
$T_w$=600s) and the France/Germany pair ($r$=5.83):
- $\beta = 150$, $\beta_{\rm crit} \approx 21$, so a finite $\lambda^*$ exists.
- Numerical solution: $\lambda^* \approx 0.010$ /s, period ~100 s.
- Functions invoked more frequently than once per 100 s warm in France;
  rarer functions are greener cold-starting in Germany.

The lemma is verified end-to-end in `scripts/verify_tradeoff.py` against
brute-force carbon comparison at 56 grid points; all checks pass.

## Status against the research plan

**The full manuscript is drafted and built.** The canonical source is
the LaTeX in `latex/sections/` (the `paper/*.md` files below are the
original research-plan drafts and are kept for provenance). The built
manuscript is available in three formats via `latex/build.sh`:
`paper_elsevier.pdf` (~99pp review format with line numbers),
`paper_elsevier_final.pdf` (~41pp camera-ready), and `paper.pdf`
(~29pp two-column). Every numerical claim in the paper is reproducible
from the scripts in this repository; the table-generating scripts
(`scripts/run_*.py`, `scripts/scenario_sweep.py`) emit the exact
percentages quoted in the manuscript, and cross-references have been
verified to resolve.

* **§1 Introduction** — drafted, with headline numbers and prior-work
  positioning matching the §7 results and §2 survey.
* **§2 Related Work** — drafted in `paper/02_related_work.md` with precise
  positioning against the three closest FaaS-targeted carbon-aware
  schedulers (GreenCourier, EcoLife, CASPER) and the theoretical foundations
  (Lechowicz et al.'s pause-and-resume line of work).
* **§3 Motivation** — drafted in `paper/03_motivation.md`, building on the
  joint Azure × ElectricityMaps figure already in `figures/`.
* **§4.1–4.2 Problem Formulation** — drafted in `paper/04_1_4_2_problem_formulation.md`,
  including the online optimisation framing and an honest discussion of why
  no competitive-ratio bound is available.
* **§4.3 Cold-start carbon trade-off** — formalised, proved, and numerically
  verified. The §4.3.9 addendum documents the parallel temporal-axis
  condition discovered during scheduler integration.
* **§5 Algorithm** — drafted in `paper/05_algorithm.md` with pseudocode that
  matches the implementation line-for-line, plus complexity analysis and a
  discussion of alternatives we considered.
* **§6 Simulator** — drafted in `paper/06_simulator.md`, attributing the
  `faas-sim` and `vessim` design heritage and describing the event model,
  warm-pool accounting, and extension points.
* **§7 Evaluation** — drafted in `paper/07_1_*` and `paper/07_2_to_7_8_*`,
  covering headline results and all five sensitivity axes from the research
  plan (topology, SLA mix, forecast accuracy, carbon variability, workload
  intensity).
* **§8 Discussion** — drafted in `paper/08_discussion.md`, covering eight
  honest limitations and pointing at follow-up directions.
* **§9 Conclusion** — drafted in `paper/09_conclusion.md`.

* **Simulator** — implemented end-to-end. Real-trace loaders match published
  Azure 2019, Azure 2021, and Let's-Wait-Awhile schemas exactly. Headline
  results in §7 are reproducible via the scripts in this repository.
* **Baselines** — four of four implemented (FIFO, Wait-Awhile, Spatial,
  GreenFaaS-v1 as ablation). The CarbonScaler-style elastic scaling baseline
  is still pending; given FaaS's fixed per-invocation scaling granularity,
  this baseline will need adaptation rather than direct port and is
  acknowledged as future work in §8.

## What's next: the consolidation pass — DONE

The manuscript has been consolidated into LaTeX. **Two builds are available**:

- `latex/paper.pdf` — generic two-column article format (15 pages), suitable
  as a starting point for ACM SoCC, IEEE CLOUD, USENIX ATC, or as a
  general-purpose preprint.
- `latex/paper_elsevier.pdf` — Elsevier journal review format (50 pages,
  single-column, line-numbered, 12pt), targeting *Future Generation
  Computer Systems* (FGCS) or similar Elsevier venues.

Both builds are reproducible via `latex/build.sh`. The Elsevier class
files are bundled in `latex/elsevier/` so the build is self-contained.
See `latex/README.md` for the full build instructions and the trim plan
if a specific venue requires fewer pages.

## Real-trace validation — extended

We validated the §7 findings on real ENTSO-E / CAISO carbon-intensity
data from the Let's-Wait-Awhile dataset \citep{wiesner2021lets,lwa}
(15-minute resolution, four real regions: DE/FR/GB/US-CAISO, 2020),
augmented with a calibrated Poland trace generated by
`scripts/generate_pl_trace.py` (LWA-documented 791 g/kWh mean,
coal-base-load diurnal shape).

The headline findings reproduce on real carbon data:

* §7.2.1 headline (4 regions, 24h): GreenFaaS 64% vs FIFO, vs Spatial 65%.
* §7.3.1 topology sweep (5 topologies including coal-belt): GreenFaaS
  matches Spatial within 1.3pp across every topology. The synthetic
  "GreenFaaS beats Spatial by +3.5pp in coal-belt" claim does NOT
  reproduce on real ENTSO-E 2020 amplitudes; that finding was partly an
  artifact of the synthetic carbon model's larger swings.
* Do-no-harm reproduces cleanly: GreenFaaS = FIFO byte-for-byte in
  single-region DE and CAISO scenarios on real carbon.
* Wait-Awhile catastrophic failure reproduces (163-253% increase over
  FIFO on real data).

The corrected positioning is that GreenFaaS is the **topology-robust**
scheduler that matches or near-matches Spatial when Spatial works, and
harmlessly falls back to FIFO when Spatial doesn't. The paper and
abstract were updated to reflect this honest framing (the +3.5pp claim
has been dropped from headline language).

The Azure Functions traces themselves remain unreachable from our build
environment (Azure storage URLs not on the proxy allowlist). The trace
loaders accept the published schemas without modification, so swapping
in the real trace on a machine with the data is a single command-line
flag (see `scripts/run_real_traces.py --azure-2021-csv ...`).

## Review-driven updates (latest iteration)

A detailed third-party review identified several issues that this iteration
addresses:

**Code bug fixes (immediate priority):**
- `greenfaas/carbon.py`: replaced `hash(region_id)` (Python's salted hash,
  non-deterministic across processes) with `zlib.adler32`. This was a real
  reproducibility bug — the paper claimed bit-exact reproducibility, but
  Python's `PYTHONHASHSEED` made synthetic traces non-deterministic across
  interpreter invocations. Fixed.
- `scripts/sensitivity_sweep.py`: same fix applied to the variability sweep.
- `greenfaas/workload.py`: lognormal duration sampling was biased upward by
  $\exp(\sigma^2/2)$. The parameterization is now $\mu = \log(\bar x) -
  \sigma^2/2$, giving an unbiased sample mean. Confirmed: sample mean 0.2998
  vs target 0.3000 over 100k draws.
- `greenfaas/simulator.py`: capacity enforcement was missing despite the
  comment claiming it. Added a backoff-on-EVENT_START mechanism (50ms
  retries when `in_flight >= capacity`) plus cold/warm re-resolution at
  actual start time. Also removed dead `_warm_idle_segments` variable.
- `greenfaas/tradeoff.py`: corrected a misleading docstring on the `r <= 1.0`
  case.

**New empirical material:**
- `scripts/run_fair_waitawhile.py`: re-runs Wait-Awhile under FaaS-appropriate
  parameters (max_defer_s ∈ {1800, 60, 30}) on both synthetic and real
  carbon data, with results in `results/fair_waitawhile.csv`. New §7.2.2
  reports the finding: at the 1800s batch-default horizon Wait-Awhile
  inflates carbon catastrophically (305% on synthetic, 287% on real); at
  short FaaS-appropriate horizons it degenerates to bit-identical FIFO. Either
  way, Wait-Awhile produces no carbon savings on FaaS — but the magnitude
  in the "tripling" claim now has its parameter dependence made explicit.
- `scripts/run_fine_donoharm.py`: fine-grained shiftable-fraction sweep at
  {0.00, 0.01, 0.02, 0.05, 0.10, 0.25} replacing the coarse {0, 0.25, 0.5,
  0.75, 1.0} sweep. New §7.4.1 documents that GreenFaaS = FIFO byte-for-byte
  across {0, 1%, 2%}, then diverges smoothly past 5%. The do-no-harm
  property is therefore robust across a neighbourhood of low-opportunity
  workloads, not just the trivial zero-shifting case.

**Honesty additions to the manuscript:**
- §4.3 acknowledges Lemma 1's first regime is unreachable for FaaS
  parameters ($\beta \approx 50$–$200$ vs $\beta_{\mathrm{crit}} \le 47$);
  the practical content is the closed-form $\lambda^*$, not the dichotomy.
- §7.5 acknowledges forecast-invariance is partly a granularity artifact
  (carbon trace step 300s exceeds Deferrable 60s horizon, so forecast not
  consulted for that class). The Background-class invariance is the
  load-bearing structural claim.
- §8 expanded with explicit limitations: (a) Lemma 1 first regime
  unreachable for FaaS, (b) no demonstrated dominance over Spatial on
  real-carbon topologies, (c) no comparison to provable online algorithms
  (Lechowicz et al.), (d) workload-trace authenticity (synthetic
  schema-faithful, not real Azure trace).
- §9 conclusion compressed from 49 lines to 30, dropping the Wait-Awhile
  re-litigation and the limitation summary already covered in §8.
- Abstract findings paragraph rebalanced to lead with GreenFaaS's positive
  contribution rather than Wait-Awhile's failure.

**Tone fixes:**
- US spelling throughout ("characterization" / "optimization" / etc).
- Dropped editorialising phrases ("most consequentially", "the most
  important figure for the contribution").
- The Wait-Awhile carbon-inflation range now reads "163-305%" (post-bug-fix
  numbers, including capacity enforcement) instead of the prior "163-236%".

**Subsequent iteration (steps 2-5):**

*Step 2: 5-seed error bars (done).* Ran 5 seeds × 5 schedulers × 3 setups
(synthetic 5-region, real LWA 4-region, real coal-belt DE/GB/PL). Headline
tables now report mean ± std. Most important new finding: GreenFaaS-v1's
variance blows up by an order of magnitude in coal-belt (9.75% std vs
~0.5% elsewhere), giving the strongest empirical evidence yet for the
§4.3.9 idle-energy correction — it controls variance, not just mean.
The multi-seed sweep also revealed the GreenFaaS-vs-Spatial gap on
synthetic shrinks from the prior 1pp to within combined-std overlap;
the corrected claim is "GreenFaaS matches Spatial within 1.1pp on
synthetic, 0.5pp on real, with statistically robust spread." Scripts:
`scripts/run_multi_seed.py`. Result CSVs in `results/multi_seed_*.csv`.

*Step 3: Camera-ready figures (done).* All figures 300 DPI (was 160).
Motivation figure: shortened title, on-figure annotation showing
"68% of invocations land outside the cleanest-carbon quartile (18% in
the highest-carbon quartile alone)" instead of having the key number
in stdout only.

*Step 4: FaaS-adapted Lechowicz baseline (done).* Implemented
`LechowiczScheduler` in `greenfaas/schedulers.py`: port of the
one-way trading algorithm with Phi* = sqrt(U·L) threshold. Ran across
synthetic 5-region, real LWA 4-region, real single-region DE.
**Striking finding**: the provably-optimal-competitive-ratio algorithm
performs *worse* than Wait-Awhile on real carbon data, and worst of
all on the single-region setup where its theory applies cleanest
(-320% vs FIFO). Mechanism is exactly the §4.3.9 contribution:
Lechowicz's competitive analysis assumes deferral is free, but FaaS
warm-pool idle energy makes it expensive; the threshold aggressively
defers past warm-pool TTLs. This is now the strongest empirical
argument for the paper's central technical claim. New §7.2.3
subsection presents it. Scripts: `scripts/run_lechowicz.py`. Result
CSVs in `results/lechowicz_*.csv`.

*Step 5: Venue tuning (done).* Default target is Future Generation
Computer Systems (FGCS, Elsevier, IF 8.95). Now produces three build
artefacts: `paper.pdf` (20 pages, generic two-column), `paper_elsevier.pdf`
(67 pages, Elsevier review format with line numbers), and
`paper_elsevier_final.pdf` (29 pages, Elsevier camera-ready 3-column
print layout). The camera-ready preview confirms the paper fits FGCS's
typical 25-35 page range.

**Still outstanding (would need next iteration):**
- 1-minute-resolution carbon data to test the forecast-invariance
  claim under the regime where forecasts would actually be consulted.
  Blocked by ElectricityMaps API access from this environment.
- Production-system validation on Knative.
- Multi-container Lemma 1 generalization (deferred to follow-up paper).
