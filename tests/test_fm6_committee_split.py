"""FM6 — COMMITTEE vs COMMITTEE_TRUSTED distinction.

Pins the audit-driven fix: ``ControllingActor.COMMITTEE`` represents a
voting / multisig committee whose internal vote dynamics distribute
control — NOT counted as unilateral in Γ. ``COMMITTEE_TRUSTED`` is the
new variant for a small trusted group acting by fiat — counted as
unilateral.

Background: pre-fix, `committee` was lumped with `single_entity` in
the Γ computation. This over-flagged every committee-governed
protocol (Bitcoin core devs, EIP process, multisig treasuries). The
paper's §3.6 definition is "decisions that can be taken unilaterally";
voting committees do not match that.
"""

from __future__ import annotations

from schema import (
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    ControllingActor,
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
from verifier import Status
from verifier.failure_modes.fm6_governance import (
    UNILATERAL_ACTORS,
    FM6GovernanceCapture,
)


def _make_te_with_actors(actors: dict[str, ControllingActor]) -> TokenEconomy:
    """Build a minimal TE with the given rule_structure mapping."""
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[
            Token(
                id="T",
                function=[TokenFunction.MEDIUM_OF_EXCHANGE],
                emission_rules=[
                    Rule(
                        trigger=RuleTrigger(kind=EmissionTriggerKind.TIME_BASED),
                        function=FunctionShape(
                            sign=FunctionSign.ALWAYS_POSITIVE,
                            asymptotic_class=AsymptoticClass(
                                family=AsymptoticFamily.CONSTANT,
                                parameter_ranges={"c": NumberRange.point(1.0)},
                            ),
                        ),
                    )
                ],
                offer_variety_K=NumberRange.point(5),
            )
        ],
        participants=ParticipantsSpec(
            count_N=NumberRange.point(1000),
            expected_Q=NumberRange.point(100),
            average_demand_d=NumberRange.point(1),
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
            rule_structure=actors,
        ),
    )


def test_unilateral_actors_set_contents() -> None:
    """The set itself encodes the fix — pin it to detect regressions."""
    assert ControllingActor.SINGLE_ENTITY in UNILATERAL_ACTORS
    assert ControllingActor.COMMITTEE_TRUSTED in UNILATERAL_ACTORS
    assert ControllingActor.COMMITTEE not in UNILATERAL_ACTORS, (
        "COMMITTEE must NOT be in UNILATERAL_ACTORS — it represents "
        "voting/multisig with internal distributed control"
    )
    assert ControllingActor.TOKEN_HOLDER_VOTE not in UNILATERAL_ACTORS
    assert ControllingActor.SMART_CONTRACT not in UNILATERAL_ACTORS


def test_all_committee_governance_yields_gamma_zero() -> None:
    """A TE whose every decision is COMMITTEE-controlled has Γ = 0
    under the new semantics — voting committees do not concentrate
    control as a single actor."""
    te = _make_te_with_actors(
        {
            "rule_a": ControllingActor.COMMITTEE,
            "rule_b": ControllingActor.COMMITTEE,
            "rule_c": ControllingActor.COMMITTEE,
        }
    )
    v = FM6GovernanceCapture().check(te)[0]
    # Status may still be inconclusive if there's no Gini to flag, but
    # Γ must be 0.
    if v.counterexample:
        assert v.counterexample.parameter_values["gamma"] == 0.0
        assert v.counterexample.parameter_values["unilateral_count"] == 0.0
    # Without a Gini signal or rule-structure capture, the verdict is
    # PASS (no concern raised).
    assert v.status == Status.PASS


