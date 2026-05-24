"""
greenfaas.tradeoff
==================

Closed-form cold-start carbon trade-off (Lemma 1, paper §4.3).

Given two regions with carbon intensities C_L < C_H, a function with execution
time tau_e, cold-start duration tau_c, active power P_a, idle power P_i, and a
warm-pool TTL T_w, this module exposes:

    * beta_crit(r, alpha)          : critical idle-cost ratio.
    * break_even_rate(...)         : the critical arrival rate lambda*.
    * prefer_warm_in_L(...)        : the boolean decision used by the scheduler.

The math, in compact form:

    A function should keep a warm pool in the low-carbon region L (rather than
    cold-start in the high-carbon region H) if and only if

        1 + alpha * exp(-u) + beta * (1 - exp(-u)) / u  <  r * (1 + alpha)

    where u = lambda * T_w. The LHS is strictly decreasing in u from
    1 + alpha + beta at u -> 0 to 1 at u -> infinity. The threshold

        beta_crit = (r - 1) * (1 + alpha)

    determines the regime:

      - beta <= beta_crit : warm-in-L wins for ALL lambda; no finite break-even.
      - beta >  beta_crit : there is a unique lambda* > 0 above which
                            warm-in-L wins, and below which cold-in-H wins.

The lemma's proof is in paper/04_3_tradeoff_lemma.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TradeoffParams:
    """Dimensional parameters of the warm-vs-cold decision."""

    tau_e: float       # execution time, seconds
    tau_c: float       # cold-start duration, seconds
    p_active_w: float  # active power, watts (used during exec and cold start)
    p_idle_w: float    # warm-idle power per container, watts
    t_warm_s: float    # warm-pool TTL, seconds
    c_low: float       # low-carbon region intensity (gCO2eq/kWh)
    c_high: float      # high-carbon region intensity (gCO2eq/kWh)

    def alpha(self) -> float:
        return self.tau_c / self.tau_e

    def beta(self) -> float:
        return (self.p_idle_w * self.t_warm_s) / (self.p_active_w * self.tau_e)

    def r(self) -> float:
        return self.c_high / self.c_low


def beta_crit(r: float, alpha: float) -> float:
    """Critical idle-cost ratio beyond which a finite lambda* exists."""
    return (r - 1.0) * (1.0 + alpha)


def lhs(u: float, alpha: float, beta: float) -> float:
    """LHS of the break-even inequality, written stably for small u.

    f(u) = 1 + alpha * exp(-u) + beta * (1 - exp(-u)) / u

    The factor (1 - exp(-u))/u is computed via expm1 for numerical stability:
    near u=0, naive evaluation suffers catastrophic cancellation.
    """
    if u <= 0.0:
        return 1.0 + alpha + beta  # limit as u -> 0+
    # (1 - exp(-u)) / u = -expm1(-u) / u, accurate for small u.
    decay = (-math.expm1(-u)) / u
    return 1.0 + alpha * math.exp(-u) + beta * decay


def _solve_u_star(r: float, alpha: float, beta: float, tol: float = 1e-9) -> float:
    """Solve f(u) = r * (1 + alpha) for u > 0 by bisection.

    Caller must ensure beta > beta_crit(r, alpha) so a root exists.
    """
    target = r * (1.0 + alpha)
    # f is strictly decreasing from 1 + alpha + beta at u=0+ to 1 at infinity.
    # Bracket: f(u_lo) > target > f(u_hi).
    u_lo = 1e-12
    u_hi = 1.0
    # Grow u_hi until f(u_hi) < target (it must eventually, since f -> 1).
    while lhs(u_hi, alpha, beta) >= target:
        u_hi *= 2.0
        if u_hi > 1e18:
            raise RuntimeError("Failed to bracket root in trade-off solver.")
    # Bisection
    for _ in range(200):
        u_mid = 0.5 * (u_lo + u_hi)
        if lhs(u_mid, alpha, beta) > target:
            u_lo = u_mid
        else:
            u_hi = u_mid
        if u_hi - u_lo < tol:
            break
    return 0.5 * (u_lo + u_hi)


def break_even_rate(params: TradeoffParams) -> Optional[float]:
    """Critical arrival rate lambda* (per second), or None if warm-in-L
    is universally preferable (beta <= beta_crit).

    Returns
    -------
    None       if warm-in-L wins for ALL lambda > 0.
    float      otherwise: above lambda*, warm-in-L wins; below, cold-in-H wins.
    """
    r = params.r()
    alpha = params.alpha()
    beta = params.beta()
    if r <= 1.0:
        # No carbon advantage to going to L: C_L >= C_H, so the lemma's
        # premise (C_L < C_H) is violated. Return None to signal "no
        # spatial advantage exists"; callers should keep the home region.
        # NB: this is NOT the "warm always wins" branch (case 1 of the
        # lemma); it is a degenerate case outside the lemma's scope.
        return None
    if beta <= beta_crit(r, alpha):
        return None  # Warm-in-L wins everywhere; no finite break-even.
    u_star = _solve_u_star(r, alpha, beta)
    return u_star / params.t_warm_s


def prefer_warm_in_L(params: TradeoffParams, lam: float) -> bool:
    """Decide warm-in-L (True) vs cold-in-H (False) at observed rate `lam`."""
    lam_star = break_even_rate(params)
    if lam_star is None:
        return True
    return lam > lam_star


def linearized_lambda_star(params: TradeoffParams) -> Optional[float]:
    """The §4.3.5 small-u approximation, useful for sanity-checking.

    lambda* ~ (beta - beta_crit) / (T_w * (alpha + beta/2))

    Returns None when the lemma's first branch applies (no finite break-even).
    """
    r = params.r()
    alpha = params.alpha()
    beta = params.beta()
    bc = beta_crit(r, alpha)
    if beta <= bc:
        return None
    return (beta - bc) / (params.t_warm_s * (alpha + beta / 2.0))


def per_invocation_carbon(params: TradeoffParams, lam: float, strategy: str) -> float:
    """Per-invocation carbon (in gCO2eq up to unit conversion), for diagnostics.

    strategy = "A"  -> warm in L
    strategy = "B"  -> cold in H

    Energy is in joules; we convert J -> kWh by dividing by 3.6e6.
    Carbon is energy * intensity.
    """
    tau_e = params.tau_e
    tau_c = params.tau_c
    Pa = params.p_active_w
    Pi = params.p_idle_w
    Tw = params.t_warm_s
    if strategy == "A":
        # E_A = Pa*tau_e + exp(-lam*Tw)*Pa*tau_c + (1 - exp(-lam*Tw))/lam * Pi
        if lam <= 0:
            return float("inf")
        u = lam * Tw
        idle_time = (-math.expm1(-u)) / lam  # (1 - exp(-u)) / lam, stable
        E_J = Pa * tau_e + math.exp(-u) * Pa * tau_c + idle_time * Pi
        return (E_J / 3.6e6) * params.c_low
    elif strategy == "B":
        E_J = Pa * (tau_e + tau_c)
        return (E_J / 3.6e6) * params.c_high
    else:
        raise ValueError("strategy must be 'A' or 'B'")
