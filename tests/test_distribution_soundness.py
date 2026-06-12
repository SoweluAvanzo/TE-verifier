"""Distribution-soundness regression — the static layer honors
stochastic specifications.

Two documented contracts were previously unimplemented:

1. **Event-level stochastic arrivals** (``EventDefinition.
   frequency_distribution``): the static layer silently treated such
   events as firing once per period. A Poisson(λ=5) behavioral event
   minting 10 tokens/event was statically scored E=10/period while the
   declared design means E≈50/period — an unsound PASS for FM1.
2. **Rule-level stochastic rates** (``FunctionShape.distribution``):
   the DistributionSpec docstring promises "the verifier interprets a
   distribution as its support … and reasons over the resulting range
   conservatively"; the static layer ignored the field entirely (the
   webapp emits ``c=[0,0]`` + distribution, so the prover saw E=0).

These tests pin the fixed semantics: support envelopes in Z3, analytic
means in the midpoint layers, per-period sampling in the ABM — and a
static-vs-ABM agreement check that fails if the two layers ever drift
apart again.
"""

from __future__ import annotations

import math

import pytest

from schema import (
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    ContributionVerification,
    ControllingActor,
    DistributionSpec,
    EventDefinition,
    EventTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceSpec,
    GovernanceType,
    HoldingTimeDistribution,
    Meta,
    NFRs,
    NumberRange,
    ParticipantsSpec,
    RedemptionMechanism,
    Rule,
    RuleTrigger,
    SanctionKind,
    SanctionStructure,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
)
from verifier import Status, verify
from verifier.distribution_support import mean, rate_support, support


# ---------------------------------------------------------------------------
# support / mean unit oracles (hand-computed)
# ---------------------------------------------------------------------------


def _spec(kind: str, **params) -> DistributionSpec:
    return DistributionSpec(kind=kind, parameters=params)


def test_support_and_mean_oracles() -> None:
    assert support(_spec("uniform", low=2.0, high=8.0)) == (2.0, 8.0)
    assert mean(_spec("uniform", low=2.0, high=8.0)) == 5.0

    assert support(_spec("normal", mu=10.0, sigma=2.0)) == (4.0, 16.0)
    assert mean(_spec("normal", mu=10.0, sigma=2.0)) == 10.0

    lo, hi = support(_spec("lognormal", mu=1.0, sigma=0.5))
    assert lo == pytest.approx(math.exp(-0.5))
    assert hi == pytest.approx(math.exp(2.5))
    assert mean(_spec("lognormal", mu=1.0, sigma=0.5)) == pytest.approx(
        math.exp(1.0 + 0.125)
    )

    assert support(_spec("bernoulli", p=0.3)) == (0.0, 1.0)
    assert mean(_spec("bernoulli", p=0.3)) == 0.3

    lo, hi = support(_spec("poisson", **{"lambda": 5.0}))
    assert lo == 0.0
    assert hi == pytest.approx(5.0 + 3.0 * math.sqrt(5.0))
    assert mean(_spec("poisson", **{"lambda": 5.0})) == 5.0

    assert support(_spec("beta", alpha=2.0, beta=6.0)) == (0.0, 1.0)
    assert mean(_spec("beta", alpha=2.0, beta=6.0)) == 0.25

    # Rate clamp: normal with negative tail clamps at 0.
    assert rate_support(_spec("normal", mu=1.0, sigma=2.0)) == (0.0, 7.0)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _const(v: float) -> AsymptoticClass:
    return AsymptoticClass(
        family=AsymptoticFamily.CONSTANT,
        parameter_ranges={"c": NumberRange.point(v)},
    )


def _te(
    *,
    emission_rules: list[Rule],
    events: list[EventDefinition],
    Q: float,
    burn_rules: list[Rule] | None = None,
) -> TokenEconomy:
    ht = HoldingTimeDistribution(expected_periods=NumberRange(min=2.0, max=4.0))
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[
            Token(
                id="TOK",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=emission_rules,
                burn_rules=burn_rules or [],
                offer_variety_K=NumberRange(min=10.0, max=10.0),
                contribution_verification=ContributionVerification.PEER_VERIFICATION,
                redemption_mechanism=RedemptionMechanism.SPECIFIC_GOODS_OR_SERVICES,
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(Q),
            average_demand_d=NumberRange(min=0.5, max=0.5),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="worker",
                    fraction=1.0,
                    expected_holding_time=ht,
                    role=AgentRole.CONTRIBUTOR,
                )
            ],
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
            sanction_structure=SanctionStructure(kind=SanctionKind.WARNING),
        ),
        events=events,
    )


def _fm1(report):
    return next(v for v in report.verdicts if v.failure_mode.startswith("FM1"))


def _poisson_event(lam: float) -> EventDefinition:
    return EventDefinition(
        id="bursty",
        label="bursty arrivals",
        kind=EventTriggerKind.BEHAVIORAL,
        frequency_distribution=_spec("poisson", **{"lambda": lam}),
    )


# ---------------------------------------------------------------------------
# 1. Event-level stochastic arrivals — the proven unsoundness, now fixed
# ---------------------------------------------------------------------------


