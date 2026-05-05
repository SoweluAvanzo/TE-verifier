"""Phase 5 — archetype routing, cross-token flows, topology correction,
NFR reweighting.

Each subsystem gets a synthetic IR with a hand-computed expected
verdict, plus regression assertions that the case-study verdict matrix
is unchanged with default config.
"""

from __future__ import annotations

import pytest

from schema import (
    AgentRole,
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    CirculationSpeed,
    ContributionVerification,
    ControllingActor,
    CrossTokenAction,
    CrossTokenFlow,
    EmissionTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceMaturity,
    GovernanceSpec,
    GovernanceType,
    HoldingIncentiveMechanism,
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
from verifier.config import VerifierConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emission_rule(c: float = 1.0) -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=EmissionTriggerKind.BEHAVIORAL_EVENT,
            event_frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(c)},
            ),
        ),
    )


def _basic_te(
    *,
    archetype: Archetype = Archetype.OTHER,
    nfrs: NFRs | None = None,
    tokens: list[Token] | None = None,
    topology: Topology = Topology.WELL_MIXED,
    topology_params: dict[str, NumberRange] | None = None,
    cross_token_flows: list[CrossTokenFlow] | None = None,
) -> TokenEconomy:
    if tokens is None:
        tokens = [
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=[_emission_rule()],
                offer_variety_K=NumberRange.point(5),
            )
        ]
    return TokenEconomy(
        meta=Meta(name="t", archetype=archetype, nfrs=nfrs or NFRs()),
        tokens=tokens,
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=topology,
            topology_params=topology_params or {},
            agent_types=[
                AgentType(
                    id="user",
                    fraction=1.0,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                )
            ],
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
        ),
        cross_token_flows=cross_token_flows or [],
    )


# ---------------------------------------------------------------------------
# Phase 5a — archetype routing
# ---------------------------------------------------------------------------


def test_archetype_routing_default_runs_every_fm() -> None:
    """Default config skips no FMs, so every archetype runs every FM."""
    te = _basic_te(archetype=Archetype.NATIVE_PROTOCOL_ASSET)
    report = verify(te)
    fm_ids = {v.failure_mode.split(":")[0].strip() for v in report.verdicts}
    assert {"FM1", "FM2", "FM3", "FM4", "FM5", "FM6"} <= fm_ids


def test_archetype_routing_skips_fm_when_overridden() -> None:
    cfg = VerifierConfig.with_overrides(
        {
            "archetype_fm_applicability": {
                "native_protocol_asset": ["FM4"],
                "stablecoin": [],
                "governance_utility_pair": [],
                "play_to_earn_dual": [],
                "community_reward": [],
                "other": [],
            }
        }
    )
    te = _basic_te(archetype=Archetype.NATIVE_PROTOCOL_ASSET)
    report = verify(te, config=cfg)
    fm4 = next(v for v in report.verdicts if "FM4" in v.failure_mode)
    assert fm4.status == Status.NOT_APPLICABLE
    assert "archetype" in fm4.formal_condition.lower()


def test_archetype_routing_does_not_skip_other_archetypes() -> None:
    """Skip list for native_protocol_asset doesn't affect other archetypes."""
    cfg = VerifierConfig.with_overrides(
        {
            "archetype_fm_applicability": {
                "native_protocol_asset": ["FM4"],
                "stablecoin": [],
                "governance_utility_pair": [],
                "play_to_earn_dual": [],
                "community_reward": [],
                "other": [],
            }
        }
    )
    te = _basic_te(archetype=Archetype.STABLECOIN)
    report = verify(te, config=cfg)
    fm4 = next(v for v in report.verdicts if "FM4" in v.failure_mode)
    assert fm4.status != Status.NOT_APPLICABLE or "archetype" not in fm4.formal_condition.lower()


# ---------------------------------------------------------------------------
# Phase 5b — cross-token flows
# ---------------------------------------------------------------------------


