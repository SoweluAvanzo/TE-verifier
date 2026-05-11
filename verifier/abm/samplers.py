"""Stochastic samplers from declared IR ranges and distributions.

The verifier reasons over support (the full NumberRange or μ±3σ of a
DistributionSpec). The ABM samples from the actual distribution.

Convention: when the user did not declare a DistributionSpec, the
sampler defaults to ``uniform(min, max)``. This is the maximally
agnostic choice — any other default would inject hidden assumptions
into the simulation. Users who want a tighter distribution (e.g.
truncated-normal around the midpoint) declare it explicitly in the
schema.

Note: at v1 the verifier IR doesn't expose DistributionSpec on
NumberRange fields directly — only via the ``vote_weighting_params``,
emission/burn rule schedules, etc. For now we sample uniformly over
NumberRange and fall back to distribution-aware sampling when fields
carry an explicit DistributionSpec (placeholder; wire when v2 lands).
"""

from __future__ import annotations

import math
import random
from typing import Iterable

from schema import DistributionSpec, NumberRange


class Sampler:
    """Tiny stateful sampler. Wraps random.Random for determinism."""

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Range sampling
    # ------------------------------------------------------------------

    def sample_range(self, rng: NumberRange) -> float:
        """Uniform over [min, max]. The default for any declared
        NumberRange without a distribution."""
        if rng.min == rng.max:
            return rng.min
        return self.rng.uniform(rng.min, rng.max)

    def sample_range_point_or_mid(self, rng: NumberRange) -> float:
        """For parameters that should hold constant across periods in
        a single run (sampled once, then frozen)."""
        return self.sample_range(rng)

    def sample_range_per_period(
        self, rng: NumberRange, periods: int
    ) -> list[float]:
        """For parameters that resample each period (rate noise)."""
        return [self.sample_range(rng) for _ in range(periods)]

    # ------------------------------------------------------------------
    # Multi-value sampling (e.g. all parameter ranges of an AC)
    # ------------------------------------------------------------------

    def sample_dict(
        self, ranges: dict[str, NumberRange]
    ) -> dict[str, float]:
        """Sample each NumberRange in a dict, return a flat dict of
        sampled values."""
        return {k: self.sample_range(v) for k, v in ranges.items()}

    # ------------------------------------------------------------------
    # DistributionSpec sampling — per-family dispatch.
    # ------------------------------------------------------------------

    def sample_distribution(self, dist: DistributionSpec) -> float:
        """Draw one sample from a declared DistributionSpec.

        Used for per-period rate noise: when a rule's FunctionShape
        carries a ``distribution`` field, the engine resamples per
        period instead of holding the once-per-run NumberRange value
        constant. Returns a non-negative float for rate-like quantities
        (the engine clamps below 0 to 0 for emission/burn/Q).
        """
        params = dist.parameters
        kind = dist.kind
        if kind == "uniform":
            return self.rng.uniform(params["low"], params["high"])
        if kind == "normal":
            return self.rng.gauss(params["mu"], params["sigma"])
        if kind == "lognormal":
            # parameters mu, sigma are of the log
            return self.rng.lognormvariate(params["mu"], params["sigma"])
        if kind == "bernoulli":
            return 1.0 if self.rng.random() < params["p"] else 0.0
        if kind == "poisson":
            # Knuth's algorithm — small λ regime is fine.
            L = math.exp(-params["lambda"])
            k = 0
            p = 1.0
            while True:
                k += 1
                p *= self.rng.random()
                if p <= L:
                    return float(k - 1)
        if kind == "beta":
            return self.rng.betavariate(params["alpha"], params["beta"])
        raise ValueError(f"unknown distribution kind: {kind}")

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def coin(self, p: float) -> bool:
        """Bernoulli(p)."""
        return self.rng.random() < p
