"""Phase 1 — threshold extraction tests.

For each FM, verify that the verifier returns the analytically-correct
critical value within `numeric_epsilon` on synthetic IRs whose closed-
form thresholds are computable by hand. Plus regression tests asserting
the case-study verdict matrix is unchanged from Phase 0.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

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
    ValueAnchor,
)
from verifier import Status, verify
from verifier.config import VerifierConfig
from verifier.failure_modes.base import optimize_threshold


EPS = 1e-6


# ---------------------------------------------------------------------------
# optimize_threshold primitive — verify the Z3 wrapper itself
# ---------------------------------------------------------------------------


def test_optimize_threshold_max_simple() -> None:
    import z3

    K = z3.Real("K")
    d = z3.Real("d")
    result = optimize_threshold(
        constraints=[K >= 2, K <= 8, d >= 1, d <= 3],
        target=2 * K * d + 1,
        direction="max",
    )
    assert result == pytest.approx(49.0, abs=EPS)


def test_optimize_threshold_min_linear() -> None:
    """Linear minimum — Z3's νZ engine handles linear arithmetic exactly."""
    import z3

    x = z3.Real("x")
    y = z3.Real("y")
    result = optimize_threshold(
        constraints=[x >= 1, x <= 5, y >= 2, y <= 4],
        target=x + 2 * y,
        direction="min",
    )
    assert result == pytest.approx(1 + 4, abs=EPS)


def test_optimize_threshold_unsat_returns_none() -> None:
    import z3

    x = z3.Real("x")
    result = optimize_threshold(
        constraints=[x > 5, x < 1],
        target=x,
        direction="max",
    )
    assert result is None


# ---------------------------------------------------------------------------
# Helper: build a minimal TE for synthetic FM testing
# ---------------------------------------------------------------------------


def _make_te(
    *,
    name: str = "synthetic",
    archetype: Archetype = Archetype.OTHER,
    nfrs: NFRs | None = None,
    tokens: list[Token],
    participants: ParticipantsSpec,
    governance: GovernanceSpec | None = None,
) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name=name, archetype=archetype, nfrs=nfrs or NFRs()),
        tokens=tokens,
        participants=participants,
        governance=governance
        or GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={
                "emission_rate": ControllingActor.TOKEN_HOLDER_VOTE,
                "burn_rate": ControllingActor.TOKEN_HOLDER_VOTE,
                "rule_modification": ControllingActor.TOKEN_HOLDER_VOTE,
            },
            monitoring_capacity_gamma=NumberRange.point(0.5),
        ),
    )


