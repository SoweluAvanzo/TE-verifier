"""Phase D4 — token role derivation and per-FM applicability.

Pins both the role-derivation rules and the dispatcher's role-aware
verdict overrides (Simulator.pdf §4 multi-token table).
"""

from __future__ import annotations

from schema import (
    AgentType,
    Archetype,
    AsymptoticClass,
    AsymptoticFamily,
    BurnTriggerKind,
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
    ValueAnchor,
)
from verifier import Status, verify
from verifier.token_role import TokenRole, derive_token_role


def _emit(c: float = 1.0) -> Rule:
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


def _make_te(*, tokens) -> TokenEconomy:
    return TokenEconomy(
        meta=Meta(name="t", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=tokens,
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
            rule_structure={"x": ControllingActor.TOKEN_HOLDER_VOTE},
        ),
    )


# ---------------------------------------------------------------------------
# Derivation rules
# ---------------------------------------------------------------------------


def test_pure_reputation_token_is_reputation_role() -> None:
    t = Token(id="REP", function=[TokenFunction.REPUTATION_MARKER])
    assert derive_token_role(t) == TokenRole.REPUTATION


def test_pure_governance_token_is_governance_role() -> None:
    """MKR-shape: [governance_right, store_of_value]."""
    t = Token(
        id="MKR",
        function=[TokenFunction.GOVERNANCE_RIGHT, TokenFunction.STORE_OF_VALUE],
    )
    assert derive_token_role(t) == TokenRole.GOVERNANCE


def test_non_transferable_governance_is_governance_role() -> None:
    """veCRV-shape: [governance_right] non-transferable."""
    t = Token(
        id="veCRV",
        function=[TokenFunction.GOVERNANCE_RIGHT],
        transferable=False,
    )
    assert derive_token_role(t) == TokenRole.GOVERNANCE


def test_eth_shape_is_utility_not_governance() -> None:
    """ETH has medium_of_exchange + store_of_value + governance_right;
    the medium_of_exchange function makes it a utility token, not a
    governance token. This is the regression test for the fix that
    relaxed the original over-eager rule."""
    t = Token(
        id="ETH",
        function=[
            TokenFunction.MEDIUM_OF_EXCHANGE,
            TokenFunction.STORE_OF_VALUE,
            TokenFunction.GOVERNANCE_RIGHT,
        ],
    )
    assert derive_token_role(t) == TokenRole.UTILITY


def test_physical_quantity_anchor_is_resource_role() -> None:
    t = Token(
        id="GRAIN",
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        value_anchor=ValueAnchor.PHYSICAL_QUANTITY,
    )
    assert derive_token_role(t) == TokenRole.RESOURCE


def test_default_token_is_utility() -> None:
    t = Token(id="T", function=[TokenFunction.MEDIUM_OF_EXCHANGE])
    assert derive_token_role(t) == TokenRole.UTILITY


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


