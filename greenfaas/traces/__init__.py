"""
greenfaas.traces
================

Loaders for real public traces used in the GreenFaaS evaluation:

  * azure_2021.py    Azure Functions Invocation Trace 2021 (per-invocation)
  * azure_2019.py    Azure Functions 2019 dataset (aggregated minute-counts +
                     duration percentiles; per-invocation arrivals are
                     reconstructed via thinning)
  * carbon_csv.py    Hourly carbon-intensity CSVs in the Let's-Wait-Awhile /
                     ElectricityMaps schema (timestamp, gco2_per_kwh).

Each loader returns the same data types the synthetic generators produce
(`List[Invocation]`, `CarbonModel`), so the simulator and schedulers consume
them without modification.
"""

from .azure_2021 import load_azure_2021_invocations
from .azure_2019 import (
    load_azure_2019_function_durations,
    load_azure_2019_invocation_counts,
    sample_invocations_from_2019,
)
from .carbon_csv import load_carbon_csv, load_carbon_model_from_dir

__all__ = [
    "load_azure_2021_invocations",
    "load_azure_2019_function_durations",
    "load_azure_2019_invocation_counts",
    "sample_invocations_from_2019",
    "load_carbon_csv",
    "load_carbon_model_from_dir",
]