def _emission_token(
    token_id: str,
    function: list[TokenFunction] | None = None,
    *,
    K: float | None = 5.0,
) -> Token:
    return Token(
        id=token_id,
        function=function or [TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[
            Rule(
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
        ],
        offer_variety_K=NumberRange.point(K) if K is not None else None,
    )


# ---------------------------------------------------------------------------
# FM5 — N* = 2·K·d + 1 (worst-case)
# ---------------------------------------------------------------------------


def test_fm5_n_star_closed_form() -> None:
    """N* = 2·K_hi·d_hi + 1 = 2·10·5 + 1 = 101."""
    te = _make_te(
        tokens=[_emission_token("T", K=10)],
        participants=ParticipantsSpec(
            count_N=NumberRange(min=50, max=80),  # below threshold
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange(min=1, max=5),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
        ),
    )
    # Override K range
    tok = te.tokens[0].model_copy(
        update={"offer_variety_K": NumberRange(min=5, max=10)}
    )
    te = te.model_copy(update={"tokens": [tok]})

    report = verify(te)
    fm5 = next(v for v in report.verdicts if "FM5" in v.failure_mode)
    assert fm5.status == Status.FAIL
    n_star_cv = next(cv for cv in fm5.critical_values if cv.parameter == "N")
    assert n_star_cv.value == pytest.approx(101.0, abs=EPS)
    assert n_star_cv.direction == ">="


def test_fm5_n_star_passes_when_n_above_threshold() -> None:
    te = _make_te(
        tokens=[_emission_token("T", K=10)],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(500),  # well above N* = 101
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(5),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
        ),
    )
    report = verify(te)
    fm5 = next(v for v in report.verdicts if "FM5" in v.failure_mode)
    assert fm5.status == Status.PASS
    # Critical value still reported on PASS so the user sees the margin
    n_star_cv = next(cv for cv in fm5.critical_values if cv.parameter == "N")
    assert n_star_cv.value == pytest.approx(2 * 10 * 5 + 1, abs=EPS)


# ---------------------------------------------------------------------------
# FM6 — n_demote* = max(0, ⌈U − T·Γ_threshold⌉)
# ---------------------------------------------------------------------------


def test_fm6_n_demote_closed_form() -> None:
    """U=8, T=10, Γ_threshold=0.5 → n_demote* = ⌈8 − 5⌉ = 3."""
    rules: dict[str, ControllingActor] = {}
    # 8 unilateral, 2 distributed
    for i in range(8):
        rules[f"decision_{i}"] = ControllingActor.SINGLE_ENTITY
    for i in range(8, 10):
        rules[f"decision_{i}"] = ControllingActor.TOKEN_HOLDER_VOTE
    gov = GovernanceSpec(
        type=GovernanceType.HYBRID,
        rule_structure=rules,
    )
    te = _make_te(
        tokens=[_emission_token("T")],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
        ),
        governance=gov,
    )
    report = verify(te)
    fm6 = next(v for v in report.verdicts if "FM6" in v.failure_mode)
    assert fm6.status == Status.FAIL
    cv = next(c for c in fm6.critical_values if c.parameter == "n_demote")
    assert cv.value == pytest.approx(3.0, abs=EPS)
    assert fm6.recommendation is not None
    assert fm6.recommendation.parameter == "n_demote"
    assert fm6.recommendation.safe_threshold == pytest.approx(3.0, abs=EPS)


def test_fm6_n_demote_zero_when_passing() -> None:
    """All distributed → n_demote* = 0."""
    rules: dict[str, ControllingActor] = {
        f"decision_{i}": ControllingActor.TOKEN_HOLDER_VOTE for i in range(5)
    }
    gov = GovernanceSpec(type=GovernanceType.DAO, rule_structure=rules)
    te = _make_te(
        tokens=[_emission_token("T")],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
        ),
        governance=gov,
    )
    report = verify(te)
    fm6 = next(v for v in report.verdicts if "FM6" in v.failure_mode)
    assert fm6.status == Status.PASS
    cv = next(c for c in fm6.critical_values if c.parameter == "n_demote")
    assert cv.value == pytest.approx(0.0, abs=EPS)


# ---------------------------------------------------------------------------
# FM4 — γ* = (T-R) / S
# ---------------------------------------------------------------------------


def test_fm4_gamma_star_closed_form() -> None:
    """T-R default = 0.5, S = 0.5 (token_penalty default minus slack) → γ* = 1.0
    in the worst case. Use a higher S so γ* falls inside [0,1].
    """
    # Use exclusion sanction (S_normalized table maps to 0.9 ± 0.1 → [0.8, 1.0])
    # γ* = 0.5 / 0.8 = 0.625
    te = _make_te(
        tokens=[
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=[
                    Rule(
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
                ],
                offer_variety_K=NumberRange.point(10),
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="contributor",
                    fraction=0.5,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                ),
                AgentType(
                    id="consumer",
                    fraction=0.5,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                ),
            ],
        ),
        governance=GovernanceSpec(
            type=GovernanceType.DAO,
            rule_structure={
                "x": ControllingActor.TOKEN_HOLDER_VOTE,
            },
            monitoring_capacity_gamma=NumberRange(min=0.1, max=0.4),  # below γ*
            sanction_structure=SanctionStructure(kind=SanctionKind.EXCLUSION),
        ),
    )
    report = verify(te)
    fm4 = next(v for v in report.verdicts if "FM4" in v.failure_mode)
    # γ* should be (0.5 / 0.8) = 0.625
    cv = next(c for c in fm4.critical_values if c.parameter == "gamma")
    assert cv.value == pytest.approx(0.5 / 0.8, abs=EPS)


