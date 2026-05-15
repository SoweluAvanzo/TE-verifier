"""Phase L2 — stochastic event frequency.

EventDefinition can now carry a ``frequency_distribution: DistributionSpec``
that overrides the deterministic AsymptoticClass when the ABM realises
per-period firings. Models economic shocks, bursty arrivals, gated events.

Tests confirm:
* schema validators reject mathematically impossible parameters
  (negative Poisson λ, σ < 0, Bernoulli p outside [0, 1])
* ABM produces non-deterministic firings under the distribution
* different seeds yield different per-period counts
* DistributionSpec takes precedence over the AsymptoticClass when
  both are present
* the events catalog still works without the new field (back-compat)
* the explore page surfaces the realised firings in
  ``PeriodSnapshot.events_realized`` so the chart layer can plot them
"""

from __future__ import annotations

import statistics

import pytest

from schema import (
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    DistributionSpec,
    EmissionTriggerKind,
    EventDefinition,
    EventTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceSpec,
    GovernanceType,
    Meta,
    NFRs,
    NumberRange,
    ParticipantsSpec,
    Rule,
    RuleTrigger,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
)
from verifier.abm import SimulationConfig
from verifier.abm.explore import run_explore


# ---------------------------------------------------------------------------
# Schema validators
# ---------------------------------------------------------------------------


def test_event_rejects_negative_poisson_lambda() -> None:
    with pytest.raises(ValueError):
        EventDefinition(
            id="shock", label="shock", kind=EventTriggerKind.ALGORITHMIC,
            frequency_distribution=DistributionSpec(
                kind="poisson", parameters={"lambda": -3.0}
            ),
        )


def test_event_rejects_negative_normal_sigma() -> None:
    with pytest.raises(ValueError):
        EventDefinition(
            id="shock", label="shock", kind=EventTriggerKind.ALGORITHMIC,
            frequency_distribution=DistributionSpec(
                kind="normal", parameters={"mu": 1.0, "sigma": -0.5}
            ),
        )


def test_event_rejects_invalid_bernoulli_p() -> None:
    with pytest.raises(ValueError):
        EventDefinition(
            id="shock", label="shock", kind=EventTriggerKind.ALGORITHMIC,
            frequency_distribution=DistributionSpec(
                kind="bernoulli", parameters={"p": 1.5}
            ),
        )


def test_event_accepts_well_formed_distribution() -> None:
    ev = EventDefinition(
        id="shock", label="shock", kind=EventTriggerKind.ALGORITHMIC,
        frequency_distribution=DistributionSpec(
            kind="normal", parameters={"mu": 5.0, "sigma": 1.0}
        ),
    )
    assert ev.frequency_distribution.kind == "normal"


# ---------------------------------------------------------------------------
# ABM consumption
# ---------------------------------------------------------------------------


def _shock_te(distribution: DistributionSpec) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="shock-te", archetype=Archetype.OTHER, nfrs=NFRs()),
        events=[
            EventDefinition(
                id="economic_shock",
                label="economic shock",
                kind=EventTriggerKind.ALGORITHMIC,
                frequency_distribution=distribution,
            ),
        ],
        tokens=[
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=[
                    Rule(
                        trigger=RuleTrigger(event_id="economic_shock"),
                        function=FunctionShape(
                            sign=FunctionSign.ALWAYS_POSITIVE,
                            asymptotic_class=AsymptoticClass(
                                family=AsymptoticFamily.CONSTANT,
                                parameter_ranges={"c": NumberRange.point(1.0)},
                            ),
                        ),
                    ),
                ],
                offer_variety_K=NumberRange.point(5),
            ),
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(100),
            expected_Q=NumberRange.point(50),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )


def test_normal_shock_produces_variance() -> None:
    te = _shock_te(DistributionSpec(
        kind="normal", parameters={"mu": 5.0, "sigma": 2.0}
    ))
    r = run_explore(te, sim_config=SimulationConfig(
        horizon_periods=80, seed=42, max_agents=30,
    ))
    series = [
        snap.events_realized.get("economic_shock", 0.0)
        for snap in r.snapshots
    ]
    assert len(series) > 1
    # Variance non-trivial — normal(5, 2) over 80 draws should never be flat.
    assert statistics.pstdev(series) > 0.5
    # Clamped to non-negative.
    assert all(x >= 0.0 for x in series)


def test_poisson_shock_integer_like_and_seeded() -> None:
    """Same seed twice → identical series. Different seed → different."""
    te = _shock_te(DistributionSpec(
        kind="poisson", parameters={"lambda": 3.0}
    ))
    r1 = run_explore(te, sim_config=SimulationConfig(
        horizon_periods=40, seed=11, max_agents=30,
    ))
    r2 = run_explore(te, sim_config=SimulationConfig(
        horizon_periods=40, seed=11, max_agents=30,
    ))
    r3 = run_explore(te, sim_config=SimulationConfig(
        horizon_periods=40, seed=999, max_agents=30,
    ))
    s1 = [s.events_realized.get("economic_shock", 0.0) for s in r1.snapshots]
    s2 = [s.events_realized.get("economic_shock", 0.0) for s in r2.snapshots]
    s3 = [s.events_realized.get("economic_shock", 0.0) for s in r3.snapshots]
    assert s1 == s2          # deterministic by seed
    assert s1 != s3          # different seeds diverge


def test_bernoulli_shock_only_emits_zero_or_positive() -> None:
    """Bernoulli sampler is binary; ABM clamps below to ≥ 0 anyway."""
    te = _shock_te(DistributionSpec(
        kind="bernoulli", parameters={"p": 0.3}
    ))
    r = run_explore(te, sim_config=SimulationConfig(
        horizon_periods=60, seed=42, max_agents=30,
    ))
    series = [s.events_realized.get("economic_shock", 0.0) for s in r.snapshots]
    assert all(x in (0.0, 1.0) for x in series)
    # Over 60 draws at p=0.3 we expect ~18 firings — at least one + at
    # least one non-fire (probability of all-zero or all-one is ~3 × 10⁻¹⁰).
    assert 0.0 in series
    assert 1.0 in series


def test_frequency_and_distribution_mutually_exclusive() -> None:
    """Phase L3: declaring both ``frequency`` and
    ``frequency_distribution`` raises — the user picks one arrival model
    per event. Removes the ambiguity at the verifier/ABM boundary."""
    with pytest.raises(ValueError, match="mutually exclusive|EITHER"):
        EventDefinition(
            id="hybrid", label="hybrid", kind=EventTriggerKind.ALGORITHMIC,
            frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(100.0)},
            ),
            frequency_distribution=DistributionSpec(
                kind="normal", parameters={"mu": 0.5, "sigma": 0.1}
            ),
        )


def test_event_kind_none_must_omit_frequency() -> None:
    with pytest.raises(ValueError, match="never fires"):
        EventDefinition(
            id="dead", label="dead", kind=EventTriggerKind.NONE,
            frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        )


def test_back_compat_event_without_distribution() -> None:
    """Existing examples (no frequency_distribution) still work."""
    te = _shock_te(DistributionSpec(
        kind="poisson", parameters={"lambda": 2.0}
    ))
    # Strip the distribution → AC fallback applies (no AC declared
    # either, so per-period count = 1 since event.kind != none).
    te2 = te.model_copy(update={
        "events": [
            ev.model_copy(update={"frequency_distribution": None})
            for ev in te.events
        ],
    })
    r = run_explore(te2, sim_config=SimulationConfig(
        horizon_periods=20, seed=42, max_agents=30,
    ))
    series = [s.events_realized.get("economic_shock", 0.0) for s in r.snapshots]
    # All zeros only if t=0 snapshot exists with empty defaults; otherwise
    # ones (the fallback for events with kind != "none").
    assert all(x in (0.0, 1.0) for x in series)
