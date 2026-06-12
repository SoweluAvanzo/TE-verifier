"""Phase-H1: EventDefinition + NonTokenizedAsset schema additions.

Verifies:
  * EventDefinition can be declared at TE level.
  * Rule trigger can reference an event by id; mutual exclusion with
    legacy kind/event_predicate enforced.
  * EventOccurrence condition can reference an event by id.
  * NonTokenizedAsset can be declared with creation/consumption shapes.
  * Reference validators reject dangling event_id / referenced_tokens.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schema import (
    Archetype,
    AssetKind,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    EmissionTriggerKind,
    EventDefinition,
    EventOccurrence,
    EventTriggerKind,
    FunctionShape,
    GovernanceSpec,
    GovernanceType,
    Meta,
    NFRs,
    NonTokenizedAsset,
    NumberRange,
    ParticipantsSpec,
    Rule,
    RuleTrigger,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
)


def _minimal_te(**overrides):
    base = dict(
        meta=Meta(name="h1-test", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[Rule(
                trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                function=FunctionShape(
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(10.0)},
                    ),
                ),
            )],
            burn_rules=[Rule(
                trigger=RuleTrigger(kind=BurnTriggerKind.DEMAND_DRIVEN),
                function=FunctionShape(
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(0.0)},
                    ),
                ),
            )],
            offer_variety_K=NumberRange.point(5),
        )],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(10),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )
    base.update(overrides)
    return TokenEconomy(**base)


# ---------------------------------------------------------------------------
# EventDefinition
# ---------------------------------------------------------------------------


def test_event_definition_loads_with_frequency() -> None:
    ev = EventDefinition(
        id="service",
        label="Verified service",
        kind=EventTriggerKind.BEHAVIORAL,
        frequency=AsymptoticClass(
            family=AsymptoticFamily.LINEAR,
            parameter_ranges={"b": NumberRange(min=20.0, max=180.0)},
        ),
    )
    assert ev.id == "service"
    assert ev.kind == EventTriggerKind.BEHAVIORAL


def test_te_carries_events_catalog() -> None:
    te = _minimal_te(events=[
        EventDefinition(id="e1", label="e1", kind=EventTriggerKind.TIME_BASED),
    ])
    # The declared event is carried; the fixture's legacy inline rules
    # canonicalize into synthesized ``_auto_`` events at load.
    assert te.get_event("e1").label == "e1"
    declared = [e for e in te.events if not e.id.startswith("_auto_")]
    assert len(declared) == 1
    for tok in te.tokens:
        for rule in tok.emission_rules + tok.burn_rules:
            assert rule.trigger.event_id is not None
            assert rule.trigger.kind is None


def test_unique_event_ids_enforced() -> None:
    with pytest.raises(ValidationError):
        _minimal_te(events=[
            EventDefinition(id="x", label="a", kind=EventTriggerKind.TIME_BASED),
            EventDefinition(id="x", label="b", kind=EventTriggerKind.TIME_BASED),
        ])


# ---------------------------------------------------------------------------
# RuleTrigger event_id linkage
# ---------------------------------------------------------------------------


def test_rule_can_reference_event_by_id() -> None:
    event = EventDefinition(id="mint_evt", label="…", kind=EventTriggerKind.TIME_BASED)
    rule = Rule(
        trigger=RuleTrigger(event_id="mint_evt"),
        function=FunctionShape(
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(5.0)},
            ),
        ),
    )
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[rule],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = _minimal_te(tokens=[token], events=[event])
    assert te.tokens[0].emission_rules[0].trigger.event_id == "mint_evt"


def test_rule_event_id_and_legacy_kind_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError):
        RuleTrigger(event_id="x", kind=EmissionTriggerKind.TIME_BASED)


def test_rule_without_event_id_or_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RuleTrigger()


def test_te_rejects_dangling_event_id_on_rule() -> None:
    rule = Rule(
        trigger=RuleTrigger(event_id="ghost"),
        function=FunctionShape(
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
    )
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[rule],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    with pytest.raises(ValidationError):
        _minimal_te(tokens=[token])  # no events declared


# ---------------------------------------------------------------------------
# EventOccurrence condition by event_id
# ---------------------------------------------------------------------------


def test_event_occurrence_accepts_event_id() -> None:
    cond = EventOccurrence(event_id="evt_x")
    assert cond.event_id == "evt_x"


def test_event_occurrence_legacy_path_still_works() -> None:
    cond = EventOccurrence(source_token="T", source_event="mint_evt")
    assert cond.source_token == "T"


def test_event_occurrence_requires_some_reference() -> None:
    with pytest.raises(ValidationError):
        EventOccurrence()


# ---------------------------------------------------------------------------
# NonTokenizedAsset
# ---------------------------------------------------------------------------


def test_asset_declares_unique_flag_and_creation() -> None:
    asset = NonTokenizedAsset(
        id="coupon_item",
        label="Local-retailer coupon item",
        kind=AssetKind.GOOD,
        unique=False,
        creation=FunctionShape(
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.LINEAR,
                parameter_ranges={"b": NumberRange.point(10.0)},
            ),
        ),
        redemption_cost=NumberRange(min=5.0, max=10.0),
        referenced_tokens=["T"],
    )
    assert asset.kind == AssetKind.GOOD
    assert asset.unique is False
    assert asset.referenced_tokens == ["T"]


def test_asset_unique_nft_works() -> None:
    asset = NonTokenizedAsset(
        id="artwork",
        label="Curated artwork",
        kind=AssetKind.NFT,
        unique=True,
    )
    assert asset.unique


def test_te_rejects_dangling_referenced_token_on_asset() -> None:
    asset = NonTokenizedAsset(
        id="x",
        label="x",
        kind=AssetKind.GOOD,
        referenced_tokens=["GHOST_TOKEN"],
    )
    with pytest.raises(ValidationError):
        _minimal_te(non_tokenized_assets=[asset])


def test_unique_asset_ids_enforced() -> None:
    a = NonTokenizedAsset(id="x", label="a", kind=AssetKind.GOOD)
    b = NonTokenizedAsset(id="x", label="b", kind=AssetKind.GOOD)
    with pytest.raises(ValidationError):
        _minimal_te(non_tokenized_assets=[a, b])


# ---------------------------------------------------------------------------
# H2: events catalog drives the verifier's frequency math.
# ---------------------------------------------------------------------------


def test_resolve_trigger_pulls_frequency_from_event_catalog() -> None:
    """A rule whose trigger.event_id references an event with a
    non-trivial frequency must produce that frequency through the
    resolver."""
    from verifier.events_resolver import resolve_trigger
    event = EventDefinition(
        id="svc",
        label="services",
        kind=EventTriggerKind.BEHAVIORAL,
        frequency=AsymptoticClass(
            family=AsymptoticFamily.LINEAR,
            parameter_ranges={"b": NumberRange(min=20.0, max=100.0)},
        ),
    )
    rule = Rule(
        trigger=RuleTrigger(event_id="svc"),
        function=FunctionShape(
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(2.0)},
            ),
        ),
    )
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[rule],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = _minimal_te(tokens=[token], events=[event])
    resolved = resolve_trigger(rule, te)
    assert resolved.event_id == "svc"
    assert resolved.kind == "behavioral"
    assert resolved.event_frequency is not None
    assert resolved.event_frequency.parameter_ranges["b"].max == 100.0


def test_resolve_trigger_legacy_path_unchanged() -> None:
    """Rules using the legacy inline kind/frequency keep working."""
    from verifier.events_resolver import resolve_trigger
    legacy_freq = AsymptoticClass(
        family=AsymptoticFamily.LINEAR,
        parameter_ranges={"b": NumberRange.point(50.0)},
    )
    rule = Rule(
        trigger=RuleTrigger(
            kind=EmissionTriggerKind.BEHAVIORAL_EVENT,
            event_frequency=legacy_freq,
        ),
        function=FunctionShape(
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
    )
    te = _minimal_te()
    resolved = resolve_trigger(rule, te)
    assert resolved.event_id is None
    assert resolved.kind == "behavioral_event"
    assert resolved.event_frequency is legacy_freq
