"""
greenfaas.carbon
================

Carbon intensity model. Provides grid carbon-intensity (g CO2eq / kWh) as a
function of (region, time), plus forecasts of varying accuracy.

For the first iteration of the project we generate synthetic-but-realistic
diurnal traces parameterised by published regional averages (e.g. France ~60,
Germany ~350, Poland ~700). The interface is structured so that real
ElectricityMaps CSVs can be dropped in via `from_csv` without changing
scheduler code.
"""
from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass
from typing import Dict, List, Optional


# Approximate annual-mean carbon intensities (g CO2eq / kWh) from public
# ElectricityMaps and IEA data. Used here to calibrate synthetic traces.
REGION_BASELINE: Dict[str, float] = {
    "FR":      60.0,    # France, mostly nuclear
    "SE":      30.0,    # Sweden, hydro + nuclear
    "CA-QC":   30.0,    # Quebec, hydro
    "DE":     350.0,    # Germany, mixed
    "GB":     220.0,    # United Kingdom, mixed
    "US-CAISO": 250.0,  # California
    "PL":     700.0,    # Poland, coal-heavy
    "IN":     650.0,    # India, coal-heavy
    "US-MISO": 450.0,   # US Midwest
}

# Amplitude of the diurnal swing as a fraction of the baseline. Renewable-
# dominated grids show larger relative swings (solar/wind volatility); fossil-
# dominated grids are flatter.
REGION_AMPLITUDE: Dict[str, float] = {
    "FR":      0.15,
    "SE":      0.10,
    "CA-QC":   0.08,
    "DE":      0.40,
    "GB":      0.35,
    "US-CAISO": 0.55,
    "PL":      0.15,
    "IN":      0.25,
    "US-MISO": 0.30,
}


@dataclass
class CarbonTrace:
    """A discrete carbon-intensity time series for one region.

    Values are sampled at a fixed step (default 5 min). Lookup is by linear
    interpolation; out-of-range queries clamp to the boundary.
    """

    region_id: str
    step_s: float
    values: List[float]  # g CO2eq / kWh

    def intensity(self, t: float) -> float:
        if t <= 0:
            return self.values[0]
        idx = t / self.step_s
        i0 = int(math.floor(idx))
        if i0 >= len(self.values) - 1:
            return self.values[-1]
        frac = idx - i0
        return self.values[i0] * (1.0 - frac) + self.values[i0 + 1] * frac

    def forecast(self, t: float, horizon_s: float, accuracy: str = "perfect") -> List[float]:
        """Return a forecast of intensities over [t, t + horizon_s].

        accuracy:
          'perfect' - returns the true trace.
          '1h'      - perfect within 1h, decaying noise beyond.
          '24h'     - perfect within 24h, decaying noise beyond.
          'none'    - returns a constant equal to the historical mean.
        """
        n_steps = max(1, int(horizon_s / self.step_s))
        truth = [self.intensity(t + i * self.step_s) for i in range(n_steps)]
        if accuracy == "perfect":
            return truth
        if accuracy == "none":
            mean = sum(self.values) / len(self.values)
            return [mean] * n_steps
        cutoff_s = 3600.0 if accuracy == "1h" else 86400.0
        noisy = []
        # Use zlib.adler32 for deterministic hashing across interpreter runs.
        # Python's built-in hash() is salted (PYTHONHASHSEED) and therefore
        # differs between processes, which breaks bit-exact reproducibility.
        region_hash = zlib.adler32(self.region_id.encode("utf-8"))
        rng = random.Random(int(t * 1000) ^ region_hash)
        for i, v in enumerate(truth):
            elapsed = i * self.step_s
            if elapsed <= cutoff_s:
                noisy.append(v)
            else:
                # noise scales linearly with hours past the horizon, capped
                hours_past = (elapsed - cutoff_s) / 3600.0
                sigma = min(0.4, 0.05 * hours_past) * v
                noisy.append(max(1.0, v + rng.gauss(0.0, sigma)))
        return noisy


def synthetic_diurnal_trace(
    region_id: str,
    duration_s: float,
    step_s: float = 300.0,
    seed: int = 0,
) -> CarbonTrace:
    """Generate a synthetic 24-hour-periodic carbon trace for a region.

    Model: base * (1 + amp * sin(2 pi (t - phase) / 86400)) + Gaussian noise.
    Phase is region-dependent so regions are not perfectly correlated.
    """
    base = REGION_BASELINE.get(region_id, 300.0)
    amp = REGION_AMPLITUDE.get(region_id, 0.25)
    # Use zlib.adler32 for deterministic region-hashing across interpreter
    # runs (Python's built-in hash() is salted by PYTHONHASHSEED).
    region_hash = zlib.adler32(region_id.encode("utf-8"))
    # phase shift by longitude proxy (just deterministic from region_id)
    phase = region_hash % 86400
    rng = random.Random(seed ^ region_hash)
    n = int(duration_s / step_s) + 1
    values = []
    for i in range(n):
        t = i * step_s
        # primary 24h cycle, plus a weak 7-day modulation, plus noise
        diurnal = math.sin(2 * math.pi * (t - phase) / 86400.0)
        weekly = 0.05 * math.sin(2 * math.pi * t / (7 * 86400.0))
        v = base * (1.0 + amp * diurnal + weekly)
        v += rng.gauss(0.0, 0.03 * base)
        values.append(max(5.0, v))
    return CarbonTrace(region_id=region_id, step_s=step_s, values=values)


class CarbonModel:
    """Aggregate carbon model spanning many regions."""

    def __init__(self, traces: Dict[str, CarbonTrace]):
        self.traces = traces

    @classmethod
    def synthetic(
        cls, region_ids: List[str], duration_s: float, step_s: float = 300.0, seed: int = 0
    ) -> "CarbonModel":
        return cls(
            traces={
                r: synthetic_diurnal_trace(r, duration_s, step_s, seed) for r in region_ids
            }
        )

    def intensity(self, region_id: str, t: float) -> float:
        return self.traces[region_id].intensity(t)

    def forecast(self, region_id: str, t: float, horizon_s: float, accuracy: str = "perfect") -> List[float]:
        return self.traces[region_id].forecast(t, horizon_s, accuracy)

    def regions(self) -> List[str]:
        return list(self.traces.keys())
