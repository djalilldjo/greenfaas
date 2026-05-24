"""
Paired statistical significance tests for key scheduler comparisons.

Addresses the FGCS reviewer concern that mean +/- std reporting lacks
formal significance testing. For each key comparison we run:
  - paired t-test (parametric)
  - Wilcoxon signed-rank test (non-parametric, robust to non-normality)

over the per-seed (synthetic) or per-window (real) carbon measurements.

Comparisons tested:
  1. GreenFaaS vs Spatial   (synthetic 5-region, 5 seeds)
  2. GreenFaaS vs Spatial   (real workload, window-shift, 5 windows)
  3. GreenFaaS vs GreenFaaS-v1 (synthetic, 5 seeds) -- ablation
  4. GreenFaaS vs FIFO      (synthetic, 5 seeds) -- sanity, should be significant
  5. Wait-Awhile vs FIFO    (real, 5 windows) -- should show WA is worse

Run: python scripts/stat_tests.py
"""
from __future__ import annotations
import csv
import sys
from collections import defaultdict
from pathlib import Path

from scipy import stats

PROJ = Path(__file__).resolve().parents[1]


def load_paired(csv_path, key_col, scheduler_col="scheduler", value_col="carbon_g"):
    """Load a CSV into {scheduler: [(key, value), ...]} sorted by key."""
    rows = list(csv.DictReader(open(csv_path)))
    buckets = defaultdict(dict)
    for r in rows:
        buckets[r[scheduler_col]][r[key_col]] = float(r[value_col])
    return buckets


def paired_test(buckets, sched_a, sched_b, label):
    """Run paired t-test and Wilcoxon on two schedulers' paired measurements."""
    keys = sorted(set(buckets[sched_a]) & set(buckets[sched_b]))
    a = [buckets[sched_a][k] for k in keys]
    b = [buckets[sched_b][k] for k in keys]
    n = len(keys)
    if n < 2:
        print(f"  {label}: insufficient paired data (n={n})")
        return

    # Paired t-test
    t_stat, t_p = stats.ttest_rel(a, b)
    # Wilcoxon signed-rank (requires non-zero differences; guard)
    diffs = [x - y for x, y in zip(a, b)]
    if all(d == 0 for d in diffs):
        w_p = 1.0
        w_note = "(all differences zero -> identical)"
    else:
        try:
            w_stat, w_p = stats.wilcoxon(a, b)
            w_note = ""
        except ValueError as e:
            w_p = float("nan")
            w_note = f"(Wilcoxon failed: {e})"

    mean_a = sum(a) / n
    mean_b = sum(b) / n
    mean_diff = sum(diffs) / n
    sig = "***" if t_p < 0.001 else "**" if t_p < 0.01 else "*" if t_p < 0.05 else "n.s."

    print(f"  {label} (n={n}):")
    print(f"    mean({sched_a})={mean_a:.3f}, mean({sched_b})={mean_b:.3f}, diff={mean_diff:+.3f}")
    print(f"    paired t-test:  t={t_stat:+.3f}, p={t_p:.4f}  [{sig}]")
    print(f"    Wilcoxon:       p={w_p:.4f}  {w_note}")
    print()
    return {"comparison": label, "n": n, "mean_a": mean_a, "mean_b": mean_b,
            "mean_diff": mean_diff, "t_stat": t_stat, "t_p": t_p, "wilcoxon_p": w_p,
            "significant_05": t_p < 0.05}


def main():
    results = []

    print("=" * 70)
    print("Synthetic 5-region, multi-seed (5 seeds)")
    print("=" * 70)
    syn = load_paired(PROJ / "results" / "multi_seed_synthetic.csv", key_col="seed")
    results.append(paired_test(syn, "GreenFaaS", "Spatial",
                               "GreenFaaS vs Spatial [synthetic]"))
    results.append(paired_test(syn, "GreenFaaS", "GreenFaaS-v1",
                               "GreenFaaS vs v1 ablation [synthetic]"))
    results.append(paired_test(syn, "GreenFaaS", "FIFO",
                               "GreenFaaS vs FIFO [synthetic]"))

    print("=" * 70)
    print("Real workload, window-shift (5 windows)")
    print("=" * 70)
    real = load_paired(PROJ / "results" / "real_workload_window_variance_raw.csv",
                       key_col="window_day")
    results.append(paired_test(real, "GreenFaaS", "Spatial",
                               "GreenFaaS vs Spatial [real, windows]"))
    results.append(paired_test(real, "GreenFaaS", "GreenFaaS-v1",
                               "GreenFaaS vs v1 ablation [real, windows]"))
    results.append(paired_test(real, "Wait-Awhile", "FIFO",
                               "Wait-Awhile vs FIFO [real, windows]"))
    results.append(paired_test(real, "Lechowicz", "FIFO",
                               "Lechowicz vs FIFO [real, windows]"))

    # Save
    out = PROJ / "results" / "stat_tests.csv"
    clean = [r for r in results if r]
    if clean:
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(clean[0].keys()))
            w.writeheader()
            for r in clean:
                w.writerow(r)
        print(f"Saved {len(clean)} test results to {out}")

    print()
    print("Interpretation key:")
    print("  *** p<0.001, ** p<0.01, * p<0.05, n.s. = not significant")
    print("  n.s. on GreenFaaS-vs-Spatial means the gap is NOT significant,")
    print("  i.e. the two are statistically indistinguishable (a feature, not a bug:")
    print("  it supports the 'GreenFaaS matches Spatial' claim).")


if __name__ == "__main__":
    main()