def test_governance_token_skips_fm2() -> None:
    """A pure governance token must come back NOT_APPLICABLE on FM2."""
    tokens = [
        Token(
            id="MKR",
            function=[TokenFunction.GOVERNANCE_RIGHT, TokenFunction.STORE_OF_VALUE],
            emission_rules=[_emit(c=1.0)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r = verify(_make_te(tokens=tokens))
    fm2 = next(v for v in r.verdicts
               if v.failure_mode.startswith("FM2") and v.subject == "MKR")
    assert fm2.status == Status.NOT_APPLICABLE
    assert "governance" in fm2.formal_condition.lower()


def test_governance_token_fm3_relaxed_to_pass_as_intended() -> None:
    """A governance token whose FM3 would FAIL is reclassified as
    PASS_AS_INTENDED — vote-bearing assets that don't self-deplete
    are consistent with their role (Simulator.pdf §4 relax)."""
    tokens = [
        Token(
            id="MKR",
            function=[TokenFunction.GOVERNANCE_RIGHT, TokenFunction.STORE_OF_VALUE],
            emission_rules=[_emit(c=1.0)],
            burn_rules=[],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r = verify(_make_te(tokens=tokens))
    fm3 = next(v for v in r.verdicts
               if v.failure_mode.startswith("FM3") and v.subject == "MKR")
    # Without the relax, this would be FAIL (no burn rules → ρ = 0).
    assert fm3.status == Status.PASS_AS_INTENDED
    assert "consistent with its role" in fm3.explanation


def test_reputation_token_skips_fm1_fm2_fm3() -> None:
    tokens = [
        Token(
            id="REP",
            function=[TokenFunction.REPUTATION_MARKER],
            transferable=False,
            emission_rules=[_emit(c=1.0)],
        )
    ]
    r = verify(_make_te(tokens=tokens))
    for fm_id in ("FM1", "FM2", "FM3"):
        v = next(v for v in r.verdicts
                 if v.failure_mode.startswith(fm_id) and v.subject == "REP")
        assert v.status == Status.NOT_APPLICABLE, f"{fm_id} should be N/A"


def test_resource_token_carries_fm1_mitigation_note() -> None:
    tokens = [
        Token(
            id="GRAIN",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            value_anchor=ValueAnchor.PHYSICAL_QUANTITY,
            emission_rules=[_emit(c=1.0)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r = verify(_make_te(tokens=tokens))
    fm1 = next(v for v in r.verdicts
               if v.failure_mode.startswith("FM1") and v.subject == "GRAIN")
    assert "[Phase D4]" in fm1.explanation
    assert "physical-quantity value anchor" in fm1.explanation.lower()


def test_utility_token_default_unchanged() -> None:
    """Utility tokens have no role override — verdicts behave as before."""
    tokens = [
        Token(
            id="T",
            function=[TokenFunction.MEDIUM_OF_EXCHANGE],
            emission_rules=[_emit(c=1.0)],
            offer_variety_K=NumberRange.point(5),
        )
    ]
    r = verify(_make_te(tokens=tokens))
    fm2 = next(v for v in r.verdicts
               if v.failure_mode.startswith("FM2") and v.subject == "T")
    # Utility token with default agent τ=5 and balanced NFR → PASS.
    assert fm2.status == Status.PASS
    assert "[Phase D4]" not in fm2.explanation


def test_existing_case_studies_unaffected_by_role_overrides() -> None:
    """Sanity check: derive role for every token in every example.

    No surprises — bitcoin BTC = utility, ethereum ETH = utility,
    MakerDAO {DAI=utility, MKR=governance}, Curve {CRV=governance,
    veCRV=governance}, Axie {AXS=governance, SLP=utility}.
    """
    from pathlib import Path
    import yaml

    # CRV (transferable, medium_of_exchange + governance_right) is
    # UTILITY because liquid CRV faces FM2-style velocity risk; veCRV
    # (non-transferable) is the pure governance token of the pair.
    # AXS (access_right + governance_right + store_of_value) is
    # UTILITY because access_right means it's used as gameplay
    # currency — FM1/FM2/FM3 all apply.
    expected = {
        "bitcoin": {"BTC": TokenRole.UTILITY},
        "ethereum": {"ETH": TokenRole.UTILITY},
        "makerdao": {"DAI": TokenRole.UTILITY, "MKR": TokenRole.GOVERNANCE},
        "curve_vecrv": {"CRV": TokenRole.UTILITY, "veCRV": TokenRole.GOVERNANCE},
        "axie_infinity": {"AXS": TokenRole.UTILITY, "SLP": TokenRole.UTILITY},
    }
    examples = Path(__file__).resolve().parent.parent / "examples"
    for name, want in expected.items():
        raw = yaml.safe_load((examples / f"{name}.yaml").read_text())
        te = TokenEconomy.model_validate(raw)
        for tok in te.tokens:
            if tok.id in want:
                got = derive_token_role(tok)
                assert got == want[tok.id], (
                    f"{name}/{tok.id}: expected {want[tok.id]}, got {got}"
                )
