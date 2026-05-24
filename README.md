# GreenFaaS — Carbon-Aware Serverless Scheduling

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20370236.svg)](https://doi.org/10.5281/zenodo.20370236)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Reference implementation and discrete-event simulator for **GreenFaaS**, a
carbon-aware scheduling framework designed natively for Function-as-a-Service
(FaaS) workloads. GreenFaaS unifies spatial routing, temporal deferral, and
warm-pool-aware container reuse under a single cost model, with an SLA-tiered
policy and an analytical cold-start carbon trade-off gate.

This repository is the **code and reproducibility artifact** for the
accompanying research paper. It contains the simulator, the scheduler
implementations spanning the comparison set, the carbon/workload trace
loaders, the statistical-test and figure-generation scripts, and a
multi-scenario evaluation harness.

## Repository layout

```
greenfaas/            core library
├── core.py             regions, functions, invocations, decisions
├── carbon.py           carbon-intensity models (synthetic + real-trace loaders)
├── workload.py         synthetic workload generator (Poisson/diurnal/Zipf)
├── tradeoff.py         the cold-start carbon trade-off lemma (Lemma 1)
├── schedulers.py       FIFO, Spatial, Wait-Awhile, Lechowicz, Caribou, GreenFaaS
├── simulator.py        discrete-event simulator with capacity + warm-pool model
└── traces/             Azure 2019/2021 + carbon CSV loaders

scripts/              experiment runners, figures, tests
├── test_core.py             unit tests (14)
├── verify_tradeoff.py       numerical verification of Lemma 1
├── verify_theorem1.py       Variant S/P theory diagnostic
├── scenario_sweep.py        synthetic topology sweep
├── run_real_carbon.py       real ENTSO-E/CAISO carbon experiments
├── run_real_workload*.py    real Azure 2021 trace experiments
├── run_caribou_comparison.py    Caribou (SOSP'24) baseline comparison
├── stat_tests.py            paired t-test / Wilcoxon
├── motivation_figure.py     Figure 1 (arrivals vs carbon)
└── ... (additional runners)

real_data/            real carbon traces (ENTSO-E/CAISO 2020, EM Jan 2021)
sample_data/          small sample workload traces
figures/              generated figures
results/              generated sensitivity-sweep CSVs
run-all.sh            end-to-end reproduction driver
```

## Quickstart

```bash
# (Optional) create a virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install numpy scipy matplotlib

# Run the unit tests
python scripts/test_core.py

# Verify the cold-start carbon trade-off lemma numerically
python scripts/verify_tradeoff.py

# Reproduce the synthetic topology sweep
python scripts/scenario_sweep.py
```

## Datasets

The real carbon traces (ENTSO-E / CAISO 2020 and ElectricityMaps January 2021)
are included under `real_data/`. The large **Azure Functions Invocation Trace
2021** is **not** redistributed here; download it from the Microsoft Azure
Public Dataset (https://github.com/Azure/AzurePublicDataset) and place it in
`real_data/azure_2021/`. See `REAL_DATA_GUIDE.md` for full instructions and the
exact commands to reproduce each experiment.

## Reproducibility

Every numerical result in the paper is reproducible from the scripts in this
repository. The table-generating scripts (`scripts/run_*.py`,
`scripts/scenario_sweep.py`) emit the exact percentages quoted in the
manuscript; random seeds are fixed and documented in each script.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