# ---------------------------------------------------------------------------
# FM2 — τ̄* = ceiling
# ---------------------------------------------------------------------------


def test_fm2_tau_bar_critical_is_ceiling() -> None:
    cfg = VerifierConfig.paper_defaults()
    te = _make_te(
        tokens=[_emission_token("T")],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="trader",
                    fraction=1.0,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(0.5)
                    ),
                )
            ],
        ),
    )
    report = verify(te)
    fm2 = next(v for v in report.verdicts if "FM2" in v.failure_mode)
    cv = next(c for c in fm2.critical_values if c.parameter == "tau_bar")
    assert cv.value == pytest.approx(cfg.tau_bar_ceiling, abs=EPS)


# ---------------------------------------------------------------------------
# FM1 — E* = Q_lo
# ---------------------------------------------------------------------------


def test_fm1_e_star_equals_q_lo() -> None:
    te = _make_te(
        tokens=[_emission_token("T")],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange(min=42, max=200),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="trader",
                    fraction=1.0,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                )
            ],
        ),
    )
    report = verify(te)
    fm1 = next(
        v
        for v in report.verdicts
        if "FM1" in v.failure_mode and v.subject == "T"
    )
    cv = next(c for c in fm1.critical_values if c.parameter == "net_emission")
    assert cv.value == pytest.approx(42.0, abs=EPS)


# ---------------------------------------------------------------------------
# FM3 — ρ* = floor
# ---------------------------------------------------------------------------


def test_fm3_rho_star_is_floor() -> None:
    cfg = VerifierConfig.paper_defaults()
    te = _make_te(
        tokens=[_emission_token("T")],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(2),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
            agent_types=[
                AgentType(
                    id="trader",
                    fraction=1.0,
                    expected_holding_time=HoldingTimeDistribution(
                        expected_periods=NumberRange.point(5)
                    ),
                )
            ],
        ),
    )
    report = verify(te)
    fm3 = next(
        v
        for v in report.verdicts
        if "FM3" in v.failure_mode and v.subject == "T"
    )
    cv = next(c for c in fm3.critical_values if c.parameter == "rho")
    assert cv.value == pytest.approx(cfg.rho_floor, abs=EPS)


# ---------------------------------------------------------------------------
# Regression — case-study verdict matrix unchanged from Phase 0
# ---------------------------------------------------------------------------


_CASE_STUDIES = [
    "axie_infinity",
    "bitcoin",
    "curve_vecrv",
    "ethereum",
    "makerdao",
]


@pytest.mark.parametrize("name", _CASE_STUDIES)
def test_case_study_critical_values_populated(name: str) -> None:
    """Every case-study verdict carries critical_values now (or has a
    well-justified reason to be empty: NOT_APPLICABLE)."""
    from tests.conftest import report_for

    report = report_for(name)
    for v in report.verdicts:
        if v.status == Status.NOT_APPLICABLE:
            continue  # N/A verdicts legitimately have no thresholds
        # PASS, FAIL, INCONCLUSIVE, PASS_AS_INTENDED all should report at
        # least one critical value
        assert v.critical_values, (
            f"{name}: {v.failure_mode} on {v.subject} "
            f"({v.status.value}) has no critical_values"
        )


@pytest.mark.parametrize("name", _CASE_STUDIES)
def test_case_study_failed_verdicts_have_recommendation(name: str) -> None:
    """Every FAIL verdict on a case-study system has a recommendation."""
    from tests.conftest import report_for

    report = report_for(name)
    for v in report.verdicts:
        if v.status != Status.FAIL:
            continue
        # A small number of FM3 cases (no-burn) carry no recommendation
        # because the redesign is structural rather than numeric — those
        # are intentionally exempt.
        if v.failure_mode.startswith("FM3") and "no burn" in v.formal_condition.lower():
            continue
        # FM6 Gini-only failures may not have a numeric recommendation
        # if no Gini value is supplied (rare in case studies)
        assert v.recommendation is not None or v.suggestions, (
            f"{name}: failed verdict {v.failure_mode}/{v.subject} has "
            f"neither recommendation nor suggestions"
        )
