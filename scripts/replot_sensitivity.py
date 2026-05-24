"""
Regenerate sensitivity-sweep figures from the CSV outputs of
scripts/sensitivity_sweep.py. Useful when only the figure layout changes;
the underlying numbers are read from results/sensitivity_*.csv.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Reuse the plotting functions and the SCHED_COLORS palette.
import scripts.sensitivity_sweep as sw

PROJ = Path(__file__).resolve().parents[1]


def load_rows(csv_path: Path):
    rows = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            # Cast numeric columns; leave the categorical 'x' (forecast) as str.
            for key in ("carbon_g", "reduction_pct", "sla_viol", "cold_rate", "invocations"):
                if key in row:
                    row[key] = float(row[key])
            try:
                row["x"] = float(row["x"])
            except ValueError:
                pass  # categorical
            rows.append(row)
    return rows


def main():
    sw._FIGURE_DIR = PROJ / "figures"

    # Workload intensity (numeric).
    rows = load_rows(PROJ / "results" / "sensitivity_intensity.csv")
    xs = sorted({r["x"] for r in rows})
    sw.plot_axis(sw._FIGURE_DIR, "Workload Intensity",
                 "Peak rate (invocations/s)", xs, rows,
                 "sensitivity_intensity.png")

    # SLA mix (numeric).
    rows = load_rows(PROJ / "results" / "sensitivity_sla_mix.csv")
    xs = sorted({r["x"] for r in rows})
    sw.plot_axis(sw._FIGURE_DIR, "SLA Class Mix",
                 "Shiftable fraction (deferrable + background)",
                 xs, rows, "sensitivity_sla_mix.png")

    # Forecast accuracy (categorical).
    rows = load_rows(PROJ / "results" / "sensitivity_forecast.csv")
    cats = []
    seen = set()
    for r in rows:
        if r["x"] not in seen:
            seen.add(r["x"])
            cats.append(r["x"])
    sw.plot_axis_categorical(sw._FIGURE_DIR, "Forecast Accuracy",
                             "Forecast horizon", cats, rows,
                             "sensitivity_forecast.png")

    # Carbon variability (numeric).
    rows = load_rows(PROJ / "results" / "sensitivity_variability.csv")
    xs = sorted({r["x"] for r in rows})
    sw.plot_axis(sw._FIGURE_DIR, "Carbon Variability",
                 "Diurnal amplitude (fraction of mean intensity)",
                 xs, rows, "sensitivity_variability.png")


if __name__ == "__main__":
    main()
