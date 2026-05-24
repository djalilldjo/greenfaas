"""
Motivation figure for the GreenFaaS paper.

Renders, for a single region (Germany), a 48h carbon-intensity trace overlaid
on the per-minute invocation rate of a representative function. Shaded bands
mark the lowest- and highest-quartile carbon windows, making the shifting
opportunity visually obvious.

This corresponds to Item 4 of the research plan's Immediate Next Actions.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas import (
    CarbonModel,
    generate_workload,
    make_default_function_catalog,
)


def main(output_path: str = "figures/motivation_carbon_vs_invocations.png"):
    duration_s = 48 * 3600.0
    region = "DE"
    functions = make_default_function_catalog()
    carbon = CarbonModel.synthetic([region], duration_s, step_s=300.0, seed=7)
    trace = carbon.traces[region]

    invocations = generate_workload(
        duration_s=duration_s,
        base_rate_per_s=6.0,
        functions=functions,
        region_ids=[region],
        seed=11,
    )

    # Focus on one representative deferrable function (webhook_handler).
    target_fn = "webhook_handler"
    arrivals = [inv.arrival_time for inv in invocations if inv.function_id == target_fn]

    # Bin invocation arrivals per minute.
    bin_s = 60.0
    n_bins = int(duration_s / bin_s)
    counts = np.zeros(n_bins)
    for t in arrivals:
        idx = int(t // bin_s)
        if 0 <= idx < n_bins:
            counts[idx] += 1
    minutes = np.arange(n_bins) * (bin_s / 60.0)  # in minutes

    # Carbon trace at minute resolution.
    ci_minutes = np.array([trace.intensity(m * 60.0) for m in minutes])

    # Carbon quartile bands.
    q25, q75 = np.percentile(ci_minutes, [25, 75])
    low_band = ci_minutes <= q25
    high_band = ci_minutes >= q75

    # ------------------------------------------------------------------ #
    # Plot
    # ------------------------------------------------------------------ #
    fig, ax1 = plt.subplots(figsize=(11, 4.5))

    # Carbon-intensity quartile shading (full plot height as vertical bands).
    _fill_top = ci_minutes.max() * 1.45
    ax1.fill_between(
        minutes / 60.0, 0, _fill_top,
        where=low_band, color="#a8e6a3", alpha=0.35,
        step="mid", label="Lowest-quartile carbon",
    )
    ax1.fill_between(
        minutes / 60.0, 0, _fill_top,
        where=high_band, color="#f4b6b0", alpha=0.30,
        step="mid", label="Highest-quartile carbon",
    )

    # Carbon line (green).
    ax1.plot(
        minutes / 60.0, ci_minutes,
        color="#1b7837", lw=1.8, label="Grid carbon intensity (DE)",
    )
    ax1.set_xlabel("Time (hours)")
    ax1.set_ylabel("Carbon intensity (gCO\u2082eq / kWh)", color="#1b7837")
    ax1.tick_params(axis="y", labelcolor="#1b7837")
    ax1.set_xlim(0, duration_s / 3600.0)
    # Extra headroom reserves a clear band at the top for the legend and
    # annotation so they never overlap the plotted curves.
    ax1.set_ylim(0, ci_minutes.max() * 1.45)

    # Invocation-rate line on a secondary axis.
    ax2 = ax1.twinx()
    # Smooth slightly so the burstiness is visible without being noisy.
    window = 5
    smoothed = np.convolve(counts, np.ones(window) / window, mode="same")
    ax2.plot(
        minutes / 60.0, smoothed,
        color="#d95f02", lw=1.8, alpha=0.95,
        label=f"Invocation rate of '{target_fn}'",
    )
    ax2.set_ylabel(f"Invocations / min", color="#d95f02")
    ax2.tick_params(axis="y", labelcolor="#d95f02")
    # Match the headroom of the primary axis so the orange curve also
    # stays in the lower portion, leaving the top band clear.
    ax2.set_ylim(0, smoothed.max() * 1.45)

    # Combined legend, placed ABOVE the plot area (outside the axes) in a
    # single horizontal row so it never overlaps the curves.
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(
        h1 + h2, l1 + l2,
        loc="lower center", bbox_to_anchor=(0.5, 1.02),
        ncol=2, framealpha=0.0, fontsize=8.5,
        handlelength=1.6, columnspacing=1.4,
    )

    # Compute the headline numbers we want to annotate on the figure.
    low_invs = counts[low_band].sum()
    high_invs = counts[high_band].sum()
    total = counts.sum()
    pct_high = high_invs / total
    pct_outside_low = 1.0 - low_invs / total

    # No on-axes title: the LaTeX caption carries the description, and the
    # legend now occupies the band above the plot.

    # On-figure annotation of the key quantitative claim, placed in the
    # cleared top-left band (the curves now peak well below it).
    annotation = (
        f"{pct_outside_low:.0%} of invocations land outside "
        f"the cleanest-carbon quartile\n"
        f"({pct_high:.0%} in the highest-carbon quartile alone)"
    )
    ax1.text(
        0.02, 0.97, annotation,
        transform=ax1.transAxes,
        verticalalignment="top",
        fontsize=8.5,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                  edgecolor="#888", alpha=0.95),
    )

    plt.tight_layout()
    out = Path(__file__).resolve().parents[1] / output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    # 300 DPI for camera-ready (was 160).
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(f"Wrote {out}")

    # Mirror the headline numbers to stdout for log readers.
    print(
        f"{target_fn}: {pct_high:.1%} of invocations land in the "
        f"highest-carbon quartile; only {low_invs / total:.1%} in the lowest. "
        f"=> meaningful shifting potential."
    )


if __name__ == "__main__":
    main()
