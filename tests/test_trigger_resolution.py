"""Phase-H regression — trigger kinds and frequencies resolved through
the events catalog.

These tests pin the resolver-first migration: every consumer that used
to read ``rule.trigger.kind`` / ``rule.trigger.event_frequency``
directly must produce the SAME analysis for a rule that references a
catalog event as it does for the equivalent legacy inline trigger.

The FM4 case is the historical bug: catalog-style specs (the webapp's
output format) silently received NOT_APPLICABLE because the
applicability gate never resolved ``event_id`` → event kind, and the
catalog enum spells the behavioral kind "behavioral" while the legacy
enum spells it "behavioral_event".
"""

from __future__ import annotations

import pytest

from schema import (
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    CirculationSpeed,
    ContributionVerification,
    ControllingActor,
    DistributionSpec,
    EventDefinition,
    EventOccurrence,
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
from verifier.conditions import ConditionStatus, evaluate_condition
from verifier.events_resolver import resolve_trigger
from verifier.failure_modes.fm1_oversupply import _declared_emission_upper_bound
from verifier.risk import _token_E_midpoint
from verifier.simulate.trajectory import _rule_base_rate_at


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _const(v: float) -> AsymptoticClass:
    return AsymptoticClass(
        family=AsymptoticFamily.CONSTANT,
        parameter_ranges={"c": NumberRange.point(v)},
    )


def _fn(v: float) -> FunctionShape:
    return FunctionShape(sign=FunctionSign.ALWAYS_POSITIVE, asymptotic_class=_const(v))


def _agents() -> list[AgentType]:
    ht = HoldingTimeDistribution(expected_periods=NumberRange(min=2.0, max=4.0))
    return [
        AgentType(id="worker", fraction=0.5, expected_holding_time=ht, role=AgentRole.CONTRIBUTOR),
        AgentType(id="user", fraction=0.5, expected_holding_time=ht, role=AgentRole.CONSUMER),
    ]


def _catalog_te(
    *,
    events: list[EventDefinition],
    emission_rules: list[Rule],
    burn_rules: list[Rule] | None = None,
    redemption=RedemptionMechanism.SPECIFIC_GOODS_OR_SERVICES,
    nfrs: NFRs | None = None,
) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=nfrs or NFRs()),
        tokens=[
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=emission_rules,
                burn_rules=burn_rules or [],
                offer_variety_K=NumberRange(min=10.0, max=10.0),
                contribution_verification=ContributionVerification.PEER_VERIFICATION,
                redemption_mechanism=redemption,
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange(min=0.5, max=0.5),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=_agents(),
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
            sanction_structure=SanctionStructure(kind=SanctionKind.WARNING),
        ),
        events=events,
    )


def _event(eid: str, kind: EventTriggerKind, freq: float | None = None) -> EventDefinition:
    return EventDefinition(
        id=eid,
        label=f"{eid}_label",
        kind=kind,
        frequency=_const(freq) if freq is not None else None,
    )


def _rule_for(eid: str, amount: float = 1.0) -> Rule:
    return Rule(trigger=RuleTrigger(event_id=eid), function=_fn(amount))


def _verdict(report, fm: str):
    return next(v for v in report.verdicts if v.failure_mode.startswith(fm))


# ---------------------------------------------------------------------------
# FM4 applicability — the historical bug
# ---------------------------------------------------------------------------


def test_fm4_applicable_with_behavioral_catalog_event() -> None:
    """A catalog event with kind=behavioral makes FM4 applicable.

    This is the exact NLAB4CIT / cascina / time_bank shape that was
    wrongly skipped: rule → event_id → event(kind=behavioral)."""
    te = _catalog_te(
        events=[_event("work", EventTriggerKind.BEHAVIORAL, freq=1.0)],
        emission_rules=[_rule_for("work")],
    )
    v = _verdict(verify(te), "FM4")
    assert v.status != Status.NOT_APPLICABLE, v.explanation


def test_fm4_applicable_with_physical_flow_catalog_event() -> None:
    te = _catalog_te(
        events=[_event("deliver", EventTriggerKind.PHYSICAL_RESOURCE_FLOW, freq=1.0)],
        emission_rules=[_rule_for("deliver")],
    )
    v = _verdict(verify(te), "FM4")
    assert v.status != Status.NOT_APPLICABLE, v.explanation


