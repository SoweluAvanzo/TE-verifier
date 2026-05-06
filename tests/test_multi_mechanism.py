"""Phase A — multi-mechanism mint/burn composition.

Verifies the composition theorem in `docs/proofs/composition.md`:
multiple `emission_rules` and `burn_rules` on a single token compose
additively, and cross-token flows targeting that token contribute on
the same side as a per-token rule of the corresponding sign.

A1 — composition tests on FM1 and FM3.
A2 — cross-token flow tests on FM1 (FM3 already covered by
test_phase5.test_cross_token_mint_adds_to_E).
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emission_rule(c: float) -> Rule:
    """A constant emission of `c` tokens per event, fired once per period."""
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


def _burn_rule(c: float, *, demand_driven: bool = True) -> Rule:
    return Rule(
        trigger=RuleTrigger(
            kind=BurnTriggerKind.DEMAND_DRIVEN
            if demand_driven
            else BurnTriggerKind.RULE_DRIVEN,
            event_frequency=AsymptoticClass(
                family=AsymptoticFamily.CONSTANT,
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
        function=FunctionShape(
            sign=FunctionSign.ALWAYS_NEGATIVE,
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


def _fm(report, fm_id: str, subject: str = "T"):
    return next(
        v
        for v in report.verdicts
        if v.failure_mode.startswith(fm_id) and v.subject == subject
    )


# ---------------------------------------------------------------------------
# A1 — multi-mechanism composition
# ---------------------------------------------------------------------------


def test_two_emission_rules_compose_additively_for_fm1() -> None:
    """Two emission rules of 30 each must compose to 60 tokens/period.

    With Q = 50, FM1 should pass for one rule (30 ≤ 50) and fail for two
    (60 > 50). This pins the additive composition: a single test on the
    boundary that flips precisely when the second rule is added.
    """
    one_rule = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=30.0)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    two_rules = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=30.0), _emission_rule(c=30.0)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r1 = verify(_make_te(tokens=one_rule, Q=50.0))
    r2 = verify(_make_te(tokens=two_rules, Q=50.0))
    assert _fm(r1, "FM1").status == Status.PASS
    assert _fm(r2, "FM1").status == Status.FAIL


def test_two_burn_rules_compose_additively_for_fm3() -> None:
    """Two burn rules of 0.6 each must compose to 1.2, lifting ρ above 1.

    With E = 1.0/period, one burn rule at 0.6 leaves ρ = 0.6 → FM3 FAIL.
    Adding a second 0.6 lifts ρ to 1.2 → FM3 PASS.
    """
    one_burn = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            burn_rules=[_burn_rule(c=0.6)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    two_burns = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            burn_rules=[_burn_rule(c=0.6), _burn_rule(c=0.6)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r1 = verify(_make_te(tokens=one_burn))
    r2 = verify(_make_te(tokens=two_burns))
    assert _fm(r1, "FM3").status == Status.FAIL
    assert _fm(r2, "FM3").status == Status.PASS


# ---------------------------------------------------------------------------
# A2 — FM1 consumes cross_token_flows
# ---------------------------------------------------------------------------


def test_fm1_includes_cross_token_mint() -> None:
    """Cross-token MINT into B should push FM1 on B from PASS to FAIL.

    Without the flow: B's E = 1, Q = 100 → PASS.
    With the flow (MINT 200 into B): B's effective E = 201 > Q → FAIL.
    """
    base_tokens = lambda: [
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

    # Without flow → PASS for B.
    r0 = verify(_make_te(tokens=base_tokens(), Q=100.0))
    assert _fm(r0, "FM1", subject="B").status == Status.PASS

    # With cross-token MINT of 200/period into B → FM1 FAIL on B.
    flow = CrossTokenFlow(
        source_token="A",
        source_event="A_event",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(
            family=AsymptoticFamily.CONSTANT,
            parameter_ranges={"c": NumberRange.point(200.0)},
        ),
    )
    r1 = verify(_make_te(tokens=base_tokens(), Q=100.0, cross_token_flows=[flow]))
    assert _fm(r1, "FM1", subject="B").status == Status.FAIL


def test_fm1_includes_cross_token_burn() -> None:
    """Cross-token BURN into A should pull FM1 on A from FAIL to PASS.

    Without the flow: E = 200 > Q = 100 → FAIL.
    With cross-token BURN of 150 into A: net = 50 ≤ 100 → PASS.
    """
    tokens = [
        Token(
            id="A",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=200.0)],
            offer_variety_K=NumberRange.point(5),
        ),
        Token(
            id="B",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emission_rule(c=1.0)],
            offer_variety_K=NumberRange.point(5),
        ),
    ]

    # Without flow → FAIL on A.
    r0 = verify(_make_te(tokens=tokens, Q=100.0))
    assert _fm(r0, "FM1", subject="A").status == Status.FAIL

    # With cross-token BURN into A → FM1 PASS on A.
    flow = CrossTokenFlow(
        source_token="B",
        source_event="B_event",
        target_token="A",
        target_action=CrossTokenAction.BURN,
        amount=AsymptoticClass(
            family=AsymptoticFamily.CONSTANT,
            parameter_ranges={"c": NumberRange.point(150.0)},
        ),
    )
    r1 = verify(_make_te(tokens=tokens, Q=100.0, cross_token_flows=[flow]))
    assert _fm(r1, "FM1", subject="A").status == Status.PASS


def test_fm1_no_own_emission_but_cross_token_mint_is_evaluated() -> None:
    """A token with no own emission_rules but a cross-token MINT into it
    must be evaluated (not short-circuit-PASSed).

    Pre-fix, FM1 returned PASS for any token with empty emission_rules
    even when cross-token flows were minting into it. Post-fix, the
    cross-token mint is composed into E and FM1 evaluates it normally.
    """
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
            emission_rules=[],  # no own emission
            offer_variety_K=NumberRange.point(5),
        ),
    ]
    flow = CrossTokenFlow(
        source_token="A",
        source_event="A_event",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(
            family=AsymptoticFamily.CONSTANT,
            parameter_ranges={"c": NumberRange.point(500.0)},
        ),
    )
    r = verify(_make_te(tokens=tokens, Q=100.0, cross_token_flows=[flow]))
    fm1_b = _fm(r, "FM1", subject="B")
    # 500/period > Q=100 → FAIL. The pre-fix bug would have returned PASS.
    assert fm1_b.status == Status.FAIL


def test_fm1_swept_fields_lists_cross_token_flow() -> None:
    """Counterexamples should mark cross-token flows as swept fields so
    the verdict UI can show them in the contributing-input list."""
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
    flow = CrossTokenFlow(
        source_token="A",
        source_event="A_event",
        target_token="B",
        target_action=CrossTokenAction.MINT,
        amount=AsymptoticClass(
            family=AsymptoticFamily.CONSTANT,
            parameter_ranges={"c": NumberRange.point(500.0)},
        ),
    )
    r = verify(_make_te(tokens=tokens, Q=100.0, cross_token_flows=[flow]))
    fm1_b = _fm(r, "FM1", subject="B")
    # The cross-token flow must appear in either swept or committed fields.
    fields = fm1_b.swept_fields + fm1_b.committed_fields
    assert any("cross_token_flows" in f for f in fields)
