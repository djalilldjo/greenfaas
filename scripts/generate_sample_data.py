"""
Generate small, schema-faithful sample files for Azure 2019, Azure 2021,
and Let's-Wait-Awhile carbon traces.

These samples let the loaders be exercised end-to-end without downloading
the real (multi-GB) datasets. The schemas match the real files exactly, so
replacing the sample files with real ones requires zero code changes.

Outputs (created under sample_data/):
  azure_2021/AzureFunctionsInvocationTraceSample.csv    (~5000 invocations)
  azure_2019/invocations_per_function_md.anon.d01.csv   (~50 functions)
  azure_2019/function_durations_percentiles.anon.d01.csv
  carbon/DE_2020.csv  GB_2020.csv  FR_2020.csv  CAISO_2020.csv  PL_2020.csv
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "sample_data"

# Power-law function popularity matching the Shahrad et al. characterization.
# A handful of "hot" functions dominate invocations.
N_FUNCTIONS = 60
ZIPF_S = 1.2

# Day of simulated data per Azure 2019 file.
MINUTES_PER_DAY = 1440

# Region mapping for round-robin assignment.
REGION_CARBON_BASELINES = {
    "DE":       350.0,
    "GB":       220.0,
    "FR":        60.0,
    "CAISO":    250.0,
    "PL":       700.0,
}
REGION_AMPLITUDES = {
    "DE":       0.40,
    "GB":       0.35,
    "FR":       0.15,
    "CAISO":    0.55,
    "PL":       0.15,
}


def _hex_id(s: str, length: int = 64) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]


def _diurnal_factor(minute_idx: int) -> float:
    """Multiplier in [0.25, 1.75] modelling business-hour load."""
    hour = (minute_idx / 60.0) % 24.0
    return 1.0 + 0.75 * math.sin(2 * math.pi * (hour - 8.0) / 24.0)


# ---------------------------------------------------------------------------
# Azure 2019: invocations_per_function_md + function_durations_percentiles
# ---------------------------------------------------------------------------

TRIGGERS = ["http", "queue", "event", "timer", "orchestration", "storage", "others"]
TRIGGER_WEIGHTS = [0.45, 0.20, 0.12, 0.10, 0.05, 0.05, 0.03]


def write_azure_2019_sample(out_dir: Path, day_index: int = 1, seed: int = 0):
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    # Build function catalog: HashOwner, HashApp, HashFunction, Trigger,
    # per-function (mean_ms, percentile shape).
    fn_records = []
    weights = [1.0 / (i + 1) ** ZIPF_S for i in range(N_FUNCTIONS)]
    total_w = sum(weights)
    # Average invocations per day at the head of the distribution.
    head_rate_per_day = 6000
    for i in range(N_FUNCTIONS):
        owner = _hex_id(f"owner-{i // 5}")
        app = _hex_id(f"app-{i}")
        func = _hex_id(f"func-{i}-{rng.random():.6f}")
        trigger = rng.choices(TRIGGERS, weights=TRIGGER_WEIGHTS, k=1)[0]
        if trigger == "http":
            mean_ms = rng.choice([50, 100, 200, 400, 800])
        elif trigger in ("queue", "event", "orchestration", "others"):
            mean_ms = rng.choice([200, 500, 1200, 2500, 5000])
        else:  # timer, storage -> background
            mean_ms = rng.choice([1500, 5000, 15000, 60000])
        # Plausible percentile distribution: log-normal-ish shape around mean.
        sigma = 0.6
        pcts = {
            "p0":   max(1.0, mean_ms * math.exp(-3 * sigma)),
            "p1":   max(1.0, mean_ms * math.exp(-2 * sigma)),
            "p25":  max(1.0, mean_ms * math.exp(-0.7 * sigma)),
            "p50":  mean_ms,
            "p75":  mean_ms * math.exp(0.7 * sigma),
            "p99":  mean_ms * math.exp(2 * sigma),
            "p100": mean_ms * math.exp(3 * sigma),
        }
        invs_per_day = int(round(head_rate_per_day * weights[i] / weights[0]))
        fn_records.append({
            "HashOwner": owner, "HashApp": app, "HashFunction": func,
            "Trigger": trigger,
            "mean_ms": mean_ms, "pcts": pcts,
            "invs_per_day": invs_per_day,
        })

    # ---- write invocations_per_function_md.anon.dXX.csv
    inv_path = out_dir / f"invocations_per_function_md.anon.d{day_index:02d}.csv"
    with open(inv_path, "w", newline="") as f:
        w = csv.writer(f)
        header = ["HashOwner", "HashApp", "HashFunction", "Trigger"] + [str(i) for i in range(1, MINUTES_PER_DAY + 1)]
        w.writerow(header)
        for rec in fn_records:
            # Distribute invs_per_day across minutes following diurnal envelope.
            envelope = [_diurnal_factor(m) for m in range(MINUTES_PER_DAY)]
            env_sum = sum(envelope)
            counts = [0] * MINUTES_PER_DAY
            remaining = rec["invs_per_day"]
            for m in range(MINUTES_PER_DAY):
                expected = rec["invs_per_day"] * envelope[m] / env_sum
                # Poisson-ish round.
                n = int(expected) + (1 if rng.random() < (expected - int(expected)) else 0)
                counts[m] = n
                remaining -= n
            # Distribute residual at random minutes.
            while remaining > 0:
                counts[rng.randrange(MINUTES_PER_DAY)] += 1
                remaining -= 1
            row = [rec["HashOwner"], rec["HashApp"], rec["HashFunction"], rec["Trigger"]] + counts
            w.writerow(row)

    # ---- write function_durations_percentiles.anon.dXX.csv
    dur_path = out_dir / f"function_durations_percentiles.anon.d{day_index:02d}.csv"
    with open(dur_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "HashOwner", "HashApp", "HashFunction",
            "Average", "Count", "Minimum", "Maximum",
            "percentile_Average_0", "percentile_Average_1",
            "percentile_Average_25", "percentile_Average_50",
            "percentile_Average_75", "percentile_Average_99",
            "percentile_Average_100",
        ])
        for rec in fn_records:
            p = rec["pcts"]
            w.writerow([
                rec["HashOwner"], rec["HashApp"], rec["HashFunction"],
                f"{rec['mean_ms']:.3f}", rec["invs_per_day"],
                f"{p['p0']:.3f}", f"{p['p100']:.3f}",
                f"{p['p0']:.3f}", f"{p['p1']:.3f}", f"{p['p25']:.3f}",
                f"{p['p50']:.3f}", f"{p['p75']:.3f}", f"{p['p99']:.3f}",
                f"{p['p100']:.3f}",
            ])

    return inv_path, dur_path


# ---------------------------------------------------------------------------
# Azure 2021: per-invocation trace (app, func, end_timestamp, duration)
# ---------------------------------------------------------------------------

def write_azure_2021_sample(out_dir: Path, n_invocations: int = 5000, seed: int = 1):
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    # 20 apps, each with 1-3 functions.
    apps = [_hex_id(f"app2021-{i}") for i in range(20)]
    funcs_per_app = {a: [_hex_id(f"{a}-fn-{j}") for j in range(rng.randint(1, 3))]
                     for a in apps}
    flat = [(a, fn) for a in apps for fn in funcs_per_app[a]]
    fn_means_s = {(a, fn): rng.choice([0.05, 0.2, 0.8, 3.0, 15.0, 60.0]) for a, fn in flat}

    rows = []
    # Spread arrivals over 6 hours of simulated wall-clock.
    horizon_s = 6 * 3600.0
    for i in range(n_invocations):
        a, fn = rng.choices(flat, weights=[1.0 / (i + 1) ** 1.1 for i in range(len(flat))], k=1)[0]
        arrival = rng.random() * horizon_s
        mean = fn_means_s[(a, fn)]
        duration = max(0.005, rng.lognormvariate(mu=math.log(mean), sigma=0.6))
        end_ts = arrival + duration
        rows.append((a, fn, end_ts, duration))
    rows.sort(key=lambda r: r[2])  # sorted by end_timestamp (as in real data)

    path = out_dir / "AzureFunctionsInvocationTraceSample.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["app", "func", "end_timestamp", "duration"])
        for a, fn, e, d in rows:
            w.writerow([a, fn, f"{e:.6f}", f"{d:.3f}"])
    return path


# ---------------------------------------------------------------------------
# Carbon: hourly CSVs in the Let's-Wait-Awhile schema.
# ---------------------------------------------------------------------------

def write_carbon_csv(out_dir: Path, region: str, year: int = 2020,
                     n_days: int = 14, seed: int = 0):
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed ^ hash(region))
    base = REGION_CARBON_BASELINES[region]
    amp = REGION_AMPLITUDES[region]
    start = dt.datetime(year, 1, 1, 0, 0, 0)
    rows = []
    for h in range(n_days * 24):
        ts = start + dt.timedelta(hours=h)
        hour = ts.hour
        diurnal = math.sin(2 * math.pi * (hour - 14) / 24.0)
        v = base * (1.0 + amp * diurnal) + rng.gauss(0, 0.05 * base)
        rows.append((ts.isoformat(), max(5.0, v)))
    path = out_dir / f"{region}_2020.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "gco2_per_kwh"])
        for ts, v in rows:
            w.writerow([ts, f"{v:.2f}"])
    return path


# ---------------------------------------------------------------------------

def main():
    print("Generating Azure 2021 sample...")
    p = write_azure_2021_sample(ROOT / "azure_2021")
    print(f"  wrote {p}")

    print("Generating Azure 2019 sample (1 day)...")
    inv, dur = write_azure_2019_sample(ROOT / "azure_2019", day_index=1)
    print(f"  wrote {inv}")
    print(f"  wrote {dur}")

    print("Generating carbon CSVs...")
    for region in REGION_CARBON_BASELINES:
        p = write_carbon_csv(ROOT / "carbon", region)
        print(f"  wrote {p}")

    print("\nSample data ready. Run scripts/run_real_traces.py to consume it.")


if __name__ == "__main__":
    main()
