"""Sign-soundness pre-flight checks (Phase G/Task 1).

A mint rule whose declared coefficient range admits a negative rate
is mathematically impossible — the verifier must reject it with a
precise error rather than silently produce verdicts."""

from __future__ import annotations

import pytest

from schema import (
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
    EmissionTriggerKind,
    FunctionShape,
    FunctionSign,
    GovernanceSpec,
    GovernanceType,
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
from verifier.dispatcher import verify
from verifier.sign_validation import validate_signs


def _te(emission_ac: AsymptoticClass):
    return TokenEconomy(
        meta=Meta(name="sign-test", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[Rule(
                trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                function=FunctionShape(asymptotic_class=emission_ac),
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


def test_constant_negative_c_is_flagged() -> None:
    """A constant mint with c < 0 is mathematically impossible."""
    ac = AsymptoticClass(
        family=AsymptoticFamily.CONSTANT,
        parameter_ranges={"c": NumberRange(min=-5.0, max=10.0)},
    )
    violations = validate_signs(_te(ac))
    assert violations
    assert violations[0].family == "constant"


def test_linear_negative_a_with_small_b_is_flagged() -> None:
    """Linear with a<0 and b not large enough to keep rate ≥ 0 over
    [0, horizon] is impossible."""
    ac = AsymptoticClass(
        family=AsymptoticFamily.LINEAR,
        parameter_ranges={
            "a": NumberRange(min=-1.0, max=0.5),
            "b": NumberRange(min=0.0, max=10.0),
        },
    )
    violations = validate_signs(_te(ac), horizon=52.0)
    assert violations, "expected a violation when a_min*H + b_min < 0"


def test_linear_negative_a_with_sufficient_b_passes() -> None:
    """a_min*H + b_min ≥ 0 → no violation."""
    ac = AsymptoticClass(
        family=AsymptoticFamily.LINEAR,
        parameter_ranges={
            "a": NumberRange(min=-0.1, max=0.5),
            "b": NumberRange(min=10.0, max=20.0),
        },
    )
    violations = validate_signs(_te(ac), horizon=52.0)
    assert not violations, f"unexpected violations: {violations}"


def test_polynomial_negative_a_flagged() -> None:
    ac = AsymptoticClass(
        family=AsymptoticFamily.POLYNOMIAL,
        degree=2,
        parameter_ranges={
            "a": NumberRange(min=-0.1, max=0.5),
            "b": NumberRange(min=0.0, max=1.0),
        },
    )
    violations = validate_signs(_te(ac), horizon=52.0)
    assert violations


def test_verify_surfaces_violation_as_coherence_error() -> None:
    """End-to-end: dispatcher.verify must emit an error-level coherence
    issue when sign validation fires."""
    ac = AsymptoticClass(
        family=AsymptoticFamily.CONSTANT,
        parameter_ranges={"c": NumberRange(min=-3.0, max=2.0)},
    )
    report = verify(_te(ac))
    errors = [ci for ci in report.coherence_issues if ci.severity == "error"]
    assert errors, "expected an error-level coherence issue for negative mint"
    assert "tokens.T.emission_rules[0]" in errors[0].location


def test_clean_spec_has_no_sign_violations() -> None:
    """All shipped example specs should be sign-sound."""
    from pathlib import Path
    from schema import load_te
    examples = (Path(__file__).resolve().parent.parent / "examples").glob("*.yaml")
    for path in examples:
        te = load_te(path)
        violations = validate_signs(te)
        assert not violations, f"{path.name} has sign violations: {violations}"


def test_report_surfaces_function_shapes() -> None:
    """Task 3 — Report carries derived monotonicity / convexity labels."""
    ac = AsymptoticClass(
        family=AsymptoticFamily.LINEAR,
        parameter_ranges={
            "a": NumberRange(min=0.1, max=0.5),
            "b": NumberRange(min=1.0, max=2.0),
        },
    )
    report = verify(_te(ac))
    assert report.function_shapes
    # Find the emission rule's shape.
    emit_shapes = [s for s in report.function_shapes if s.rule_kind == "emission"]
    assert emit_shapes
    assert emit_shapes[0].family == "linear"
    assert emit_shapes[0].monotonicity == "increasing"
    assert emit_shapes[0].convexity == "linear"


def test_shape_summary_composes_function_with_event_frequency() -> None:
    """An event-driven rule's per-period rate is function × frequency.
    With function=constant and frequency=linear (rising), the effective
    shape must be linear-rising — not "constant" as the per-class
    description alone would suggest."""
    from pathlib import Path
    from schema import load_te
    examples = Path(__file__).resolve().parent.parent / "examples"
    te = load_te(examples / "axie_infinity.yaml")
    report = verify(te)
    slp_em = [s for s in report.function_shapes if s.token_id == "SLP" and s.rule_kind == "emission"]
    assert slp_em
    s = slp_em[0]
    assert s.monotonicity == "increasing"
    # composition prose mentions both factors.
    assert "function" in s.summary.lower()
    assert "frequency" in s.summary.lower()


def test_shape_summary_collapses_linear_with_zero_slope_to_constant() -> None:
    """A linear frequency with a={0,0} is effectively constant at b.
    Composition with a constant function must yield 'constant, linear',
    not 'increasing, linear'."""
    from pathlib import Path
    from schema import load_te
    examples = Path(__file__).resolve().parent.parent / "examples"
    te = load_te(examples / "time_bank.yaml")
    report = verify(te)
    hour_em = [s for s in report.function_shapes if s.token_id == "HOUR" and s.rule_kind == "emission"]
    assert hour_em
    s = hour_em[0]
    # service_delivered frequency: a={0,0}, b={20,180} → slope ≡ 0 → flat.
    assert s.monotonicity == "constant", s
    assert "slope" in s.summary.lower()


def test_shape_summary_unspecified_frequency_is_uncertain() -> None:
    """Axie SLP burn has frequency family=unspecified (axie_breed
    triggered by player behavior, not modeled). Shape must be
    'mixed, varies' rather than asserting a definite trajectory."""
    from pathlib import Path
    from schema import load_te
    examples = Path(__file__).resolve().parent.parent / "examples"
    te = load_te(examples / "axie_infinity.yaml")
    report = verify(te)
    slp_burn = [s for s in report.function_shapes if s.token_id == "SLP" and s.rule_kind == "burn"]
    assert slp_burn
    s = slp_burn[0]
    assert s.monotonicity == "mixed"
    assert s.convexity == "varies"


def test_shape_summary_folds_schedule_modifiers() -> None:
    """Bitcoin's emission is family=constant but Rule.schedule adds a
    halving schedule + supply cap. The derived shape MUST reflect that:
    monotonicity decreasing, convexity convex, and the summary should
    mention both the halving and the cap.
    """
    from pathlib import Path
    from schema import load_te
    examples = Path(__file__).resolve().parent.parent / "examples"
    te = load_te(examples / "bitcoin.yaml")
    report = verify(te)
    btc_shapes = [s for s in report.function_shapes if s.token_id == "BTC"]
    assert btc_shapes
    btc = btc_shapes[0]
    assert btc.monotonicity == "decreasing", btc
    assert btc.convexity == "convex", btc
    assert "halving" in btc.summary.lower()
    assert "cap" in btc.summary.lower()
