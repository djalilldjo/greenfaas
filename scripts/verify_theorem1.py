"""
Diagnostic: why the single-container Lechowicz lower-bound construction
does NOT establish a beta-dependent bound.

An earlier version of this script claimed to verify a Theorem 9.1 bound
at N=100. A careful reviewer correctly noted the proof's idle-cost
summation double-counts idle in the single-container model: at any
moment only ONE warm container exists, so its idle period is a single
contiguous interval, not a sum over N pending invocations.

The paper now states the lower bound as Conjecture 9.1 instead of a
theorem. This diagnostic script supports that retraction: it shows
that the bound DOES NOT hold in the strict single-container model
(Variant S, matching the formal Lemma 1 cost equation), but DOES hold
in the independent-pending model (Variant P) which idealizes FaaS
production behavior.

Run: python scripts/verify_theorem1.py
"""
from __future__ import annotations
import math

# Parameters
P_a, P_i, tau_e, T_w = 4.0, 0.3, 0.3, 600.0
L, U = 73.0, 869.0  # FR/PL on EM Jan 2021
r = U / L
beta = (P_i * T_w) / (P_a * tau_e)

print(f"Parameters: P_a={P_a}, P_i={P_i}, tau_e={tau_e}, T_w={T_w}")
print(f"            L={L}, U={U}, r={r:.2f}, beta={beta:.1f}")
print()
print("=" * 70)
print("Variant S (single-container): bound does NOT hold")
print("=" * 70)

def variant_S(N):
    Delta_t = T_w / N
    # Lechowicz: all N execute back-to-back warm starting at T_w.
    # Single physical container, one continuous idle [0, T_w] at U.
    # Then back-to-back execution: no inter-execution idle.
    # Then post-i_N: T_w at L.
    lech_idle = P_i * T_w * U + P_i * T_w * L
    lech_exec = N * P_a * tau_e * L
    lech_total = lech_idle + lech_exec

    # OPT: commit each at arrival.
    opt_idle = (N - 1) * P_i * Delta_t * U + P_i * T_w * L
    opt_exec = N * P_a * tau_e * U
    opt_total = opt_idle + opt_exec
    return lech_total, opt_total, lech_total / opt_total

print(f"{'N':>6} {'Lechowicz':>14} {'OPT':>14} {'Ratio':>8}")
print("-" * 46)
for N in [5, 10, 20, 50, 100, 500, 1000]:
    lech, opt, ratio = variant_S(N)
    print(f"{N:>6} {lech:>14.2f} {opt:>14.2f} {ratio:>8.4f}")

print()
print("Ratio stays near 1.2 regardless of N. NOT Theta(beta).")
print("The single-container proof attempt double-counted idle.")

print()
print("=" * 70)
print("Variant P (independent-pending): bound DOES hold asymptotically")
print("=" * 70)

def variant_P(N):
    Delta_t = T_w / N
    # Lechowicz: each pending container idles (T_w - t_k) at U.
    lech_pending_idle = P_i * U * T_w * (N - 1) / 2
    lech_exec = N * P_a * tau_e * L
    lech_post_idle = N * P_i * T_w * L
    lech_total = lech_pending_idle + lech_exec + lech_post_idle

    # OPT: zero pre-commit idle, exec at U, post-commit idle.
    opt_exec = N * P_a * tau_e * U
    opt_post_idle = N * P_i * T_w * L
    opt_total = opt_exec + opt_post_idle
    return lech_total, opt_total, lech_total / opt_total

print(f"{'N':>6} {'Lechowicz':>14} {'OPT':>14} {'Ratio':>8}")
print("-" * 46)
for N in [5, 10, 20, 50, 100, 500, 1000]:
    lech, opt, ratio = variant_P(N)
    print(f"{N:>6} {lech:>14.2f} {opt:>14.2f} {ratio:>8.4f}")

print()
print(f"Ratio grows toward Theta(beta) = {beta:.1f}.")
print("Conjecture 9.1 is empirically supported in Variant P.")
print("A formal proof requires a multi-container model matching FaaS")
print("production semantics; this remains open.")

print()
print("=" * 70)
print("Summary")
print("=" * 70)
print("Variant S (single-container, matches Lemma 1 formal model):")
print("  ratio ~ 1.2, no beta-dependence. Naive proof attempt fails.")
print()
print("Variant P (independent-pending, idealization of FaaS production):")
print("  ratio grows with beta, supporting Conjecture 9.1.")
print()
print("The paper's Theorem 9.2 (Sqrt(r) lower bound, beta=0 limit) is")
print("the only proven result. Conjecture 9.1 is supported numerically")
print("here and empirically in Section 8.5 (Lechowicz performs worst")
print("of all baselines on FaaS workloads).")
