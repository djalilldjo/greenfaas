"""GreenFaaS: carbon-aware serverless scheduling simulator."""

from .core import (
    ExecutionRecord,
    FunctionSpec,
    Invocation,
    LatencyClass,
    Region,
    ScheduleDecision,
)
from .carbon import (
    CarbonModel,
    CarbonTrace,
    REGION_BASELINE,
    REGION_AMPLITUDE,
    synthetic_diurnal_trace,
)
from .workload import generate_workload, make_default_function_catalog
from .schedulers import (
    FifoScheduler,
    WaitAwhileScheduler,
    LechowiczScheduler,
    CaribouScheduler,
    SpatialScheduler,
    GreenFaaSScheduler,
    GreenFaaSV1Scheduler,
    ArrivalRateTracker,
    SystemState,
    Scheduler,
)
from .simulator import Simulator, SimulationResult
from .tradeoff import (
    TradeoffParams,
    beta_crit,
    break_even_rate,
    prefer_warm_in_L,
    per_invocation_carbon,
)
from .traces import (
    load_azure_2021_invocations,
    load_azure_2019_function_durations,
    load_azure_2019_invocation_counts,
    sample_invocations_from_2019,
    load_carbon_csv,
    load_carbon_model_from_dir,
)

__all__ = [
    "ArrivalRateTracker",
    "CarbonModel",
    "CarbonTrace",
    "ExecutionRecord",
    "FifoScheduler",
    "FunctionSpec",
    "GreenFaaSScheduler",
    "GreenFaaSV1Scheduler",
    "Invocation",
    "LatencyClass",
    "LechowiczScheduler",
    "CaribouScheduler",
    "REGION_AMPLITUDE",
    "REGION_BASELINE",
    "Region",
    "ScheduleDecision",
    "Scheduler",
    "SimulationResult",
    "Simulator",
    "SpatialScheduler",
    "SystemState",
    "TradeoffParams",
    "WaitAwhileScheduler",
    "beta_crit",
    "break_even_rate",
    "generate_workload",
    "make_default_function_catalog",
    "per_invocation_carbon",
    "prefer_warm_in_L",
    "synthetic_diurnal_trace",
]


def default_carbon_dir():
    """Return the carbon-data directory, honouring GREENFAAS_CARBON_DIR env var.

    The default is `real_data/carbon` relative to the project root. To run
    experiments with alternative carbon data (e.g., real ElectricityMaps
    fetches in `real_data/carbon_em`), set:

        export GREENFAAS_CARBON_DIR=real_data/carbon_em

    before running any scripts.
    """
    import os
    return os.environ.get("GREENFAAS_CARBON_DIR", "real_data/carbon")
