"""
Verify Lemma 1 (paper §4.3) numerically.

We compute, for a grid of (lambda, r) values, both:
    (a) the lemma's prediction of which strategy wins, and
    (b) the brute-force direct comparison of per-invocation carbon.
and assert they agree at every grid point.

This is a guard-rail for the algebra. Run it before trusting the scheduler.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenfaas.tradeoff import (
    TradeoffParams,
    beta_crit,
    break_even_rate,
    lhs,
    per_invocation_carbon,
    prefer_warm_in_L,
    linearized_lambda_star,
)


def main():
    # webhook_handler-like parameters from the paper's worked example.
    base = dict(
        tau_e=0.3,
        tau_c=1.0,
        p_active_w=4.0,
        p_idle_w=0.3,
        t_warm_s=600.0,
        c_low=60.0,
    )

    print("=" * 72)
    print("Trade-off lemma numerical verification")
    print("=" * 72)

    # ------------------------------------------------------------------ #
    # 1. Reproduce the paper's worked example (France vs Germany).
    # ------------------------------------------------------------------ #
    print("\nWorked example: France (60) vs Germany (350)")
    p = TradeoffParams(c_high=350.0, **base)
    alpha = p.alpha()
    beta = p.beta()
    r = p.r()
    bc = beta_crit(r, alpha)
    print(f"  alpha = tau_c/tau_e         = {alpha:.3f}")
    print(f"  beta  = Pi*Tw/(Pa*tau_e)    = {beta:.3f}")
    print(f"  r     = C_H/C_L             = {r:.3f}")
    print(f"  beta_crit = (r-1)(1+alpha)  = {bc:.3f}")
    print(f"  beta > beta_crit?            {beta > bc}  (finite lambda* exists)")
    lam_star = break_even_rate(p)
    lam_star_lin = linearized_lambda_star(p)
    u_star = lam_star * p.t_warm_s
    print(f"  u*          = lambda* * Tw  = {u_star:.4f}")
    print(f"  lambda*     (exact)         = {lam_star:.6f} /s  "
          f"(period ~ {1.0/lam_star:.1f} s)")
    print(f"  lambda*     (linearized)    = {lam_star_lin:.6f} /s")
    # The paper claims u* ~ 6.2 and lambda* ~ 0.010 /s for these params.
    assert abs(u_star - 6.2) < 0.2, f"u* deviates from paper: {u_star}"
    assert abs(lam_star - 0.010) < 0.002, f"lambda* deviates from paper: {lam_star}"
    print("  PASS: matches paper's worked example.")

    # ------------------------------------------------------------------ #
    # 2. France vs Poland (paper claims lambda* ~ 0.003 /s).
    # ------------------------------------------------------------------ #
    print("\nFrance (60) vs Poland (700)")
    p2 = TradeoffParams(c_high=700.0, **base)
    lam_star2 = break_even_rate(p2)
    print(f"  r           = {p2.r():.3f}")
    print(f"  beta_crit   = {beta_crit(p2.r(), p2.alpha()):.3f}")
    print(f"  lambda*     = {lam_star2:.6f} /s "
          f"(period ~ {1.0/lam_star2:.1f} s)")
    assert abs(lam_star2 - 0.003) < 0.002, f"lambda* deviates: {lam_star2}"
    print("  PASS: matches paper's worked example.")

    # ------------------------------------------------------------------ #
    # 3. Brute-force cross-check: at every grid point in (lambda, C_H),
    #    the lemma's prediction must agree with direct carbon comparison.
    # ------------------------------------------------------------------ #
    print("\nGrid cross-check vs brute-force carbon comparison")
    lambdas = [0.0001, 0.001, 0.003, 0.005, 0.01, 0.03, 0.1, 1.0]
    c_highs = [80.0, 150.0, 250.0, 350.0, 500.0, 700.0, 1000.0]
    mismatches = 0
    checks = 0
    for ch in c_highs:
        pp = TradeoffParams(c_high=ch, **base)
        for lam in lambdas:
            carbon_A = per_invocation_carbon(pp, lam, "A")
            carbon_B = per_invocation_carbon(pp, lam, "B")
            brute_force_says_A = carbon_A < carbon_B
            lemma_says_A = prefer_warm_in_L(pp, lam)
            checks += 1
            if brute_force_says_A != lemma_says_A:
                mismatches += 1
                print(f"  MISMATCH: C_H={ch}, lambda={lam}: "
                      f"brute={brute_force_says_A} lemma={lemma_says_A} "
                      f"(carbon_A={carbon_A:.4e}, carbon_B={carbon_B:.4e})")
    print(f"  Checked {checks} grid points; mismatches: {mismatches}")
    assert mismatches == 0, "Lemma disagrees with brute force!"
    print("  PASS: lemma and brute-force agree at every grid point.")

    # ------------------------------------------------------------------ #
    # 4. Monotonicity: f(u) must be strictly decreasing.
    # ------------------------------------------------------------------ #
    print("\nMonotonicity of f(u)")
    pp = TradeoffParams(c_high=350.0, **base)
    a, b = pp.alpha(), pp.beta()
    prev = lhs(1e-6, a, b)
    violated = False
    for u in [0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 50.0, 1000.0]:
        cur = lhs(u, a, b)
        if cur >= prev:
            print(f"  VIOLATION at u={u}: f={cur} >= prev={prev}")
            violated = True
        prev = cur
    assert not violated
    print("  PASS: f(u) strictly decreasing as predicted.")

    # ------------------------------------------------------------------ #
    # 5. Universal regime (beta < beta_crit): need a small beta or large r.
    # ------------------------------------------------------------------ #
    print("\nUniversal-warm-wins regime (beta < beta_crit)")
    # Same base, but a tiny TTL so that beta is small.
    base_short_ttl = dict(base)
    base_short_ttl["t_warm_s"] = 5.0
    p_uni = TradeoffParams(c_high=700.0, **base_short_ttl)
    a, b = p_uni.alpha(), p_uni.beta()
    bc = beta_crit(p_uni.r(), a)
    print(f"  alpha={a:.3f}, beta={b:.3f}, beta_crit={bc:.3f}")
    print(f"  beta <= beta_crit? {b <= bc}")
    lam_star = break_even_rate(p_uni)
    assert lam_star is None, f"Expected None, got {lam_star}"
    print("  PASS: break_even_rate returns None (warm-in-L wins everywhere).")
    # And brute-force confirms it for a wide range of lambdas:
    for lam in [1e-5, 1e-3, 1.0]:
        cA = per_invocation_carbon(p_uni, lam, "A")
        cB = per_invocation_carbon(p_uni, lam, "B")
        assert cA < cB, f"Brute force disagrees at lam={lam}: A={cA}, B={cB}"
    print("  PASS: brute force confirms warm-in-L wins at all tested lambdas.")

    print("\n" + "=" * 72)
    print("All trade-off lemma checks passed.")
    print("=" * 72)


if __name__ == "__main__":
    main()