def test_fm4_not_applicable_with_time_based_catalog_event() -> None:
    """Time-based emission is NOT a contribution economy — the catalog
    path must preserve the legitimate not-applicable case."""
    te = _catalog_te(
        events=[_event("tick", EventTriggerKind.TIME_BASED, freq=1.0)],
        emission_rules=[_rule_for("tick")],
    )
    v = _verdict(verify(te), "FM4")
    assert v.status == Status.NOT_APPLICABLE


def test_fm4_catalog_and_legacy_specs_agree() -> None:
    """The same economy in catalog and legacy form must yield the same
    FM4 status — the dual-form invariant for the applicability gate."""
    te_catalog = _catalog_te(
        events=[_event("work", EventTriggerKind.BEHAVIORAL, freq=1.0)],
        emission_rules=[_rule_for("work")],
    )
    legacy_rule = Rule(
        trigger=RuleTrigger(
            kind="behavioral_event",
            event_frequency=_const(1.0),
        ),
        function=_fn(1.0),
    )
    te_legacy = _catalog_te(events=[], emission_rules=[legacy_rule])
    s_cat = _verdict(verify(te_catalog), "FM4").status
    s_leg = _verdict(verify(te_legacy), "FM4").status
    assert s_cat == s_leg


# ---------------------------------------------------------------------------
# FM3 burn-quality classification
# ---------------------------------------------------------------------------


def test_fm3_rule_driven_catalog_burn_flagged_as_structurally_weak() -> None:
    te = _catalog_te(
        events=[
            _event("mint_ev", EventTriggerKind.BEHAVIORAL, freq=1.0),
            _event("sched_burn", EventTriggerKind.RULE_DRIVEN, freq=1.0),
        ],
        emission_rules=[_rule_for("mint_ev", 2.0)],
        burn_rules=[_rule_for("sched_burn", 1.0)],
    )
    v = _verdict(verify(te), "FM3")
    assert "rule-driven" in v.explanation


def test_fm3_demand_driven_catalog_burn_not_flagged_rule_driven() -> None:
    te = _catalog_te(
        events=[
            _event("mint_ev", EventTriggerKind.BEHAVIORAL, freq=1.0),
            _event("redeem_ev", EventTriggerKind.DEMAND_DRIVEN, freq=1.0),
        ],
        emission_rules=[_rule_for("mint_ev", 2.0)],
        burn_rules=[_rule_for("redeem_ev", 1.0)],
    )
    v = _verdict(verify(te), "FM3")
    assert "rule-driven (fixed schedule)" not in v.explanation


# ---------------------------------------------------------------------------
# Coherence checks C1 / C6
# ---------------------------------------------------------------------------


def test_c1_p2p_redemption_plus_catalog_demand_burn_is_flagged() -> None:
    te = _catalog_te(
        events=[
            _event("mint_ev", EventTriggerKind.BEHAVIORAL, freq=1.0),
            _event("redeem_ev", EventTriggerKind.DEMAND_DRIVEN, freq=1.0),
        ],
        emission_rules=[_rule_for("mint_ev", 2.0)],
        burn_rules=[_rule_for("redeem_ev", 1.0)],
        redemption=RedemptionMechanism.PEER_TO_PEER_TRANSFER,
    )
    report = verify(te)
    assert any(
        i.severity == "error" and "burn_rules" in i.location and "redemption" in i.location
        for i in report.coherence_issues
    ), [(i.severity, i.location) for i in report.coherence_issues]


def test_c6_retain_value_plus_catalog_expiry_burn_is_flagged() -> None:
    te = _catalog_te(
        events=[
            _event("mint_ev", EventTriggerKind.BEHAVIORAL, freq=1.0),
            _event("expire_ev", EventTriggerKind.EXPIRY, freq=1.0),
        ],
        emission_rules=[_rule_for("mint_ev", 2.0)],
        burn_rules=[_rule_for("expire_ev", 1.0)],
        nfrs=NFRs(circulation_speed=CirculationSpeed.RETAIN_VALUE),
    )
    report = verify(te)
    assert any(
        i.severity == "warn" and "circulation_speed" in i.location
        for i in report.coherence_issues
    ), [(i.severity, i.location) for i in report.coherence_issues]


# ---------------------------------------------------------------------------
# Frequency resolution in the numeric layers
# ---------------------------------------------------------------------------


