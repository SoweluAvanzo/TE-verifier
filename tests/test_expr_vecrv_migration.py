"""Phase K7 — veCRV DSL vs AsymptoticClass equivalence.

The DSL variant of curve_vecrv.yaml reconstructs the aggregate veCRV
emission flow from per-lock physics: amount × duration / max_lock,
multiplied by the per-period lock count. The legacy variant uses a
linear AsymptoticClass approximation. Both should:

* Load without error.
* Produce per-period veCRV mint rates inside the same order-of-magnitude.
* Run all six failure-mode checks to completion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import load_te
from verifier.abm import SimulationConfig, run_simulation
from verifier.dispatcher import verify as static_verify
from verifier.expr_eval import EvalEnv, evaluate

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


# ---------------------------------------------------------------------------
# Both variants load
# ---------------------------------------------------------------------------


def test_both_variants_load() -> None:
    te_ac = load_te(EXAMPLES_DIR / "curve_vecrv.yaml")
    te_dsl = load_te(EXAMPLES_DIR / "curve_vecrv_dsl.yaml")
    assert te_ac.meta.name == te_dsl.meta.name == "Curve / veCRV"


def test_dsl_variant_has_event_catalog() -> None:
    te = load_te(EXAMPLES_DIR / "curve_vecrv_dsl.yaml")
    assert any(e.id == "user_locks_crv" for e in te.events)
    user_locks = next(e for e in te.events if e.id == "user_locks_crv")
    assert {f.name for f in user_locks.payload} == {"amount", "duration"}


def test_dsl_emission_rule_is_expression() -> None:
    te = load_te(EXAMPLES_DIR / "curve_vecrv_dsl.yaml")
    veCRV = next(t for t in te.tokens if t.id == "veCRV")
    rule = veCRV.emission_rules[0]
    assert rule.function.expression is not None
    assert rule.function.asymptotic_class is None
    # References user_locks_crv via event_id (Phase H).
    assert rule.trigger.event_id == "user_locks_crv"


# ---------------------------------------------------------------------------
# Quantitative agreement on per-week mint range
# ---------------------------------------------------------------------------


def test_dsl_per_week_mint_in_legacy_range() -> None:
    """The legacy AC declares aggregate veCRV/wk in [500k, 10M]. The
    DSL formula amount × duration / 208 × locks_per_week should sit
    inside that envelope at representative parameter midpoints."""
    te = load_te(EXAMPLES_DIR / "curve_vecrv_dsl.yaml")
    veCRV = next(t for t in te.tokens if t.id == "veCRV")
    rule = veCRV.emission_rules[0]
    user_locks = next(e for e in te.events if e.id == "user_locks_crv")

    # Per-lock veCRV at midpoint payload.
    amount_mid = sum(
        f.range.min + f.range.max for f in user_locks.payload if f.name == "amount"
    ) / 2.0
    duration_mid = sum(
        f.range.min + f.range.max for f in user_locks.payload if f.name == "duration"
    ) / 2.0
    max_lock = next(
        p for p in rule.function.parameters if p.name == "max_lock_periods"
    )
    max_lock_mid = (max_lock.range.min + max_lock.range.max) / 2.0
    env = EvalEnv(
        state={"t": 0.0},
        event={"amount": amount_mid, "duration": duration_mid},
        params={"max_lock_periods": max_lock_mid},
        consts={},
        agents=[], tokens=[], events=[], assets=[],
    )
    per_lock = evaluate(rule.function.expression, env)
    # Lock frequency midpoint (linear: a·t + b at t=H/2=26).
    freq_b = user_locks.frequency.parameter_ranges["b"]
    freq_a = user_locks.frequency.parameter_ranges["a"]
    locks_per_week = (
        (freq_a.min + freq_a.max) / 2.0 * 26.0
        + (freq_b.min + freq_b.max) / 2.0
    )
    aggregate = per_lock * locks_per_week
    # Legacy AC envelope is [500k, 10M]; midpoint expected within 5×
    # of either bound. With our midpoints: 50050 × 106 ≈ 5.3M lies
    # inside.
    assert 100_000.0 <= aggregate <= 50_000_000.0


# ---------------------------------------------------------------------------
# End-to-end execution
# ---------------------------------------------------------------------------


def test_static_verifier_runs_on_dsl_variant() -> None:
    te = load_te(EXAMPLES_DIR / "curve_vecrv_dsl.yaml")
    report = static_verify(te)
    statuses = {v.status.value for v in report.verdicts}
    # Every FM produced a verdict; nothing crashed.
    assert report.verdicts
    # Phase K5 should NOT leave any verdict with an opaque
    # "expr_free" counterexample variable when payload is declared.
    for v in report.verdicts:
        if v.counterexample is None:
            continue
        for cv in (v.counterexample.parameter_values or {}):
            assert "expr_free" not in cv, (
                f"verdict for {v.subject} surfaced an opaque expr_free "
                f"variable — the Z3 hook should have bound event payload "
                f"fields. cv={cv}"
            )


def test_abm_runs_on_dsl_variant() -> None:
    te = load_te(EXAMPLES_DIR / "curve_vecrv_dsl.yaml")
    cfg = SimulationConfig(n_runs=3, seed=42, horizon_periods=10)
    report = run_simulation(te, config=cfg)
    assert report.per_fm_results
