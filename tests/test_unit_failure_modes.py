"""Unit tests for each failure-mode evaluator on small synthetic IRs.

These tests avoid the YAML fixtures so each FM is exercised in isolation
with the minimum machinery needed to drive it. They verify the core
inequalities of the paper translate correctly into Z3 queries.
"""

from __future__ import annotations

import pytest

from schema import (
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    CirculationSpeed,
    ControllingActor,
    EmissionTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceMaturity,
    GovernanceSpec,
    GovernanceType,
    HoldingTimeDistribution,
    Meta,
    NFRs,
    NumberRange,
    ParticipantsSpec,
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
from verifier.failure_modes import (
    FM1Oversupply,
    FM2VelocityTrap,
    FM3BurnEmission,
    FM4FreeRider,
    FM5CriticalMass,
    FM6GovernanceCapture,
)


def _emission_constant(c_min: float, c_max: float) -> Rule:
    return Rule(
        trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_POSITIVE,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange(min=c_min, max=c_max)},
            ),
        ),
    )


def _burn_constant(c_min: float, c_max: float, *, demand_driven: bool = True) -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=BurnTriggerKind.DEMAND_DRIVEN
            if demand_driven
            else BurnTriggerKind.RULE_DRIVEN
        ),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_NEGATIVE,
            asymptotic_class=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange(min=c_min, max=c_max)},
            ),
        ),
    )


def _basic_te(
    *,
    token: Token,
    N: NumberRange = NumberRange(min=1000, max=1000),
    Q: NumberRange = NumberRange(min=10000, max=10000),
    d: NumberRange = NumberRange(min=1, max=1),
    topology: Topology = Topology.WELL_MIXED,
    nfrs: NFRs | None = None,
    governance: GovernanceSpec | None = None,
    agent_types: list[AgentType] | None = None,
) -> TokenEconomy:
    if agent_types is None:
        agent_types = [
            AgentType(
                id="user",
                fraction=1.0,
                expected_holding_time=HoldingTimeDistribution(
                    expected_periods=NumberRange(min=10, max=20)
                ),
                balance_share=1.0,
            )
        ]
    return TokenEconomy(
        meta=Meta(name="unit-test", archetype=Archetype.OTHER, nfrs=nfrs or NFRs()),
        tokens=[token],
        participants=ParticipantsSpec(
            count_N=N,
            expected_Q=Q,
            average_demand_d=d,
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=topology,
            agent_types=agent_types,
        ),
        governance=governance
        or GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={"emission": ControllingActor.TOKEN_HOLDER_VOTE},
            monitoring_capacity_gamma=NumberRange.point(0.9),
            sanction_structure=SanctionStructure(kind=SanctionKind.GRADUATED),
        ),
    )


# ---------------------------------------------------------------------------
# FM1
# ---------------------------------------------------------------------------


def test_fm1_pure_inflation_is_flagged():
    """Emission >> Q must produce FAIL."""
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        offer_variety_K=NumberRange(min=10, max=10),
        emission_rules=[_emission_constant(1_000_000, 1_000_000)],
    )
    te = _basic_te(token=token, Q=NumberRange.point(10))
    report = verify(te, failure_modes=[FM1Oversupply])
    assert report.failures()
    assert report.failures()[0].counterexample is not None


def test_fm1_passes_when_emission_below_Q():
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        offer_variety_K=NumberRange(min=10, max=10),
        emission_rules=[_emission_constant(0, 5)],
    )
    te = _basic_te(token=token, Q=NumberRange.point(1_000_000))
    report = verify(te, failure_modes=[FM1Oversupply])
    assert not report.failures()


def test_fm1_not_applicable_for_non_transferable():
    token = Token(
        id="T",
        function=[TokenFunction.GOVERNANCE_RIGHT],
        transferable=False,
        emission_rules=[_emission_constant(1e9, 1e9)],
    )
    te = _basic_te(token=token)
    report = verify(te, failure_modes=[FM1Oversupply])
    [v] = report.verdicts
    assert v.status.value == "not_applicable"


# ---------------------------------------------------------------------------
# FM2
# ---------------------------------------------------------------------------


def test_fm2_velocity_trap_when_holding_time_low():
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        offer_variety_K=NumberRange.point(10),
        emission_rules=[_emission_constant(0, 1)],
    )
    agents = [
        AgentType(
            id="trader",
            fraction=1.0,
            balance_share=1.0,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange(min=0.1, max=0.5)
            ),
        )
    ]
    te = _basic_te(token=token, agent_types=agents)
    report = verify(te, failure_modes=[FM2VelocityTrap])
    [v] = report.verdicts
    assert v.status.value == "fail"


