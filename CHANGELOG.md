# Changelog

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