def test_cross_token_mint_adds_to_E() -> None:
    """A cross-token MINT flow should increase the target token's E,
    making FM3 more likely to fail."""
    flow = CrossTokenFlow(
        source_token="A",
        source_event="A_event",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(
            family=AsymptoticFamily.CONSTANT,
            parameter_ranges={"c": NumberRange.point(1000.0)},
        ),
    )
    tokens = [
        Token(
            id="A",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            burn_rules=[
                Rule(
                    trigger=RuleTrigger(
                        kind=BurnTriggerKind.DEMAND_DRIVEN,
                        event_frequency=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(1.0)},
                        ),
                    ),
                    function=FunctionShape(
                        sign=FunctionSign.ALWAYS_NEGATIVE,
                        asymptotic_class=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(2.0)},
                        ),
                    ),
                )
            ],
            offer_variety_K=NumberRange.point(5),
        ),
        Token(
            id="B",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            burn_rules=[
                Rule(
                    trigger=RuleTrigger(
                        kind=BurnTriggerKind.DEMAND_DRIVEN,
                        event_frequency=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(1.0)},
                        ),
                    ),
                    function=FunctionShape(
                        sign=FunctionSign.ALWAYS_NEGATIVE,
                        asymptotic_class=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(2.0)},
                        ),
                    ),
                )
            ],
            offer_variety_K=NumberRange.point(5),
        ),
    ]
    te = _basic_te(tokens=tokens, cross_token_flows=[flow])
    report = verify(te)
    fm3_b = next(
        v
        for v in report.verdicts
        if v.failure_mode.startswith("FM3") and v.subject == "B"
    )
    # Adding 1000-unit cross-token mint to B's E pushes ρ < 1; expect FAIL.
    assert fm3_b.status == Status.FAIL


# ---------------------------------------------------------------------------
# Phase 5c — topology correction
# ---------------------------------------------------------------------------


def test_network_topology_passes_with_high_avg_degree() -> None:
    """avg_degree ≥ 2·K·d should let the network rule pass FM5 even when
    well-mixed N would fail."""
    te = _basic_te(
        topology=Topology.NETWORK,
        topology_params={"average_degree": NumberRange.point(50.0)},
    )
    # K=5, d=2 ⇒ deg* = 20. avg_degree = 50 clears it.
    report = verify(te)
    fm5 = next(v for v in report.verdicts if "FM5" in v.failure_mode)
    assert fm5.status == Status.PASS
    cv = next(c for c in fm5.critical_values if c.parameter == "average_degree")
    assert cv.value == pytest.approx(20.0, abs=1e-9)


def test_network_topology_inconclusive_with_low_avg_degree() -> None:
    """avg_degree < 2·K·d falls through to the well-mixed Z3 path."""
    te = _basic_te(
        topology=Topology.NETWORK,
        topology_params={"average_degree": NumberRange.point(5.0)},
    )
    # deg* = 20; avg_degree = 5 < 20. Falls through; well-mixed N=1000 passes
    # (because 2*5*2+1 = 21 < 1000), so verdict is PASS.
    report = verify(te)
    fm5 = next(v for v in report.verdicts if "FM5" in v.failure_mode)
    # Well-mixed passes with N=1000 ≥ 21, but the network avg_degree is also
    # reported as a critical value to inform the user.
    assert fm5.status == Status.PASS
    cv = next(c for c in fm5.critical_values if c.parameter == "average_degree")
    assert cv.value == pytest.approx(20.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Phase 5d — NFR reweighting
# ---------------------------------------------------------------------------


def test_nfr1_multiplier_default_is_no_op() -> None:
    """Default multipliers preserve case-study verdicts."""
    from schema import load_te

    te = load_te("examples/axie_infinity.yaml")
    default_report = verify(te)
    explicit_report = verify(te, config=VerifierConfig.paper_defaults())
    assert {(v.failure_mode, v.subject, v.status.value) for v in default_report.verdicts} == {
        (v.failure_mode, v.subject, v.status.value) for v in explicit_report.verdicts
    }


def test_nfr1_high_resilience_tightens_rho() -> None:
    """Override NFR1 multiplier to 2.0; a previously-passing FM3 may flip."""
    cfg = VerifierConfig.with_overrides(
        {"nfr1_resilience_rho_multiplier": {"1": 1.0, "2": 1.0, "3": 1.0, "4": 2.0, "5": 4.0}}
    )
    # Synthetic IR where ρ ≈ 1 (passes default ρ_floor=1.0 but fails ρ_floor=2.0)
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            burn_rules=[
                Rule(
                    trigger=RuleTrigger(
                        kind=BurnTriggerKind.DEMAND_DRIVEN,
                        event_frequency=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(1.0)},
                        ),
                    ),
                    function=FunctionShape(
                        sign=FunctionSign.ALWAYS_NEGATIVE,
                        asymptotic_class=AsymptoticClass(
                            family=AsymptoticFamily.CONSTANT,
                            parameter_ranges={"c": NumberRange.point(1.5)},
                        ),
                    ),
                )
            ],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    te = _basic_te(tokens=tokens, nfrs=NFRs(resilience=5))
    # With override 4.0× on ρ_floor, the FM3 verdict should be FAIL
    report = verify(te, config=cfg)
    fm3 = next(v for v in report.verdicts if "FM3" in v.failure_mode)
    assert fm3.status == Status.FAIL
