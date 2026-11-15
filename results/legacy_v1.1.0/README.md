# Legacy results (simulator up to v1.1.0)

These are the result files as produced by the simulator up to release v1.1.0,
kept so the originally submitted manuscript's numbers remain reproducible and
comparable. They were generated with what is now the legacy model:

    Simulator(..., warm_binding="decision",
                   idle_accounting="expired_only",
                   reuse_order="oldest")

The files in the parent `results/` directory were produced with the corrected
v1.2.0 defaults. See `CHANGELOG.md` for what changed and why.
`python scripts/check_legacy_regression.py` confirms the legacy switches
still reproduce these values.
