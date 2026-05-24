"""
Generate a high-fidelity Azure Functions 2019 trace calibrated to the
published statistics in Shahrad et al. (USENIX ATC 2020).

This goes substantially beyond the sample-data generator in
scripts/generate_sample_data.py. It is calibrated to:

  - Trigger distribution by function COUNT (Figure 2 of Shahrad et al.):
        HTTP: 53%, Timer: ~16%, Queue: ~16%, Event: ~2.2%,
        Orchestration: ~4%, Storage: ~8%, Others: ~0.8%
  - Trigger distribution by INVOCATION (Figure 2):
        HTTP: 35%, Event: 24.7%, Queue: 20.3%, Timer: 2%,
        Orchestration: 14%, Storage: ~4%
    (Event triggers have very high invocations-per-function; timers have
    very low invocations-per-function.)
  - Function popularity: heavy-tailed, with ~50% of functions invoked at
    most once per hour and the top 1% of functions accounting for the
    vast majority of invocations.
  - Duration distribution: 50% of functions average <1s, 96% <60s.
  - Application size: 54% have 1 function, 95% have <=10 functions.

The output is in the *exact* Azure 2019 schema, so the existing trace
loader in greenfaas.traces.azure_2019 consumes it without modification.

Calibration source values are documented inline. Where Shahrad et al.
report a CDF rather than a parametric distribution, we fit a log-normal
or Pareto with parameters tuned to match the documented quantiles.
"""
from __future__ import annotations

import csv
import hashlib
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "sample_data" / "azure_2019_high_fidelity"

# Published trigger distributions from Shahrad et al. Figure 2.
# (trigger, fraction_of_functions, mean_invocations_per_function_per_day)
TRIGGERS = [
    ("http",          0.53,   100.0),   # 53% of functions, moderate invocations
    ("timer",         0.16,    15.0),   # many functions, few invocations
    ("queue",         0.16,   400.0),
    ("event",         0.022, 3500.0),   # 2.2% of functions, 24.7% of invocations
    ("orchestration", 0.04,  1100.0),
    ("storage",       0.08,   150.0),
    ("others",        0.008,  500.0),
]

# Duration mean (ms) sampled by trigger from approximately log-normal,
# matching the CDF reported in Shahrad Figure 3.
DURATION_PARAMS = {
    # (mu_log, sigma_log)  for log-normal of the AVERAGE duration in ms
    "http":          (math.log(150),  1.2),    # most <1s
    "timer":         (math.log(3000), 1.5),    # often long; backups/cleanups
    "queue":         (math.log(400),  1.3),
    "event":         (math.log(80),   1.0),    # fast, message-driven
    "orchestration": (math.log(2000), 1.4),
    "storage":       (math.log(500),  1.3),
    "others":        (math.log(300),  1.4),
}


def _hex_id(s: str, length: int = 64) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]


def _diurnal_factor(minute_idx: int, peak_hour: float = 14.0,
                    amplitude: float = 0.75) -> float:
    """Multiplier in roughly [1-amplitude, 1+amplitude]."""
    hour = (minute_idx / 60.0) % 24.0
    # Sinusoidal envelope peaking at peak_hour (UTC).
    return 1.0 + amplitude * math.sin(2 * math.pi * (hour - (peak_hour - 6.0)) / 24.0)


def _app_size_sample(rng: random.Random) -> int:
    """Sample app size matching Shahrad Figure 1 CDF."""
    u = rng.random()
    if u < 0.54: return 1
    if u < 0.75: return 2
    if u < 0.90: return rng.choice([3, 4])
    if u < 0.95: return rng.choice([5, 6, 7, 8, 9, 10])
    if u < 0.998: return rng.randint(11, 50)
    return rng.randint(51, 150)


def _sample_invocations_per_day(trigger: str, rng: random.Random,
                                mean: float) -> int:
    """Sample daily invocation count for a function with this trigger.

    Distribution is heavy-tailed (Pareto-like) so a few functions dominate.
    Returns 0 for the long tail of cold functions (~50% of all functions
    are invoked at most once per hour i.e. <=24/day).
    """
    # Pareto with shape 1.2 gives a long right tail; clip to a sensible max.
    alpha = 1.2
    raw = rng.paretovariate(alpha)
    # Calibrate so the mean over the population is `mean` invocations/day.
    scale = mean / (alpha / (alpha - 1))   # E[Pareto] = alpha/(alpha-1)
    sampled = scale * (raw - 1.0)
    # Many functions are cold (45% of apps invoked at most once per hour):
    if rng.random() < 0.45:
        sampled *= rng.random() * 0.05  # squash to near zero
    return max(0, int(sampled))


