"""
Figure: cold-start carbon trade-off break-even contour.

Renders, on a (carbon-ratio r, arrival rate lambda) plane, the boundary
between the two strategic regimes of Lemma 1:

  - "Warm in L" (green region):  warm pool in the low-carbon region wins.
  - "Cold in H" (red region):    cold-starting in the high-carbon region wins.

The boundary curve is the locus { (r, lambda) : LHS(u) = r * (1 + alpha) }
where u = lambda * T_w. We also overlay realistic FaaS region pairs as
labelled points to give the reader something to anchor on.

This is the figure that visually communicates Lemma 1 in §4.3 of the paper.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas.tradeoff import TradeoffParams, break_even_rate


def main(output_path: str = "figures/tradeoff_breakeven_contour.png"):
    # Function parameters: webhook_handler-like.
    base = dict(
        tau_e=0.3,
        tau_c=1.0,
        p_active_w=4.0,
        p_idle_w=0.3,
        t_warm_s=600.0,
        c_low=60.0,         # fix L = France
    )

    # Sweep r = C_H / C_L from just above 1 to 15 (covers FR vs IN ~ 11).
    rs = np.linspace(1.05, 15.0, 80)
    lam_stars = []
    for r in rs:
        p = TradeoffParams(c_high=60.0 * r, **base)
        ls = break_even_rate(p)
        # break_even_rate returns None if warm always wins; in plotting we
        # treat that as lambda* = 0 (the entire half-plane is "warm-in-L").
        lam_stars.append(ls if ls is not None else 0.0)
    lam_stars = np.array(lam_stars)

    # ------------------------------------------------------------------ #
    # Plot
    # ------------------------------------------------------------------ #
    fig, ax = plt.subplots(figsize=(8.2, 5.0))

    lam_min, lam_max = 1e-4, 1.0
    # Fill "warm in L" wins region (above the curve).
    ax.fill_between(
        rs, lam_stars, lam_max,
        color="#a8e6a3", alpha=0.45,
        label=r"Warm-in-L wins ($\lambda > \lambda^*$)",
    )
    # Fill "cold in H" wins region (below the curve).
    ax.fill_between(
        rs, lam_min, np.maximum(lam_stars, lam_min),
        color="#f4b6b0", alpha=0.45,
        label=r"Cold-in-H wins ($\lambda < \lambda^*$)",
    )
    # Boundary curve.
    ax.plot(rs, lam_stars, color="#222", lw=2.0, label=r"Break-even $\lambda^*(r)$")

    # Overlay realistic region pairs vs France as L (C_L = 60).
    # Use offset vectors per-label to avoid overlap on the steep portion
    # of the curve.
    pairs = [
        ("FR / GB",    220, (10, 18)),
        ("FR / CAISO", 250, (10, -22)),
        ("FR / DE",    350, (10, 18)),
        ("FR / MISO",  450, (10, -22)),
        ("FR / IN",    650, (-65, 22)),
        ("FR / PL",    700, (10, -22)),
    ]
    for label, c_h, offset in pairs:
        p = TradeoffParams(c_high=c_h, **base)
        ls = break_even_rate(p)
        ax.plot(p.r(), ls, marker="o", color="#1f3b73", markersize=6, zorder=5)
        ax.annotate(
            f"{label}\n($\\lambda^*$={ls:.3g}/s)",
            xy=(p.r(), ls),
            xytext=offset,
            textcoords="offset points",
            fontsize=8,
            color="#1f3b73",
            arrowprops=dict(arrowstyle="-", color="#1f3b73", lw=0.5),
        )

    # Reference arrival rates for typical FaaS functions.
    fn_rates = [
        ("api_auth (~30/s)", 30.0),
        ("webhook (~0.5/s)", 0.5),
        ("log_ingest (~0.01/s)", 0.01),
        ("nightly_report (~0.0001/s)", 1e-4),
    ]
    for label, rate in fn_rates:
        if lam_min <= rate <= lam_max:
            ax.axhline(rate, color="#888", lw=0.6, ls=":")
            ax.text(
                rs[-1] + 0.1, rate, label,
                fontsize=8, color="#555", va="center",
            )

    ax.set_yscale("log")
    ax.set_ylim(lam_min, lam_max)
    ax.set_xlim(rs[0], rs[-1])
    ax.set_xlabel(r"Carbon ratio $r = C_H / C_L$")
    ax.set_ylabel(r"Arrival rate $\lambda$ (invocations / second)")
    ax.set_title(
        "Cold-start carbon trade-off: break-even surface (Lemma 1)\n"
        r"webhook-like function: $\tau_e=0.3$s, $\tau_c=1.0$s, "
        r"$P_a=4$W, $P_i=0.3$W, $T_w=600$s",
        fontsize=10,
    )
    ax.legend(loc="upper left", framealpha=0.92, fontsize=9)
    ax.grid(True, alpha=0.25)

    plt.tight_layout()
    out = Path(__file__).resolve().parents[1] / output_path
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
