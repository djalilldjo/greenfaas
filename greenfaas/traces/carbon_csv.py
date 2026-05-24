"""
greenfaas.traces.carbon_csv
===========================

Loader for hourly carbon-intensity CSVs. Accepts the standard schema used by:

  * Let's-Wait-Awhile (`{REGION}_2020.csv`):
        timestamp, gco2_per_kwh
    where `timestamp` is ISO-8601 with hourly granularity.

  * ElectricityMaps historical exports (hourly):
        Datetime (UTC), Carbon Intensity gCO₂eq/kWh (LCA), ...
    we map `Datetime (UTC) -> timestamp` and the LCA column -> `gco2_per_kwh`.

The output is a `CarbonTrace` with a configurable step size (default 5 min,
linearly interpolated from the source's hourly values to match the simulator).
"""
from __future__ import annotations

import csv
import datetime as dt
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..carbon import CarbonModel, CarbonTrace


def _parse_timestamp(s: str) -> dt.datetime:
    """Parse an ISO-8601-ish timestamp; tolerates 'Z' suffix and missing TZ."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        # Common alternate format used by some ElectricityMaps exports.
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
            try:
                return dt.datetime.strptime(s, fmt)
            except ValueError:
                continue
    raise ValueError(f"Could not parse timestamp: {s!r}")


def _detect_columns(fieldnames: List[str]) -> Tuple[str, str]:
    """Return (timestamp_col, intensity_col), matching common schemas."""
    ts_col = None
    ci_col = None
    lower = {f.lower(): f for f in fieldnames}
    for cand in ("timestamp", "datetime (utc)", "datetime", "time", "date"):
        if cand in lower:
            ts_col = lower[cand]
            break
    for f in fieldnames:
        fl = f.lower()
        if "carbon" in fl and ("intensity" in fl or "gco2" in fl):
            ci_col = f
            break
    if ci_col is None and "gco2_per_kwh" in lower:
        ci_col = lower["gco2_per_kwh"]
    if ts_col is None or ci_col is None:
        raise ValueError(
            f"Could not find timestamp / carbon-intensity columns in {fieldnames}. "
            "Expected timestamp + gco2_per_kwh (Let's-Wait-Awhile) or "
            "Datetime + Carbon Intensity gCO\u2082eq/kWh (ElectricityMaps)."
        )
    return ts_col, ci_col


def load_carbon_csv(
    path: str,
    region_id: str,
    step_s: float = 300.0,
    duration_s: Optional[float] = None,
    anchor_first_row: bool = True,
) -> CarbonTrace:
    """Load an hourly carbon-intensity CSV and resample to step_s.

    Parameters
    ----------
    path             : CSV file path.
    region_id        : region identifier to attach to the returned CarbonTrace.
    step_s           : output resolution (default 5 min, matching the simulator).
    duration_s       : optionally truncate to this many seconds from the start.
    anchor_first_row : if True, the first timestamp anchors t=0; otherwise,
                       the first row's UTC timestamp anchors t=0.

    Returns
    -------
    CarbonTrace with `step_s` and an interpolated value list.
    """
    rows: List[Tuple[dt.datetime, float]] = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        ts_col, ci_col = _detect_columns(reader.fieldnames or [])
        for row in reader:
            try:
                ts = _parse_timestamp(row[ts_col])
                ci = float(row[ci_col])
            except (ValueError, KeyError):
                continue  # skip malformed rows
            rows.append((ts, ci))
    if not rows:
        raise ValueError(f"No usable rows found in {path}")
    rows.sort()

    t0 = rows[0][0]
    raw_seconds: List[float] = []
    raw_ci: List[float] = []
    for ts, ci in rows:
        raw_seconds.append((ts - t0).total_seconds())
        raw_ci.append(ci)

    if duration_s is None:
        duration_s = raw_seconds[-1]

    # Resample to fixed step via linear interpolation.
    n = int(duration_s / step_s) + 1
    values: List[float] = []
    j = 0
    for i in range(n):
        t = i * step_s
        while j + 1 < len(raw_seconds) and raw_seconds[j + 1] < t:
            j += 1
        if j + 1 >= len(raw_seconds):
            values.append(raw_ci[-1])
            continue
        t0_, t1_ = raw_seconds[j], raw_seconds[j + 1]
        v0_, v1_ = raw_ci[j], raw_ci[j + 1]
        if t1_ == t0_:
            values.append(v0_)
        else:
            frac = (t - t0_) / (t1_ - t0_)
            values.append(v0_ * (1.0 - frac) + v1_ * frac)
    return CarbonTrace(region_id=region_id, step_s=step_s, values=values)


# Mapping from filename stem to region_id. Add new aliases here as needed.
DEFAULT_FILENAME_MAP: Dict[str, str] = {
    "DE":      "DE",     "DE_2020":   "DE",     "germany":    "DE",
    "GB":      "GB",     "GB_2020":   "GB",     "uk":         "GB",
    "FR":      "FR",     "FR_2020":   "FR",     "france":     "FR",
    "CA":      "CA-QC",  "CA_2020":   "CA-QC",  "quebec":     "CA-QC",
    "CAISO":   "US-CAISO", "CAISO_2020": "US-CAISO", "california": "US-CAISO",
    "PL":      "PL",     "PL_2020":   "PL",     "poland":     "PL",
    "SE":      "SE",     "SE_2020":   "SE",     "sweden":     "SE",
    "IN":      "IN",     "IN_2020":   "IN",     "india":      "IN",
    "MISO":    "US-MISO", "MISO_2020": "US-MISO",
}


def load_carbon_model_from_dir(
    directory: str,
    step_s: float = 300.0,
    duration_s: Optional[float] = None,
    filename_map: Optional[Dict[str, str]] = None,
) -> CarbonModel:
    """Load every *.csv in a directory as a CarbonTrace and assemble a CarbonModel.

    Filenames are mapped to region_ids via DEFAULT_FILENAME_MAP (extendable via
    `filename_map`). Files that don't match any known region are loaded with
    region_id = filename stem.
    """
    mapping = dict(DEFAULT_FILENAME_MAP)
    if filename_map:
        mapping.update(filename_map)

    traces: Dict[str, CarbonTrace] = {}
    for path in sorted(Path(directory).glob("*.csv")):
        stem = path.stem
        region_id = mapping.get(stem, stem)
        trace = load_carbon_csv(str(path), region_id, step_s=step_s, duration_s=duration_s)
        traces[region_id] = trace
    if not traces:
        raise ValueError(f"No CSV files found in {directory}")
    return CarbonModel(traces=traces)
