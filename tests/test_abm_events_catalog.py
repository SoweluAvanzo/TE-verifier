"""Phase H3 — ABM realizes the events catalog + non-tokenized asset
state per period."""

from __future__ import annotations

import pytest

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
from verifier.abm.engine import _build_initial_state, _step_state
from verifier.abm.samplers import Sampler


def _te(events=None, assets=None, mint_event_id=None):
    trigger = (
        RuleTrigger(event_id=mint_event_id) if mint_event_id else
        RuleTrigger(kind=EmissionTriggerKind.TIME_BASED)
    )
    return TokenEconomy(
        meta=Meta(name="h3-abm", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[Rule(
                trigger=trigger,
                function=FunctionShape(
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(5.0)},
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
        events=events or [],
        non_tokenized_assets=assets or [],
    )


def test_event_realization_populates_state() -> None:
    event = EventDefinition(
        id="svc",
        label="service",
        kind=EventTriggerKind.BEHAVIORAL,
        frequency=AsymptoticClass(
            family=AsymptoticFamily.CONSTANT,
            parameter_ranges={"c": NumberRange.point(20.0)},
        ),
    )
    te = _te(events=[event])
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    state = _step_state(state, params)
    assert state["events_realized"]["svc"] == pytest.approx(20.0)


def test_event_with_no_frequency_fires_once_per_period() -> None:
    event = EventDefinition(
        id="tb",
        label="time-based event",
        kind=EventTriggerKind.TIME_BASED,
        frequency=None,
    )
    te = _te(events=[event])
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    state = _step_state(state, params)
    assert state["events_realized"]["tb"] == pytest.approx(1.0)


def test_event_occurrence_condition_reads_realized_firings() -> None:
    """The regime/condition evaluator must see the realized event count
    when EventOccurrence references an event by id."""
    from verifier.abm.regimes import is_condition_active
    event = EventDefinition(
        id="svc",
        label="service",
        kind=EventTriggerKind.BEHAVIORAL,
        frequency=AsymptoticClass(
            family=AsymptoticFamily.CONSTANT,
            parameter_ranges={"c": NumberRange.point(10.0)},
        ),
    )
    te = _te(events=[event])
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    # Before stepping → no realized firings yet.
    assert not is_condition_active(EventOccurrence(event_id="svc"), state)
    state = _step_state(state, params)
    assert is_condition_active(EventOccurrence(event_id="svc"), state)


# ---------------------------------------------------------------------------
# Non-tokenized assets
# ---------------------------------------------------------------------------


def test_asset_creation_increments_count() -> None:
    asset = NonTokenizedAsset(
        id="coupon_item",
        label="local-retailer coupon",
        kind=AssetKind.GOOD,
        creation=FunctionShape(
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(5.0)},
            ),
        ),
    )
    te = _te(assets=[asset])
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    state = _step_state(state, params)
    state = _step_state(state, params)
    assert state["assets"]["coupon_item"]["count"] == pytest.approx(10.0)
    assert state["assets"]["coupon_item"]["created"] == pytest.approx(10.0)


def test_unique_asset_spawns_only_once() -> None:
    asset = NonTokenizedAsset(
        id="artwork",
        label="curated piece",
        kind=AssetKind.NFT,
        unique=True,
        creation=FunctionShape(
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
    )
    te = _te(assets=[asset])
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    for _ in range(10):
        state = _step_state(state, params)
    # NFT spawns once, never again.
    assert state["assets"]["artwork"]["count"] == pytest.approx(1.0)


def test_asset_consumption_decrements_count() -> None:
    asset = NonTokenizedAsset(
        id="ticket",
        label="event ticket",
        kind=AssetKind.GOOD,
        creation=FunctionShape(
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(5.0)},
            ),
        ),
        consumption=FunctionShape(
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(3.0)},
            ),
        ),
    )
    te = _te(assets=[asset])
    sampler = Sampler(seed=1)
    state, params = _build_initial_state(te, sampler, None)
    state = _step_state(state, params)
    # Net = 5 created - 3 consumed = 2.
    assert state["assets"]["ticket"]["count"] == pytest.approx(2.0)
    assert state["assets"]["ticket"]["consumed"] == pytest.approx(3.0)
