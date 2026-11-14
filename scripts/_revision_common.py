"""Shared setup for the TSC-revision experiments (run_multibaseline.py,
run_interactive_guard.py, run_runtime_crossover.py)."""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from greenfaas import (  # noqa: E402
    Region, default_carbon_dir, load_carbon_model_from_dir,
    make_default_function_catalog,
)
from greenfaas.carbon import CarbonModel  # noqa: E402
from greenfaas.core import FunctionSpec, LatencyClass  # noqa: E402

SEEDS = (42, 43, 44)
DURATION = 24 * 3600.0
MULTI = ["FR", "DE", "GB", "US-CAISO", "PL"]

# Inter-region RTT (ms), symmetric.
RTT = {
    ("FR", "DE"): 15, ("FR", "GB"): 12, ("FR", "US-CAISO"): 145, ("FR", "PL"): 30,
    ("DE", "GB"): 20, ("DE", "US-CAISO"): 155, ("DE", "PL"): 15,
    ("GB", "US-CAISO"): 140, ("GB", "PL"): 30, ("US-CAISO", "PL"): 170,
}


def carbon_dir() -> str:
    d = default_carbon_dir()
    return d if os.path.isdir(d) else str(ROOT / d)


def regions_for(ids):
    rtt = {r: {} for r in ids}
    for (a, b), v in RTT.items():
        if a in ids and b in ids:
            rtt[a][b] = float(v)
            rtt[b][a] = float(v)
    return {r: Region(region_id=r, name=r, capacity=400,
                      network_rtt_ms=rtt[r], pue=1.2) for r in ids}


def carbon_for(ids):
    full = load_carbon_model_from_dir(carbon_dir(), step_s=300.0, duration_s=DURATION)
    ids = [r for r in ids if r in full.traces]
    return ids, CarbonModel(traces={r: full.traces[r] for r in ids})


def canonical_catalog():
    """The paper's canonical six-function catalog."""
    return make_default_function_catalog()


def long_deadline_catalog():
    """Stress-test catalog that FAVOURS temporal shifting: eight functions,
    deferrable deadlines of 15-60 min (canonical: 30-120 s) and background
    deadlines of 2-6 h. Used only for the supplement's stress test."""
    L = LatencyClass
    return [
        FunctionSpec("api_auth", 0.05, 0.02, 128, 0.4, 2.5, 0.2, L.INTERACTIVE, 0.5),
        FunctionSpec("api_search", 0.15, 0.08, 256, 0.8, 4.0, 0.3, L.INTERACTIVE, 1.0),
        FunctionSpec("webhook_handler", 0.3, 0.15, 256, 1.0, 4.0, 0.3, L.DEFERRABLE, 900.0),
        FunctionSpec("thumbnail_gen", 1.2, 0.5, 512, 1.5, 7.0, 0.5, L.DEFERRABLE, 1800.0),
        FunctionSpec("media_transcode", 2.0, 0.8, 1024, 1.8, 9.0, 0.6, L.DEFERRABLE, 3600.0),
        FunctionSpec("log_ingest", 0.6, 0.3, 256, 0.8, 4.0, 0.3, L.BACKGROUND, 7200.0),
        FunctionSpec("etl_batch", 1.5, 0.6, 512, 1.2, 7.0, 0.5, L.BACKGROUND, 14400.0),
        FunctionSpec("nightly_report", 2.5, 1.0, 1024, 2.0, 10.0, 0.7, L.BACKGROUND, 21600.0),
    ]
