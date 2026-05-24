# 7. Evaluation

This section presents our experimental evaluation of GreenFaaS against
four carbon-aware baselines drawn from the recent literature. §7.1
describes the trace data and workload-reconstruction methodology that
underlies the experiments. §7.2 reports the headline results on a
canonical workload, framing the rest of the section. §7.3–§7.7 sweep
five sensitivity axes (topology, SLA class mix, forecast accuracy,
carbon-intensity variability, and workload intensity), each chosen to
characterise a specific aspect of the scheduler's behaviour. §7.8
synthesises the cross-axis findings into a single statement of what
GreenFaaS does and does not guarantee.

## 7.1 Real-Trace Methodology

To validate GreenFaaS on production-representative inputs, we drive the
simulator with two public Azure Functions traces and four real grid carbon-
intensity time series.

### Workload traces

**Azure Functions Invocation Trace 2021** (Zhang et al., SOSP 2021).
This is a per-invocation trace covering two weeks starting 2021-01-31, with
schema `(app, func, end_timestamp, duration)`. It is the smaller and more
recent of the two datasets but easier to consume because each row corresponds
to a single invocation. We convert it directly into our `Invocation` stream
by computing `arrival_time = end_timestamp - duration` and mapping
`(app, func)` pairs to stable function identifiers.

**Azure Functions 2019** (Shahrad et al., USENIX ATC 2020). This is the
canonical reference workload used by essentially all prior FaaS
characterization and carbon-aware FaaS work. It is *aggregated* in two ways:
invocations are reported as per-minute counts per function (in
`invocations_per_function_md.anon.dXX.csv`), and execution durations are
given as percentile distributions (in `function_durations_percentiles.anon.dXX.csv`).
We reconstruct a per-invocation stream by drawing arrival times uniformly
within each minute bin and sampling per-invocation durations from the
empirical percentile distribution via linear inverse-CDF interpolation —
a standard reconstruction also used by Roy et al. (CASPER, ICPE'24).

### Latency-class assignment

Neither dataset explicitly labels SLA tiers. We use two complementary
heuristics:

- For the 2019 trace, we map the explicit `Trigger` field to a latency
  class: HTTP triggers → `INTERACTIVE`; queue, event-grid, and orchestration
  triggers → `DEFERRABLE`; timer and storage triggers → `BACKGROUND`. This
  matches the spirit of the Shahrad et al. characterization, in which HTTP
  triggers are overwhelmingly user-facing and timer-triggered functions
  are dominated by periodic batch work.

- For the 2021 trace, which has no trigger field, we classify by observed
  duration: mean < 1 s → `INTERACTIVE` (1 s SLA); 1–30 s → `DEFERRABLE`
  (60 s SLA); > 30 s → `BACKGROUND` (1 hour SLA). The duration-based
  heuristic is a known proxy and is conservative: it can demote some
  short-duration background functions to deferrable, but it does not
  systematically over-promote.

We report sensitivity to the classification thresholds in §7.4.

### Carbon traces

We use the publicly released carbon-intensity traces from Wiesner et al.
(*Let's Wait Awhile*, Middleware 2021), which provide hourly carbon-intensity
values for Germany, Great Britain, France, and California for the full
year 2020 ± 10 days, computed from ENTSO-E (EU) and CAISO (US) generation
mix data using IPCC carbon-intensity factors per source. We extend this with
ElectricityMaps historical data for Poland, Sweden, and India to cover the
high-carbon and clean-grid extremes of our region set. The simulator
resamples all carbon traces to a uniform 5-minute resolution by linear
interpolation; we have verified that finer resolutions (1 min) do not
materially change the results.

### Reproducibility

The trace loaders are implemented in `greenfaas/traces/{azure_2019,azure_2021,
carbon_csv}.py` and consume the published file schemas without modification.
A `scripts/generate_sample_data.py` script generates small synthetic-but-
schema-faithful sample files for end-to-end pipeline validation; these
samples are not used in the headline results, which are computed on the
real traces above.

### Sample characterization

Loading a one-day, 60-function subset of the 2019 trace produces ~20k
invocations with the following composition: 44% deferrable, 30% background,
26% interactive. The composition matches the trigger distribution in the
Shahrad et al. paper (HTTP-triggered functions are roughly a quarter of
all invocations after accounting for popularity weights). The 2021 trace
on a 6-hour, 5,000-invocation slice shows a different composition (46%
interactive, 19% deferrable, 36% background), reflecting both the duration-
based heuristic and the fact that the 2021 trace under-samples the long
tail of low-frequency functions.
