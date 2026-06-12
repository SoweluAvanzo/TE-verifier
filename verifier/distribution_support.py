"""Conservative numeric envelopes for ``DistributionSpec``.

The schema documents the contract (``schema.te_ir.DistributionSpec``):
the *verifier* interprets a stochastic distribution as its support and
reasons over the resulting interval conservatively, while the
*simulator* samples the distribution proper each period. This module
is the single implementation of that contract:

* ``support(spec)`` — the (lo, hi) interval the static layer binds a
  Z3 variable to. Unbounded distributions use the conventional 3-sigma
  envelope (≥ 99.7% of the mass for normal; the analogous quantile
  envelope for lognormal and Poisson). Callers clamp ``lo`` at 0 when
  the value is a rate, matching the ABM's ``max(0, sample)`` clamp.
* ``mean(spec)`` — the analytic mean, used by the midpoint layers
  (risk banding, deterministic diagnostic trajectories) where a point
  estimate rather than an envelope is wanted.

Parameter names follow ``verifier.abm.samplers.Sampler.sample_distribution``:
uniform(low, high), normal(mu, sigma), lognormal(mu, sigma),
bernoulli(p), poisson(lambda), beta(alpha, beta).
"""

from __future__ import annotations

import math

from schema import DistributionSpec

# 3-sigma envelope: covers ≥ 99.7% of the mass for the normal family
# and is the documented convention in the DistributionSpec docstring.
_SIGMAS = 3.0


def support(spec: DistributionSpec) -> tuple[float, float]:
    """Return the (lo, hi) interval the static layer reasons over."""
    p = spec.parameters
    kind = spec.kind
    if kind == "uniform":
        return (float(p["low"]), float(p["high"]))
    if kind == "normal":
        mu, sigma = float(p["mu"]), float(p["sigma"])
        return (mu - _SIGMAS * sigma, mu + _SIGMAS * sigma)
    if kind == "lognormal":
        mu, sigma = float(p["mu"]), float(p["sigma"])
        return (math.exp(mu - _SIGMAS * sigma), math.exp(mu + _SIGMAS * sigma))
    if kind == "bernoulli":
        return (0.0, 1.0)
    if kind == "poisson":
        lam = float(p["lambda"])
        # Poisson std is sqrt(lambda); [0, lambda + 3*sqrt(lambda)]
        # covers > 99.7% of the mass for lambda >= 1 and is exact at
        # the lower end (counts are non-negative).
        return (0.0, lam + _SIGMAS * math.sqrt(lam))
    if kind == "beta":
        return (0.0, 1.0)
    raise ValueError(f"unknown distribution kind: {kind}")


def mean(spec: DistributionSpec) -> float:
    """Return the analytic mean of the distribution."""
    p = spec.parameters
    kind = spec.kind
    if kind == "uniform":
        return (float(p["low"]) + float(p["high"])) / 2.0
    if kind == "normal":
        return float(p["mu"])
    if kind == "lognormal":
        mu, sigma = float(p["mu"]), float(p["sigma"])
        return math.exp(mu + sigma * sigma / 2.0)
    if kind == "bernoulli":
        return float(p["p"])
    if kind == "poisson":
        return float(p["lambda"])
    if kind == "beta":
        a, b = float(p["alpha"]), float(p["beta"])
        return a / (a + b)
    raise ValueError(f"unknown distribution kind: {kind}")


def rate_support(spec: DistributionSpec) -> tuple[float, float]:
    """``support`` with the lower end clamped at 0 — the envelope for
    values used as rates (emission / burn / event arrivals), matching
    the ABM's ``max(0, sample)`` clamp."""
    lo, hi = support(spec)
    return (max(0.0, lo), max(0.0, hi))
