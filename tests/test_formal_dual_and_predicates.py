"""Phase-C: formal satisfaction_reachable + SafetyPredicate contract.

Pins:

1. Each FM exposes ``is_satisfaction_reachable_when_failing`` that
   returns "true"/"false"/"unknown" via Z3 (or arithmetic for FM6).
2. Each FM exposes ``safety_predicates`` returning a list of
   SafetyPredicate objects with the expected variable/operator/
   threshold shape.
3. The minimal output uses these formally — distinguishes FRAGILE
   from BROKEN (the headline ABM-handoff signal).
4. The CLI ``--minimal`` flag emits the right shape.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from schema import load_te
from verifier.failure_modes.fm1_oversupply import FM1Oversupply
from verifier.failure_modes.fm2_velocity import FM2VelocityTrap
from verifier.failure_modes.fm3_burn_emission import FM3BurnEmission
from verifier.failure_modes.fm4_freerider import FM4FreeRider
from verifier.failure_modes.fm5_critical_mass import FM5CriticalMass
from verifier.failure_modes.fm6_governance import FM6GovernanceCapture
from verifier.minimal import StructuralStatus, minimal_verdicts
from verifier.safety_predicate import SafetyPredicate

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


# ---------------------------------------------------------------------------
# Each FM exposes safety_predicates with the right shape
# ---------------------------------------------------------------------------


def test_fm1_safety_predicate_shape() -> None:
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    preds = FM1Oversupply().safety_predicates(te, None, "SLP")
    assert len(preds) == 1
    p = preds[0]
    assert isinstance(p, SafetyPredicate)
    assert p.failure_mode == "FM1"
    assert p.variable.startswith("net_emission_per_period")
    assert p.operator == "<="
    assert p.threshold > 0  # Q_lo
    assert p.paper_section is not None
    assert "expected_Q" in " ".join(p.inputs)


def test_fm2_safety_predicate_shape() -> None:
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    preds = FM2VelocityTrap().safety_predicates(te, None, "SLP")
    assert len(preds) == 1
    p = preds[0]
    assert p.failure_mode == "FM2"
    assert p.variable.startswith("tau_bar")
    assert p.operator == ">"
    assert p.threshold == 1.5
    assert "expected_holding_time" in " ".join(p.inputs)


def test_fm3_safety_predicate_shape() -> None:
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    preds = FM3BurnEmission().safety_predicates(te, None, "SLP")
    assert len(preds) == 1
    p = preds[0]
    assert p.failure_mode == "FM3"
    assert p.variable.startswith("rho")
    assert p.operator == ">="
    assert p.threshold >= 1.0  # NFR1-adjusted


def test_fm4_emits_two_safety_predicates() -> None:
    """FM4's safety is a conjunction — both predicates must hold."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    preds = FM4FreeRider().safety_predicates(te, None, "system")
    assert len(preds) == 2
    vars_set = {p.variable for p in preds}
    assert "phi_times_K" in vars_set
    assert "gamma_times_S" in vars_set


def test_fm5_safety_predicate_shape() -> None:
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    preds = FM5CriticalMass().safety_predicates(te, None, "system")
    # At least the well-mixed predicate. Axie declares NETWORK by default
    # under the new schema, so a network predicate may also appear.
    assert len(preds) >= 1
    well_mixed = next(p for p in preds if p.variable == "N")
    assert well_mixed.operator == ">="
    assert well_mixed.threshold > 0


def test_fm6_emits_two_safety_predicates() -> None:
    """FM6's safety is a conjunction (Γ + Gini)."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    preds = FM6GovernanceCapture().safety_predicates(te, None, "system")
    vars_set = {p.variable for p in preds}
    assert "Gamma" in vars_set
    assert any(v.endswith("gini") for v in vars_set)


# ---------------------------------------------------------------------------
# Formal dual on per-FM basis
# ---------------------------------------------------------------------------


def test_fm6_dual_returns_false_for_bitcoin() -> None:
    """Bitcoin's token_balance_gini is 0.85-0.95; the safety threshold
    is 0.6. No assignment in the box passes — the dual proves
    'false' (BROKEN), not 'unknown'."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    result = FM6GovernanceCapture().is_satisfaction_reachable_when_failing(
        te, None, "system"
    )
    assert result == "false"


def test_fm6_dual_returns_true_for_curve() -> None:
    """Curve's effective Gini under TIME_LOCKED ranges 0.49-0.765;
    0.49 is below 0.6 → satisfaction reachable in some corner."""
    te = load_te(EXAMPLES_DIR / "curve_vecrv.yaml")
    result = FM6GovernanceCapture().is_satisfaction_reachable_when_failing(
        te, None, "system"
    )
    assert result == "true"