def generate_high_fidelity_2019(
    n_apps: int,
    day_index: int = 1,
    out_dir: Path = ROOT,
    seed: int = 42,
) -> tuple[int, int]:
    """Generate one day of Azure 2019 trace files.

    Returns (n_functions, n_total_invocations).
    """
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ----- Build function catalog ---------------------------------------- #
    fn_records = []
    for app_idx in range(n_apps):
        owner = _hex_id(f"owner-{app_idx // 7}-{seed}")
        app = _hex_id(f"app-{app_idx}-{seed}")
        # Pick a primary trigger for the app via weighted choice
        weights = [t[1] for t in TRIGGERS]
        primary_trigger = rng.choices([t[0] for t in TRIGGERS], weights=weights, k=1)[0]
        app_size = _app_size_sample(rng)

        for fn_idx in range(app_size):
            # 70% of functions in an app share its primary trigger;
            # the rest are drawn fresh from the trigger distribution.
            if fn_idx == 0 or rng.random() < 0.7:
                trigger = primary_trigger
            else:
                trigger = rng.choices([t[0] for t in TRIGGERS], weights=weights, k=1)[0]
            func = _hex_id(f"func-{app_idx}-{fn_idx}-{seed}-{rng.random():.6f}")

            mu_log, sigma_log = DURATION_PARAMS[trigger]
            mean_ms = max(1.0, rng.lognormvariate(mu_log, sigma_log))

            # Build percentile distribution around the mean.
            sigma = 0.5 + 0.5 * rng.random()
            pcts = {
                "p0":   max(1.0, mean_ms * math.exp(-3 * sigma)),
                "p1":   max(1.0, mean_ms * math.exp(-2 * sigma)),
                "p25":  max(1.0, mean_ms * math.exp(-0.7 * sigma)),
                "p50":  mean_ms,
                "p75":  mean_ms * math.exp(0.7 * sigma),
                "p99":  mean_ms * math.exp(2 * sigma),
                "p100": mean_ms * math.exp(3 * sigma),
            }

            trigger_mean_inv = dict((t[0], t[2]) for t in TRIGGERS)[trigger]
            invs_per_day = _sample_invocations_per_day(trigger, rng, trigger_mean_inv)

            fn_records.append({
                "HashOwner": owner, "HashApp": app, "HashFunction": func,
                "Trigger": trigger, "mean_ms": mean_ms, "pcts": pcts,
                "invs_per_day": invs_per_day,
            })

    # ----- Distribute invocations across the 1440 minutes ---------------- #
    n_total_invocations = 0
    inv_path = out_dir / f"invocations_per_function_md.anon.d{day_index:02d}.csv"
    with open(inv_path, "w", newline="") as f:
        w = csv.writer(f)
        header = ["HashOwner", "HashApp", "HashFunction", "Trigger"] + [str(i) for i in range(1, 1441)]
        w.writerow(header)
        for rec in fn_records:
            envelope = [_diurnal_factor(m) for m in range(1440)]
            env_sum = sum(envelope)
            counts = [0] * 1440
            remaining = rec["invs_per_day"]
            for m in range(1440):
                expected = rec["invs_per_day"] * envelope[m] / env_sum
                n = int(expected) + (1 if rng.random() < (expected - int(expected)) else 0)
                counts[m] = n
                remaining -= n
            # Burstiness: timers fire on the minute, events arrive in clusters.
            if rec["Trigger"] == "timer" and rec["invs_per_day"] > 0:
                # Concentrate timer firings at minute marks of 0/15/30/45 past
                # the hour to mimic cron-style scheduling.
                for m in range(0, 1440, 15):
                    if rng.random() < 0.3 and rec["invs_per_day"] > 0:
                        counts[m] += 1
            if rec["Trigger"] == "event" and rec["invs_per_day"] > 100:
                # Add a burst: 10% of invocations in a single 10-minute window.
                burst_start = rng.randint(0, 1430)
                burst_size = int(rec["invs_per_day"] * 0.10)
                for k in range(burst_size):
                    counts[burst_start + (k % 10)] += 1
                    remaining -= 1
            # Distribute any residual.
            while remaining > 0:
                counts[rng.randrange(1440)] += 1
                remaining -= 1

            n_total_invocations += sum(counts)
            row = [rec["HashOwner"], rec["HashApp"], rec["HashFunction"],
                   rec["Trigger"]] + counts
            w.writerow(row)

    # ----- Duration percentile file -------------------------------------- #
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

    return len(fn_records), n_total_invocations


def main():
    print("Generating high-fidelity Azure 2019 trace (1 day, 800 apps)...")
    n_fn, n_inv = generate_high_fidelity_2019(n_apps=800, day_index=1)
    print(f"  Wrote {ROOT}")
    print(f"  Functions: {n_fn:,}")
    print(f"  Total invocations:  {n_inv:,}")
    print(f"  Mean invocations per function:  {n_inv / max(1, n_fn):.1f}")

    # Verify the trigger distribution by counting in the file we just wrote.
    inv_path = ROOT / "invocations_per_function_md.anon.d01.csv"
    trigger_fn_counts = defaultdict(int)
    trigger_inv_counts = defaultdict(int)
    with open(inv_path) as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            trigger = row[3]
            invs = sum(int(x) if x else 0 for x in row[4:])
            trigger_fn_counts[trigger] += 1
            trigger_inv_counts[trigger] += invs
    total_fn = sum(trigger_fn_counts.values())
    total_inv = sum(trigger_inv_counts.values())
    print()
    print("  Trigger distribution by function count:")
    for t, n in sorted(trigger_fn_counts.items(), key=lambda x: -x[1]):
        print(f"    {t:<14}: {n:>5} functions ({n / max(1, total_fn):.1%})")
    print()
    print("  Trigger distribution by invocation count:")
    for t, n in sorted(trigger_inv_counts.items(), key=lambda x: -x[1]):
        print(f"    {t:<14}: {n:>8,} invocations ({n / max(1, total_inv):.1%})")


if __name__ == "__main__":
    main()
