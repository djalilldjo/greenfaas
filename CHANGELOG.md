# Changelog

## v1.3.0 (redesigned GreenFaaS scheduler; exact idle carbon)

Scheduler:

- `GreenFaaSScheduler` is redesigned. It now decides three things from one
  SLA-slack budget: where an invocation runs (lowest-intensity region within
  the tier's RTT budget; for the interactive tier the budget is a share
  `interactive_slack_frac` = 5% of the warm-path slack instead of "home
  only"), whether it queues for a busy container instead of cold-starting
  another (`queue_slack_frac` = 0.5 of the slack, capped at
  `queue_cold_mult` = 3 cold starts), and how long its container stays warm
  (the break-even keep-alive `P_a * tau_c / P_i` for the deferrable and
  background tiers). Carbon-driven deferral keeps its conservative idle
  charge. The scheduler no longer uses an arrival-rate estimator or the
  Lemma 1 routing gate.
- The previous scheduler is kept unchanged as `GreenFaaSSubmittedScheduler`
  (name `GreenFaaS-S`; "GF-Gate" in the paper).
- `WithWarmPoolControl(base)` gives any scheduler's placement the same
  queueing and keep-alive controls (the "+WP" rows of the ablation).
- `tradeoff.break_even_rate` now handles equal intensities (r = 1), where it
  returns `P_i / (P_a * tau_c)`; it returns `None` only for r < 1.

Simulator:

- `ScheduleDecision` has two optional fields, `reuse_wait_s` (default 0) and
  `keep_warm_s` (default: the platform TTL). A request with a queue wait that
  finds no free warm container but a busy one waits and is handed the first
  container to complete, or cold-starts when the wait expires. Schedulers
  that leave the fields at their defaults behave exactly as in v1.2.0.
- Idle carbon is now the integral of the region's intensity over each idle
  interval (`idle_intensity="trace"`), i.e. the idle term of the paper's
  total-carbon equation exactly. `idle_intensity="mean"` restores the v1.2.0
  attribution at the region's mean intensity. The change moves results by a
  fraction of a percent.
- `SystemState` exposes `busy_count` and `queued_count` per (region, function).

Experiments:

- New `scripts/run_ablation.py` (`ablation.csv`, `wp_sensitivity.csv`):
  mechanism ablation with latency and SLA costs, and sensitivity to the
  three parameters.
- GreenCourier is added to the headline, topology, window and sensitivity
  experiments; the former `GreenFaaS-v1` rows are replaced by `GreenFaaS-S`.
- `run_runtime_crossover.py` also reports GreenFaaS without carbon-driven
  deferral; `run_interactive_guard.py` is rewritten around the new scheduler.
- All result files were regenerated. The v1.2.0 files are kept under
  `results/v1.2.0/`.
- 25 unit tests, including hand-computed checks of queueing, keep-alive
  control and time-resolved idle carbon.

Known limitations: idle power and the platform keep-alive are assumed, not
measured; queueing and keep-alive control assume a platform that buffers
requests for a busy container and accepts a per-function keep-alive.

## v1.2.0 (corrected simulator model)

The simulator's physical model changed in three ways. Each has a switch that
restores the previous behaviour, and `scripts/check_legacy_regression.py`
confirms the legacy switches reproduce the v1.1.0 results exactly.

| Aspect | v1.2.0 default | Legacy (up to v1.1.0) |
|---|---|---|
| Warm or cold start | Resolved when the invocation starts: it uses a warm container if one is available (`warm_binding="start"`) | Frozen at decision time through `ScheduleDecision.use_warm` (`"decision"`) |
| Idle energy | All warm-but-idle time is charged, as in the paper's total-carbon equation (`idle_accounting="full"`) | Only containers that expire unused are charged (`"expired_only"`) |
| Container reuse | Most recently used warm container first, so surplus containers expire (`reuse_order="newest"`) | Oldest first (`"oldest"`) |

Why it matters:

- With decision-time binding, a deferred invocation that was scheduled while
  the warm pool was empty cold-started even when a warm container existed at
  its start time, and each such start added a container that idled for the
  full keep-alive. This produced the large carbon inflation previously
  reported for deferring schedulers (Wait-Awhile, Lechowicz, GreenFaaS-v1).
  With start-time binding those schedulers are within a few percent of FIFO.
- With expired-only accounting, the idle time of containers that were later
  reused was not counted. Idle energy is in fact a large share of total
  carbon (about 29% of FIFO on the Azure trace, more on the synthetic
  workloads).
- Schedulers that never defer (FIFO, Spatial, Caribou, GreenCourier,
  GreenFaaS) are unaffected by the binding change; all schedulers are
  affected by the idle accounting.

Other changes:

- All result files under `results/` were regenerated with the v1.2.0 model.
  The v1.1.0 files are kept under `results/legacy_v1.1.0/`.
- New experiment `scripts/run_idle_sensitivity.py` (idle power and keep-alive
  time).
- `scripts/stat_tests.py` now reads `multi_seed_raw.csv`.
- Four new unit tests cover the simulator model.

Known limitations: idle carbon is attributed at each region's mean intensity
(as stated in the paper), and the Azure headline and the idle sensitivity
sweep are single runs.

## v1.1.0

- GreenCourier-style baseline (`GreenCourierScheduler`).
- Experiments: multi-baseline comparison (canonical and long-deadline
  workloads), interactive routing at equal guards, runtime crossover.
- `.zenodo.json`, `CITATION.cff`.