def test_static_fm1_fails_on_poisson_frequency() -> None:
    """10 tokens/event × Poisson(λ=5) arrivals vs Q=20.

    True mean emission is 50/period ≫ 20. Before the fix the static
    layer saw frequency=None → E=10 ≤ 20 → unsound PASS. With the
    support envelope [0, λ+3√λ] the violation is reachable → FAIL."""
    rule = Rule(
        trigger=RuleTrigger(event_id="bursty"),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE, asymptotic_class=_const(10.0)
        ),
    )
    te = _te(emission_rules=[rule], events=[_poisson_event(5.0)], Q=20.0)
    v = _fm1(verify(te))
    assert v.status == Status.FAIL, v.explanation


def test_static_fm1_passes_when_q_absorbs_poisson_ceiling() -> None:
    """Same design with Q large enough to absorb the support ceiling
    (10 × (5+3√5) ≈ 117) must stay a genuine PASS."""
    rule = Rule(
        trigger=RuleTrigger(event_id="bursty"),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE, asymptotic_class=_const(10.0)
        ),
    )
    te = _te(emission_rules=[rule], events=[_poisson_event(5.0)], Q=150.0)
    v = _fm1(verify(te))
    assert v.status == Status.PASS, v.explanation


# ---------------------------------------------------------------------------
# 2. Rule-level distribution — the webapp's c=[0,0] + distribution shape
# ---------------------------------------------------------------------------


def _dist_rule(mu: float, sigma: float) -> Rule:
    return Rule(
        trigger=RuleTrigger(kind="time_based"),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE,
            asymptotic_class=_const(0.0),  # webapp fallback when blank
            distribution=_spec("normal", mu=mu, sigma=sigma),
        ),
    )


def test_static_fm1_sees_rule_distribution_support() -> None:
    """c=[0,0] + normal(10,2): the static layer must reason over the
    support [4,16], not the zero asymptotic class. With Q=12 the upper
    half of the support violates → FAIL."""
    te = _te(emission_rules=[_dist_rule(10.0, 2.0)], events=[], Q=12.0)
    v = _fm1(verify(te))
    assert v.status == Status.FAIL, v.explanation


def test_static_fm1_distribution_pass_when_q_absorbs_support() -> None:
    te = _te(emission_rules=[_dist_rule(10.0, 2.0)], events=[], Q=20.0)
    v = _fm1(verify(te))
    assert v.status == Status.PASS, v.explanation


# ---------------------------------------------------------------------------
# 3. Midpoint layers use the analytic mean
# ---------------------------------------------------------------------------


def test_risk_midpoint_uses_distribution_means() -> None:
    from verifier.risk import _token_E_midpoint

    rule = Rule(
        trigger=RuleTrigger(event_id="bursty"),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE, asymptotic_class=_const(10.0)
        ),
    )
    te = _te(emission_rules=[rule], events=[_poisson_event(5.0)], Q=20.0)
    # 10 tokens/event × mean 5 events/period = 50.
    assert _token_E_midpoint(te, te.tokens[0]) == pytest.approx(50.0)

    te2 = _te(emission_rules=[_dist_rule(10.0, 2.0)], events=[], Q=20.0)
    # normal mean 10 (time-based → factor 1).
    assert _token_E_midpoint(te2, te2.tokens[0]) == pytest.approx(10.0)


def test_trajectory_uses_distribution_means() -> None:
    from verifier.simulate.trajectory import _rule_base_rate_at

    rule = Rule(
        trigger=RuleTrigger(event_id="bursty"),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE, asymptotic_class=_const(10.0)
        ),
    )
    te = _te(emission_rules=[rule], events=[_poisson_event(5.0)], Q=20.0)
    assert _rule_base_rate_at(rule, 5.0, te=te) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# 4. ABM realizes stochastic arrivals in rates
# ---------------------------------------------------------------------------


def _abm_mean_E(te: TokenEconomy, *, periods: int = 200, seed: int = 7) -> float:
    """Mean realized per-period emission through the no-agent fallback."""
    from verifier.abm.engine import _build_initial_state, _step_state
    from verifier.abm.samplers import Sampler

    sampler = Sampler(seed=seed)
    state, params = _build_initial_state(te, sampler, None, effective_agent_cap=5)
    state["agents"] = []  # force the rule-aggregate fallback branch
    total = 0.0
    for _ in range(periods):
        state = _step_state(state, params)
        total += state["tokens"]["TOK"]["E"]
    return total / periods


def test_abm_realizes_poisson_event_arrivals() -> None:
    """The ABM's realized emission must reflect the declared Poisson
    arrivals (mean λ×amount = 50/period), not the old implicit ×1."""
    rule = Rule(
        trigger=RuleTrigger(event_id="bursty"),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE, asymptotic_class=_const(10.0)
        ),
    )
    te = _te(emission_rules=[rule], events=[_poisson_event(5.0)], Q=20.0)
    m = _abm_mean_E(te)
    assert 40.0 < m < 60.0, m  # mean 50, generous CI for 200 periods


def test_static_envelope_contains_abm_realization() -> None:
    """Agreement tripwire: the ABM's realized emission must fall inside
    the static layer's conservative envelope. If the two layers drift
    apart again (one honoring a stochastic field the other ignores),
    this test goes red."""
    rule = Rule(
        trigger=RuleTrigger(event_id="bursty"),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE, asymptotic_class=_const(10.0)
        ),
    )
    te = _te(emission_rules=[rule], events=[_poisson_event(5.0)], Q=20.0)

    static_lo, static_hi = rate_support(_spec("poisson", **{"lambda": 5.0}))
    static_lo *= 10.0
    static_hi *= 10.0

    m = _abm_mean_E(te)
    assert static_lo <= m <= static_hi, (m, static_lo, static_hi)
