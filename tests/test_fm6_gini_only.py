"""FM6 — Gini-only verdict when rule_structure is empty.

Pre-fix: an empty rule_structure short-circuited FM6 to INCONCLUSIVE,
ignoring an explicit token_balance_gini. Post-fix: a high Gini
produces a FAIL verdict on the secondary-signal channel even without
rule_structure data — the Curve-Wars / Convex pattern is independently
actionable.
"""

from __future__ import annotations

from schema import (
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
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


def _emit() -> Rule:
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
                parameter_ranges={"c": NumberRange.point(1.0)},
            ),
        ),
    )


def _make_te(*, gini=None, rule_structure=None) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=[_emit()],
                offer_variety_K=NumberRange.point(5),
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="u",
                    fraction=1.0,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                )
            ],
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure=rule_structure or {},
            token_balance_gini=gini,
        ),
    )


def _fm6(report):
    return next(v for v in report.verdicts if v.failure_mode.startswith("FM6"))


def test_fm6_high_gini_alone_yields_fail() -> None:
    """rule_structure empty + Gini > 0.6 → FAIL on the Gini channel."""
    te = _make_te(gini=NumberRange(min=0.7, max=0.85))
    fm6 = _fm6(verify(te))
    assert fm6.status == Status.FAIL
    assert "Gini" in fm6.formal_condition
    # Must surface a recommendation the user can act on.
    assert fm6.recommendation is not None
    assert fm6.recommendation.parameter == "token_gini"


def test_fm6_low_gini_with_empty_rule_structure_stays_inconclusive() -> None:
    """A safe Gini doesn't rescue the missing rule_structure → INCONCLUSIVE
    (because we still can't compute Γ, the primary signal)."""
    te = _make_te(gini=NumberRange(min=0.1, max=0.3))
    fm6 = _fm6(verify(te))
    assert fm6.status == Status.INCONCLUSIVE


def test_fm6_no_gini_no_rule_structure_stays_inconclusive() -> None:
    """Truly empty governance section — INCONCLUSIVE as before."""
    te = _make_te()
    fm6 = _fm6(verify(te))
    assert fm6.status == Status.INCONCLUSIVE
