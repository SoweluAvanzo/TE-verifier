"""Phase B1 — proportional cross-token flow coupling.

When `CrossTokenFlow.coupling = PROPORTIONAL_TO_SOURCE`, the flow's
per-period rate is `coupling_ratio × source_token.own_E`. This test
file pins the encoding and the back-compat default.
"""

from __future__ import annotations

import pytest

from schema import (
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    ControllingActor,
    CrossTokenAction,
    CrossTokenFlow,
    EmissionTriggerKind,
    FlowCoupling,
    FunctionShape,
    FunctionSign,
    GovernanceSpec,
    GovernanceType,
    HoldingTimeDistribution,
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
from verifier import Status, verify


def _emission_rule(c: float) -> Rule:
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


def _make_te(
    *,
    tokens: list[Token],
    Q: float = 100.0,
    cross_token_flows: list[CrossTokenFlow] | None = None,
) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=tokens,
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(Q),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
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


def _fm(report, fm_id: str, subject: str):
    return next(
        v
        for v in report.verdicts
        if v.failure_mode.startswith(fm_id) and v.subject == subject
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_proportional_coupling_requires_ratio() -> None:
    """proportional_to_source without coupling_ratio must raise at construction."""
    with pytest.raises(ValueError, match="coupling_ratio"):
        CrossTokenFlow(
            source_token="A",
            source_event="evt",
            target_token="B",
            target_action=CrossTokenAction.MINT,
            amount=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            coupling=FlowCoupling.PROPORTIONAL_TO_SOURCE,
            # no coupling_ratio
        )


def test_independent_default_no_ratio_required() -> None:
    """Default coupling=independent stays valid without coupling_ratio."""
    flow = CrossTokenFlow(
        source_token="A",
        source_event="evt",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(
            family=AsymptoticFamily.CONSTANT,
            parameter_ranges={"c": NumberRange.point(10.0)},
        ),
    )
    assert flow.coupling == FlowCoupling.INDEPENDENT
    assert flow.coupling_ratio is None


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_independent_coupling_is_back_compat() -> None:
    """An explicit independent flow must behave identically to a Phase A flow."""
    tokens = [
        Token(
            id="A",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            offer_variety_K=NumberRange.point(5),
        ),
        Token(
            id="B",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            offer_variety_K=NumberRange.point(5),
        ),
    ]
    indep = CrossTokenFlow(
        source_token="A",
        source_event="evt",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(
            family=AsymptoticFamily.CONSTANT,
            parameter_ranges={"c": NumberRange.point(200.0)},
        ),
    )
    r = verify(_make_te(tokens=tokens, Q=100.0, cross_token_flows=[indep]))
    # 200/period MINT pushes B's E above Q=100 → FAIL.
    assert _fm(r, "FM1", subject="B").status == Status.FAIL


def test_proportional_coupling_scales_with_source_E() -> None:
    """A proportional flow's contribution scales with the source's own E.

    Source A emits 100/period. Coupling ratio = [0.5, 0.5] → exactly 50/period
    contributed to B. With B's own E = 1 and Q = 60, total E = 51 ≤ 60 → PASS.
    With ratio = [2.0, 2.0] → 200/period → total E = 201 > 60 → FAIL.
    """
    base_tokens = lambda src_c: [
        Token(
            id="A",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=src_c)],
            offer_variety_K=NumberRange.point(5),
        ),
        Token(
            id="B",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            offer_variety_K=NumberRange.point(5),
        ),
    ]
    flow_low = CrossTokenFlow(
        source_token="A",
        source_event="evt",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
        coupling=FlowCoupling.PROPORTIONAL_TO_SOURCE,
        coupling_ratio=NumberRange.point(0.5),
    )
    flow_high = CrossTokenFlow(
        source_token="A",
        source_event="evt",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
        coupling=FlowCoupling.PROPORTIONAL_TO_SOURCE,
        coupling_ratio=NumberRange.point(2.0),
    )
    r_low = verify(
        _make_te(tokens=base_tokens(100.0), Q=60.0, cross_token_flows=[flow_low])
    )
    r_high = verify(
        _make_te(tokens=base_tokens(100.0), Q=60.0, cross_token_flows=[flow_high])
    )
    assert _fm(r_low, "FM1", subject="B").status == Status.PASS
    assert _fm(r_high, "FM1", subject="B").status == Status.FAIL