def test_fm6_dual_returns_false_when_gamma_violates() -> None:
    """Axie's rule_structure has Γ=1 (all single_entity). Γ is
    deterministic from rule_structure (no parameter shift), so the
    safety predicate Γ ≤ 0.5 is unreachable. The dual returns 'false'."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    result = FM6GovernanceCapture().is_satisfaction_reachable_when_failing(
        te, None, "system"
    )
    assert result == "false"


def test_fm3_dual_returns_false_when_no_burn() -> None:
    """A token with no burn rules and no supply cap has ρ ≡ 0; no
    assignment satisfies ρ ≥ 1. The dual returns 'false'."""
    from schema import (
        AsymptoticClass,
        AsymptoticFamily,
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

    tok = Token(
        id="T",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        emission_rules=[
            Rule(
                trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                function=FunctionShape(
                    sign=FunctionSign.ALWAYS_POSITIVE,
                    asymptotic_class=AsymptoticClass(
                        family=AsymptoticFamily.CONSTANT,
                        parameter_ranges={"c": NumberRange.point(10.0)},
                    ),
                ),
            )
        ],
        burn_rules=[],
        offer_variety_K=NumberRange.point(5),
    )
    te = TokenEconomy(
        meta=Meta(name="t", nfrs=NFRs()),
        tokens=[tok],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1.0),
            growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
            topology=Topology.WELL_MIXED,
        ),
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )
    result = FM3BurnEmission().is_satisfaction_reachable_when_failing(te, None, "T")
    # No burn AND no supply cap → structurally broken on ρ.
    assert result == "false"


def test_fm5_dual_returns_true_when_box_can_pass() -> None:
    """A TE whose declared N range includes values above 2Kd+1 must
    yield 'true' on the dual."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")  # huge N
    result = FM5CriticalMass().is_satisfaction_reachable_when_failing(
        te, None, "system"
    )
    # Bitcoin should pass FM5 anyway, so the satisfaction-dual is
    # trivially true. Confirm Z3 finds it.
    assert result == "true"


# ---------------------------------------------------------------------------
# Minimal output integration: BROKEN vs FRAGILE distinction
# ---------------------------------------------------------------------------


def test_bitcoin_fm6_is_broken_under_formal_dual() -> None:
    """The Phase-C formal dual proves Bitcoin FM6 is structurally
    BROKEN (token_gini.min > 0.6) — pre-fix this was 'inconclusive'."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    verdicts = minimal_verdicts(te)
    fm6 = next(v for v in verdicts if v.failure_mode == "FM6")
    assert fm6.structural_status == StructuralStatus.BROKEN
    assert fm6.violation_reachable == "true"
    assert fm6.satisfaction_reachable == "false"


def test_axie_fm6_is_broken_under_formal_dual() -> None:
    """Axie's Γ = 1.0 (all single_entity); no parameter shift can
    change rule_structure, so FM6 is BROKEN."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    verdicts = minimal_verdicts(te)
    fm6 = next(v for v in verdicts if v.failure_mode == "FM6")
    assert fm6.structural_status == StructuralStatus.BROKEN


def test_curve_fm6_is_fragile_under_formal_dual() -> None:
    """Curve's effective Gini under TIME_LOCKED ranges into the
    passing region — FRAGILE, not BROKEN."""
    te = load_te(EXAMPLES_DIR / "curve_vecrv.yaml")
    verdicts = minimal_verdicts(te)
    fm6 = next(v for v in verdicts if v.failure_mode == "FM6")
    assert fm6.structural_status == StructuralStatus.FRAGILE
    assert fm6.satisfaction_reachable == "true"


def test_minimal_output_carries_safety_predicates() -> None:
    """The ReachabilityVerdict must include the structured predicates
    for ABM handoff."""
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    verdicts = minimal_verdicts(te)
    # At least one FM should expose predicates.
    has_predicates = [v for v in verdicts if v.safety_predicates]
    assert len(has_predicates) > 0
    # Predicate shape sanity.
    for v in has_predicates:
        for p in v.safety_predicates:
            assert p.variable
            assert p.operator in {">=", "<=", ">", "<", "=="}
            assert isinstance(p.threshold, float)


# ---------------------------------------------------------------------------
# JSON contract — ABM handoff stability
# ---------------------------------------------------------------------------


def test_reachability_verdict_json_includes_predicates() -> None:
    te = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    verdicts = minimal_verdicts(te)
    payload = [v.model_dump(mode="json") for v in verdicts]
    # Round-trip cleanly
    serialized = json.dumps(payload)
    parsed = json.loads(serialized)
    # At least one entry has safety_predicates with the contract fields.
    found = False
    for entry in parsed:
        if entry.get("safety_predicates"):
            p = entry["safety_predicates"][0]
            assert "variable" in p
            assert "operator" in p
            assert "threshold" in p
            assert "inputs" in p
            assert "paper_section" in p
            found = True
            break
    assert found, "no safety_predicates surfaced in JSON output"


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_cli_minimal_flag_emits_table() -> None:
    result = subprocess.run(
        ["te-verify", "examples/axie_infinity.yaml", "--minimal"],
        capture_output=True,
        text=True,
        cwd=str(EXAMPLES_DIR.parent),
    )
    # Exit code may be 1 (because Axie FM6 is BROKEN) — that's the
    # documented behavior.
    assert result.returncode in (0, 1), f"unexpected exit: {result.stderr}"
    # Output is the minimal table — has the header.
    assert "FM" in result.stdout
    assert "subject" in result.stdout
    assert "status" in result.stdout
    # No multi-paragraph narrative.
    assert "Governance is captured" not in result.stdout
    assert "## FM" not in result.stdout


def test_cli_minimal_json_flag_emits_parseable_json() -> None:
    result = subprocess.run(
        ["te-verify", "examples/axie_infinity.yaml", "--minimal", "--json"],
        capture_output=True,
        text=True,
        cwd=str(EXAMPLES_DIR.parent),
    )
    assert result.returncode in (0, 1)
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert all("failure_mode" in v for v in payload)
    assert all("safety_predicates" in v for v in payload)


def test_cli_minimal_exit_code_is_1_when_broken() -> None:
    """Bitcoin has a BROKEN FM6 verdict → exit code 1 under --minimal."""
    result = subprocess.run(
        ["te-verify", "examples/bitcoin.yaml", "--minimal"],
        capture_output=True,
        text=True,
        cwd=str(EXAMPLES_DIR.parent),
    )
    assert result.returncode == 1, (
        f"expected exit 1 (broken verdict), got {result.returncode}; "
        f"stdout={result.stdout}"
    )