def test_fm2_passthru_when_circulate_fast_declared():
    """Same low τ̄ but NFR6 = circulate_fast → pass_as_intended."""
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        offer_variety_K=NumberRange.point(10),
        emission_rules=[_emission_constant(0, 1)],
    )
    agents = [
        AgentType(
            id="trader",
            fraction=1.0,
            balance_share=1.0,
            expected_holding_time=HoldingTimeDistribution(
                expected_periods=NumberRange(min=0.1, max=0.5)
            ),
        )
    ]
    te = _basic_te(
        token=token,
        agent_types=agents,
        nfrs=NFRs(circulation_speed=CirculationSpeed.CIRCULATE_FAST),
    )
    report = verify(te, failure_modes=[FM2VelocityTrap])
    [v] = report.verdicts
    assert v.status.value == "pass_as_intended"


# ---------------------------------------------------------------------------
# FM3
# ---------------------------------------------------------------------------


def test_fm3_no_burn_is_fail():
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_constant(1, 10)],
        burn_rules=[],
    )
    te = _basic_te(token=token)
    report = verify(te, failure_modes=[FM3BurnEmission])
    [v] = report.verdicts
    assert v.status.value == "fail"
    assert "no burn" in v.formal_condition.lower()


def test_fm3_demand_driven_burn_can_pass():
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_constant(1, 5)],
        burn_rules=[_burn_constant(5, 10, demand_driven=True)],
    )
    te = _basic_te(token=token)
    report = verify(te, failure_modes=[FM3BurnEmission])
    [v] = report.verdicts
    assert v.status.value == "pass"


# ---------------------------------------------------------------------------
# FM4
# ---------------------------------------------------------------------------


def test_fm4_not_applicable_for_pure_financial_token():
    """No behavioral_event / physical_resource_flow → FM4 inapplicable."""
    token = Token(
        id="T",
        function=[TokenFunction.STORE_OF_VALUE],
        emission_rules=[_emission_constant(1, 1)],
    )
    te = _basic_te(token=token)
    report = verify(te, failure_modes=[FM4FreeRider])
    [v] = report.verdicts
    assert v.status.value == "not_applicable"


# ---------------------------------------------------------------------------
# FM5
# ---------------------------------------------------------------------------


def test_fm5_critical_mass_violation():
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        offer_variety_K=NumberRange.point(50),
        emission_rules=[_emission_constant(1, 1)],
    )
    te = _basic_te(
        token=token,
        N=NumberRange(min=10, max=50),
        d=NumberRange.point(2),
        topology=Topology.WELL_MIXED,
    )
    report = verify(te, failure_modes=[FM5CriticalMass])
    [v] = report.verdicts
    assert v.status.value == "fail"  # 2*50*2+1 = 201 > 50


def test_fm5_pass_above_threshold():
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        offer_variety_K=NumberRange.point(5),
        emission_rules=[_emission_constant(1, 1)],
    )
    te = _basic_te(
        token=token,
        N=NumberRange(min=200, max=200),
        d=NumberRange.point(1),
        topology=Topology.WELL_MIXED,
    )
    report = verify(te, failure_modes=[FM5CriticalMass])
    [v] = report.verdicts
    assert v.status.value == "pass"  # 2*5*1+1 = 11 < 200


# ---------------------------------------------------------------------------
# FM6
# ---------------------------------------------------------------------------


def test_fm6_centralized_governance_flagged():
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_constant(1, 1)],
    )
    gov = GovernanceSpec(
        type=GovernanceType.CENTRALIZED,
        rule_structure={
            "a": ControllingActor.SINGLE_ENTITY,
            "b": ControllingActor.SINGLE_ENTITY,
            "c": ControllingActor.SINGLE_ENTITY,
        },
        sanction_structure=SanctionStructure(kind=SanctionKind.WARNING),
    )
    te = _basic_te(token=token, governance=gov)
    report = verify(te, failure_modes=[FM6GovernanceCapture])
    [v] = report.verdicts
    assert v.status.value == "fail"


def test_fm6_pass_as_intended_with_indefinite_centralization():
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_constant(1, 1)],
    )
    gov = GovernanceSpec(
        type=GovernanceType.CENTRALIZED,
        rule_structure={
            "a": ControllingActor.SINGLE_ENTITY,
            "b": ControllingActor.SINGLE_ENTITY,
        },
        sanction_structure=SanctionStructure(kind=SanctionKind.WARNING),
    )
    te = _basic_te(
        token=token,
        governance=gov,
        nfrs=NFRs(governance_maturity=GovernanceMaturity.INDEFINITE),
    )
    report = verify(te, failure_modes=[FM6GovernanceCapture])
    [v] = report.verdicts
    assert v.status.value == "pass_as_intended"


def test_fm6_pass_distributed_governance():
    token = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[_emission_constant(1, 1)],
    )
    gov = GovernanceSpec(
        type=GovernanceType.DAO,
        rule_structure={
            "a": ControllingActor.TOKEN_HOLDER_VOTE,
            "b": ControllingActor.TOKEN_HOLDER_VOTE,
            "c": ControllingActor.SMART_CONTRACT,
        },
        sanction_structure=SanctionStructure(kind=SanctionKind.GRADUATED),
        token_balance_gini=NumberRange(min=0.3, max=0.4),
    )
    te = _basic_te(token=token, governance=gov)
    report = verify(te, failure_modes=[FM6GovernanceCapture])
    [v] = report.verdicts
    assert v.status.value == "pass"