def test_all_committee_trusted_yields_gamma_one() -> None:
    """A TE whose every decision is COMMITTEE_TRUSTED has Γ = 1 —
    captured. This is the variant for non-voting trusted groups."""
    te = _make_te_with_actors(
        {
            "rule_a": ControllingActor.COMMITTEE_TRUSTED,
            "rule_b": ControllingActor.COMMITTEE_TRUSTED,
            "rule_c": ControllingActor.COMMITTEE_TRUSTED,
        }
    )
    v = FM6GovernanceCapture().check(te)[0]
    assert v.status == Status.FAIL
    assert v.counterexample is not None
    assert v.counterexample.parameter_values["gamma"] == 1.0
    assert v.counterexample.parameter_values["unilateral_count"] == 3.0


def test_mixed_committee_and_committee_trusted() -> None:
    """COMMITTEE_TRUSTED counts toward Γ; COMMITTEE does not. A mix
    of the two reports Γ = (count of trusted) / total."""
    te = _make_te_with_actors(
        {
            "rule_a": ControllingActor.COMMITTEE_TRUSTED,
            "rule_b": ControllingActor.COMMITTEE,
            "rule_c": ControllingActor.COMMITTEE,
            "rule_d": ControllingActor.TOKEN_HOLDER_VOTE,
        }
    )
    v = FM6GovernanceCapture().check(te)[0]
    # Γ = 1/4 = 0.25, below the 0.5 threshold → PASS
    assert v.status == Status.PASS
    if v.counterexample:
        assert v.counterexample.parameter_values["gamma"] == 0.25
        assert v.counterexample.parameter_values["unilateral_count"] == 1.0
        assert v.counterexample.parameter_values["total_count"] == 4.0


def test_single_entity_still_unilateral() -> None:
    """Sanity check: the existing SINGLE_ENTITY behavior is unchanged."""
    te = _make_te_with_actors(
        {
            "rule_a": ControllingActor.SINGLE_ENTITY,
            "rule_b": ControllingActor.SINGLE_ENTITY,
        }
    )
    v = FM6GovernanceCapture().check(te)[0]
    assert v.status == Status.FAIL
    assert v.counterexample is not None
    assert v.counterexample.parameter_values["gamma"] == 1.0


def test_bitcoin_committees_no_longer_drive_gamma() -> None:
    """Bitcoin's protocol_change and consensus_rules use COMMITTEE
    (multi-stakeholder core dev process). Post-fix, Γ for Bitcoin
    drops from 0.5 to 0.0 because both committees are now correctly
    classified as non-unilateral. The verdict remains FAIL because
    the Gini secondary signal still triggers."""
    from schema import load_te
    from pathlib import Path

    examples = Path(__file__).resolve().parent.parent / "examples"
    te = load_te(examples / "bitcoin.yaml")
    v = FM6GovernanceCapture().check(te)[0]
    assert v.status == Status.FAIL  # Gini-driven
    if v.counterexample:
        # No actor in Bitcoin's rule_structure is COMMITTEE_TRUSTED or
        # SINGLE_ENTITY, so unilateral_count is 0 — verdict is
        # Gini-only.
        assert v.counterexample.parameter_values.get("unilateral_count", 0) == 0.0
        assert "Gini" in v.explanation


def test_migration_v1_committee_preserves_value() -> None:
    """The v1 → v2 migration must preserve COMMITTEE as COMMITTEE (the
    new voting-committee semantics) and COMMITTEE_TRUSTED as
    COMMITTEE_TRUSTED. No silent re-interpretation."""
    from schema import v2 as schema_v2

    te_v1 = _make_te_with_actors(
        {
            "rule_a": ControllingActor.COMMITTEE,
            "rule_b": ControllingActor.COMMITTEE_TRUSTED,
            "rule_c": ControllingActor.SINGLE_ENTITY,
        }
    )
    te_v2 = schema_v2.from_v1(te_v1)
    actors_v2 = {
        k: a.value for k, a in te_v2.governance.rule_structure.items()
    }
    assert actors_v2 == {
        "rule_a": "committee",
        "rule_b": "committee_trusted",
        "rule_c": "single_entity",
    }