def _freq_te() -> TokenEconomy:
    """One emission rule: 10 tokens per event × 5 events/period = 50/period."""
    return _catalog_te(
        events=[_event("work", EventTriggerKind.BEHAVIORAL, freq=5.0)],
        emission_rules=[_rule_for("work", 10.0)],
    )


def test_fm1_declared_upper_bound_resolves_catalog_frequency() -> None:
    te = _freq_te()
    assert _declared_emission_upper_bound(te.tokens[0], te) == pytest.approx(50.0)


def test_risk_midpoint_resolves_catalog_frequency() -> None:
    te = _freq_te()
    assert _token_E_midpoint(te, te.tokens[0]) == pytest.approx(50.0)


def test_trajectory_rate_resolves_catalog_frequency() -> None:
    te = _freq_te()
    rate = _rule_base_rate_at(te.tokens[0].emission_rules[0], 1.0, te=te)
    assert rate == pytest.approx(50.0)


def test_abm_stochastic_tuple_carries_catalog_frequency() -> None:
    """The engine pre-resolves the event frequency when classifying
    stochastic rules, so the per-period pool path multiplies by the
    catalog frequency (not the always-None inline field)."""
    from verifier.abm.engine import _build_initial_state
    from verifier.abm.samplers import Sampler

    stochastic_rule = Rule(
        trigger=RuleTrigger(event_id="work"),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE,
            asymptotic_class=_const(0.0),
            distribution=DistributionSpec(kind="normal", parameters={"mu": 4.0, "sigma": 0.0}),
        ),
    )
    te = _catalog_te(
        events=[_event("work", EventTriggerKind.BEHAVIORAL, freq=3.0)],
        emission_rules=[stochastic_rule],
    )
    _state, params = _build_initial_state(te, Sampler(seed=1), None, effective_agent_cap=5)
    stoch = params["stochastic_rules"]
    assert len(stoch) == 1
    token_id, side, _rule, freq_ac, freq_dist = stoch[0]
    assert (token_id, side) == ("T", "E")
    assert freq_ac is not None and freq_ac.parameter_ranges["c"].max == 3.0
    assert freq_dist is None

    from verifier.abm.actions import prepare_pools

    pools = prepare_pools({}, {"T": {"E": 0.0, "B": 0.0}}, stoch, Sampler(seed=2), {})
    # normal(mu=4, sigma=0) × frequency 3 = 12, deterministic.
    assert pools["T"]["E"] == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# EventOccurrence legacy matching through the catalog
# ---------------------------------------------------------------------------


def test_event_occurrence_matches_catalog_label() -> None:
    te = _freq_te()
    cond = EventOccurrence(source_token="T", source_event="work_label")
    assert evaluate_condition(cond, te) == ConditionStatus.ALWAYS


def test_event_occurrence_matches_catalog_kind_value() -> None:
    te = _freq_te()
    cond = EventOccurrence(source_token="T", source_event="behavioral")
    assert evaluate_condition(cond, te) == ConditionStatus.ALWAYS


def test_event_occurrence_unmatched_stays_conservative() -> None:
    te = _freq_te()
    cond = EventOccurrence(source_token="T", source_event="nonexistent_thing")
    assert evaluate_condition(cond, te) == ConditionStatus.EVER


# ---------------------------------------------------------------------------
# Resolver predicate unit checks (the vocabulary mapping itself)
# ---------------------------------------------------------------------------


def test_resolver_predicates_cover_both_vocabularies() -> None:
    te_cat = _catalog_te(
        events=[_event("work", EventTriggerKind.BEHAVIORAL, freq=1.0)],
        emission_rules=[_rule_for("work")],
    )
    rt_cat = resolve_trigger(te_cat.tokens[0].emission_rules[0], te_cat)
    assert rt_cat.kind == "behavioral" and rt_cat.is_contribution

    legacy_rule = Rule(
        trigger=RuleTrigger(kind="behavioral_event", event_frequency=_const(1.0)),
        function=_fn(1.0),
    )
    te_leg = _catalog_te(events=[], emission_rules=[legacy_rule])
    rt_leg = resolve_trigger(te_leg.tokens[0].emission_rules[0], te_leg)
    # Legacy input canonicalizes at load: the trigger now references a
    # synthesized catalog event whose kind uses the unified vocabulary.
    assert rt_leg.kind == "behavioral" and rt_leg.is_contribution
    assert rt_leg.event_id is not None and rt_leg.event_id.startswith("_auto_")
