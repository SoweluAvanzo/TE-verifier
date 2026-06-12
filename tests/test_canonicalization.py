"""Load-time canonicalization of legacy triggers (Phase-H completion).

``TokenEconomy._normalize_legacy_triggers`` rewrites every legacy
inline trigger (kind / event_predicate / event_frequency) into a
synthesized ``_auto_`` EventDefinition + an ``event_id``-only trigger.
Post-load there is exactly ONE trigger vocabulary.

These tests pin: the post-load invariant on every shipped example, the
synthesis mapping (kind aliasing, label and frequency relocation, id
collision handling), verdict equivalence between the two authoring
styles, and a seeded ABM differential run guarding against
double-counted frequencies.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from schema import (
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    ContributionVerification,
    ControllingActor,
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
from verifier import verify

EXAMPLES = sorted(pathlib.Path(__file__).parent.parent.glob("examples/*.yaml"))


def _load(path: pathlib.Path) -> TokenEconomy:
    return TokenEconomy.model_validate(yaml.safe_load(path.read_text()))


# ---------------------------------------------------------------------------
# Post-load invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_every_example_canonicalizes(path: pathlib.Path) -> None:
    te = _load(path)
    known = {e.id for e in te.events}
    for token in te.tokens:
        for rule in token.emission_rules + token.burn_rules:
            assert rule.trigger.event_id is not None, (path.stem, token.id)
            assert rule.trigger.kind is None
            assert rule.trigger.event_id in known


# ---------------------------------------------------------------------------
# Synthesis mapping
# ---------------------------------------------------------------------------


def _const(v: float) -> AsymptoticClass:
    return AsymptoticClass(
        family=AsymptoticFamily.CONSTANT,
        parameter_ranges={"c": NumberRange.point(v)},
    )


def _fn(v: float) -> FunctionShape:
    return FunctionShape(sign=FunctionSign.ALWAYS_POSITIVE, asymptotic_class=_const(v))


def _te(emission_rules, events=None, burn_rules=None) -> TokenEconomy:
    ht = HoldingTimeDistribution(expected_periods=NumberRange(min=2.0, max=4.0))
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[
            Token(
                id="T",
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
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange(min=0.5, max=0.5),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="worker", fraction=1.0, expected_holding_time=ht,
                    role=AgentRole.CONTRIBUTOR,
                )
            ],
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
            sanction_structure=SanctionStructure(kind=SanctionKind.WARNING),
        ),
        events=events or [],
    )


def test_synthesis_maps_behavioral_and_moves_frequency() -> None:
    rule = Rule(
        trigger=RuleTrigger(
            kind="behavioral_event",
            event_predicate="service_delivered",
            event_frequency=_const(5.0),
        ),
        function=_fn(10.0),
    )
    te = _te([rule])
    canon = te.tokens[0].emission_rules[0]
    ev = te.get_event(canon.trigger.event_id)
    # Kind aliased to the unified vocabulary.
    assert ev.kind == EventTriggerKind.BEHAVIORAL
    # Label preserves the legacy predicate (EventOccurrence matching).
    assert ev.label == "service_delivered"
    # Frequency MOVED into the catalog (not duplicated on the trigger).
    assert ev.frequency is not None
    assert ev.frequency.parameter_ranges["c"].max == 5.0
    assert canon.trigger.event_frequency is None
    assert canon.trigger.kind is None


def test_synthesis_avoids_id_collisions() -> None:
    """A user-declared event already named like the auto id must not
    collide with the synthesized one."""
    rule = Rule(trigger=RuleTrigger(kind="behavioral_event"), function=_fn(1.0))
    taken = EventDefinition(
        id="_auto_T_emission_rules_0",
        label="taken",
        kind=EventTriggerKind.TIME_BASED,
    )
    te = _te([rule], events=[taken])
    ids = [e.id for e in te.events]
    assert len(ids) == len(set(ids))
    canon = te.tokens[0].emission_rules[0]
    assert canon.trigger.event_id != "taken"
    assert te.get_event(canon.trigger.event_id).kind == EventTriggerKind.BEHAVIORAL


def test_catalog_style_spec_passes_through_unchanged() -> None:
    ev = EventDefinition(id="work", label="work", kind=EventTriggerKind.BEHAVIORAL,
                         frequency=_const(2.0))
    rule = Rule(trigger=RuleTrigger(event_id="work"), function=_fn(1.0))
    te = _te([rule], events=[ev])
    assert [e.id for e in te.events] == ["work"]
    assert te.tokens[0].emission_rules[0].trigger.event_id == "work"


# ---------------------------------------------------------------------------
# Dual-form equivalence: verdicts and seeded ABM trajectories
# ---------------------------------------------------------------------------


def _legacy_form() -> TokenEconomy:
    emit = Rule(
        trigger=RuleTrigger(
            kind="behavioral_event",
            event_predicate="work",
            event_frequency=_const(3.0),
        ),
        function=_fn(10.0),
    )
    burn = Rule(
        trigger=RuleTrigger(kind="demand_driven", event_predicate="redeem"),
        function=_fn(5.0),
    )
    return _te([emit], burn_rules=[burn])


def _catalog_form() -> TokenEconomy:
    events = [
        EventDefinition(id="ev_work", label="work", kind=EventTriggerKind.BEHAVIORAL,
                        frequency=_const(3.0)),
        EventDefinition(id="ev_redeem", label="redeem",
                        kind=EventTriggerKind.DEMAND_DRIVEN),
    ]
    emit = Rule(trigger=RuleTrigger(event_id="ev_work"), function=_fn(10.0))
    burn = Rule(trigger=RuleTrigger(event_id="ev_redeem"), function=_fn(5.0))
    return _te([emit], events=events, burn_rules=[burn])


def test_dual_form_verdict_equivalence() -> None:
    """The same economy authored legacy-style and catalog-style must
    produce identical verdicts, statuses, and risk bands."""
    r_leg = verify(_legacy_form())
    r_cat = verify(_catalog_form())
    leg = {(v.failure_mode, v.subject): (v.status, v.risk_level) for v in r_leg.verdicts}
    cat = {(v.failure_mode, v.subject): (v.status, v.risk_level) for v in r_cat.verdicts}
    assert leg == cat
    assert r_leg.summary == r_cat.summary


def test_dual_form_abm_trajectory_equivalence() -> None:
    """Seeded ABM differential: both authoring styles of the same
    economy must produce identical realized trajectories — guards
    against double-counted frequencies in the synthesis (frequency
    must be MOVED to the catalog, not copied)."""
    from verifier.abm.engine import _build_initial_state, _step_state
    from verifier.abm.samplers import Sampler

    def run(te: TokenEconomy) -> list[tuple[float, float, float]]:
        sampler = Sampler(seed=42)
        state, params = _build_initial_state(te, sampler, None, effective_agent_cap=5)
        state["agents"] = []  # rule-aggregate branch: deterministic given seed
        out = []
        for _ in range(30):
            state = _step_state(state, params)
            tok = state["tokens"]["T"]
            out.append((tok["M"], tok["E"], tok["B"]))
        return out

    assert run(_legacy_form()) == run(_catalog_form())