def test_proportional_coupling_ratio_bounds_honored() -> None:
    """When the ratio range is wide enough, Z3 must find a witness within it.

    Source A emits 50/period. Ratio range [0.0, 4.0] means flow contributes
    in [0, 200]. Q = 60. The verifier must FAIL FM1 on B because 4.0×50 = 200
    exceeds Q regardless of the ratio's lower bound.
    """
    tokens = [
        Token(
            id="A",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=50.0)],
            offer_variety_K=NumberRange.point(5),
        ),
        Token(
            id="B",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            offer_variety_K=NumberRange.point(5),
        ),
    ]
    flow = CrossTokenFlow(
        source_token="A",
        source_event="evt",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
        coupling=FlowCoupling.PROPORTIONAL_TO_SOURCE,
        coupling_ratio=NumberRange(min=0.0, max=4.0),
    )
    r = verify(_make_te(tokens=tokens, Q=60.0, cross_token_flows=[flow]))
    assert _fm(r, "FM1", subject="B").status == Status.FAIL


def test_proportional_burn_coupling_lifts_rho() -> None:
    """A proportional BURN flow tied to source's E lifts the target's ρ.

    MakerDAO-shape: A is the "fee-paying" token (own E = 100/period);
    B's own E = 100/period and own burn = 0. A proportional BURN flow
    with ratio = 1.0 makes B's burn = 1.0 × 100 = 100/period, so
    ρ = 100/100 = 1 → FM3 PASS. Without the flow, ρ = 0 → FM3 FAIL.
    """
    tokens = [
        Token(
            id="A",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=100.0)],
            offer_variety_K=NumberRange.point(5),
        ),
        Token(
            id="B",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=100.0)],
            offer_variety_K=NumberRange.point(5),
        ),
    ]
    # Without the flow, B has no burn → FM3 FAIL.
    r_no_flow = verify(_make_te(tokens=tokens, Q=200.0))
    assert _fm(r_no_flow, "FM3", subject="B").status == Status.FAIL

    flow = CrossTokenFlow(
        source_token="A",
        source_event="fee_event",
        target_token="B",
        target_action=CrossTokenAction.BURN,
        amount=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
        coupling=FlowCoupling.PROPORTIONAL_TO_SOURCE,
        coupling_ratio=NumberRange.point(1.0),
    )
    r_with_flow = verify(
        _make_te(tokens=tokens, Q=200.0, cross_token_flows=[flow])
    )
    assert _fm(r_with_flow, "FM3", subject="B").status == Status.PASS


def test_missing_source_token_falls_back_to_zero() -> None:
    """If source_token isn't in te.tokens, the proportional flow contributes 0.

    This is the defensive path: rather than crashing or silently using a
    free variable, the FM treats the missing source as a no-op so the rest
    of the verdict can still compute.
    """
    tokens = [
        Token(
            id="B",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=10.0)],
            offer_variety_K=NumberRange.point(5),
        ),
    ]
    flow = CrossTokenFlow(
        source_token="GHOST",  # not in tokens
        source_event="evt",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
        coupling=FlowCoupling.PROPORTIONAL_TO_SOURCE,
        coupling_ratio=NumberRange(min=0.0, max=10.0),
    )
    r = verify(_make_te(tokens=tokens, Q=100.0, cross_token_flows=[flow]))
    # Source missing → flow contributes 0, so FM1 sees only own E=10 ≤ 100.
    assert _fm(r, "FM1", subject="B").status == Status.PASS
