"""K auto-derivation from non_tokenized_assets catalog.

When a NonTokenizedAsset lists a token in ``referenced_tokens``, that
asset counts as one of the K distinct redemption opportunities for the
token (paper §3.4). The TokenEconomy validator collapses
``Token.offer_variety_K`` to the asset count regardless of any manual
declaration — catalog wins.
"""

from __future__ import annotations

import pytest

from schema import (
    Archetype,
    AssetKind,
    AsymptoticClass,
    AsymptoticFamily,
    GovernanceSpec,
    GovernanceType,
    Meta,
    NFRs,
    NonTokenizedAsset,
    NumberRange,
    ParticipantsSpec,
    Token,
    TokenEconomy,
    TokenFunction,
    Topology,
    likert_to_variety_contribution,
)


def _participants() -> ParticipantsSpec:
    return ParticipantsSpec(
        count_N=NumberRange.point(1000),
        expected_Q=NumberRange.point(100),
        average_demand_d=NumberRange.point(1.0),
        growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
        topology=Topology.WELL_MIXED,
    )


def _token(token_id: str, K: NumberRange | None = None) -> Token:
    return Token(
        id=token_id,
        function=[TokenFunction.MEDIUM_OF_EXCHANGE],
        offer_variety_K=K,
    )


def _asset(
    asset_id: str,
    *referenced_tokens: str,
    variety_contribution: int = 1,
) -> NonTokenizedAsset:
    return NonTokenizedAsset(
        id=asset_id,
        label=asset_id,
        kind=AssetKind.GOOD,
        referenced_tokens=list(referenced_tokens),
        variety_contribution=variety_contribution,
    )


def test_K_overridden_to_asset_count() -> None:
    """Three assets reference token T → K(T) = 3 regardless of manual."""
    te = TokenEconomy(
        meta=Meta(name="x", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[_token("T", K=NumberRange(min=100, max=200))],
        participants=_participants(),
        governance=GovernanceSpec(type=GovernanceType.DAO),
        non_tokenized_assets=[
            _asset("a1", "T"),
            _asset("a2", "T"),
            _asset("a3", "T"),
        ],
    )
    assert te.tokens[0].offer_variety_K.min == 3
    assert te.tokens[0].offer_variety_K.max == 3


def test_K_unchanged_when_no_assets_reference_token() -> None:
    """Token with manual K but no asset references → manual K kept."""
    te = TokenEconomy(
        meta=Meta(name="x", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[
            _token("T", K=NumberRange(min=5, max=20)),
            _token("U", K=NumberRange(min=1, max=2)),
        ],
        participants=_participants(),
        governance=GovernanceSpec(type=GovernanceType.DAO),
        non_tokenized_assets=[
            _asset("a1", "T"),  # references only T
        ],
    )
    # T overridden to 1
    T = next(t for t in te.tokens if t.id == "T")
    U = next(t for t in te.tokens if t.id == "U")
    assert T.offer_variety_K.min == T.offer_variety_K.max == 1
    # U's manual K stays
    assert U.offer_variety_K.min == 1
    assert U.offer_variety_K.max == 2


def test_K_unchanged_when_catalog_empty() -> None:
    """No assets → no override."""
    te = TokenEconomy(
        meta=Meta(name="x", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[_token("T", K=NumberRange(min=5, max=20))],
        participants=_participants(),
        governance=GovernanceSpec(type=GovernanceType.DAO),
        non_tokenized_assets=[],
    )
    assert te.tokens[0].offer_variety_K.min == 5
    assert te.tokens[0].offer_variety_K.max == 20


def test_K_derived_per_token_independently() -> None:
    """Multi-token: each gets its own asset count."""
    te = TokenEconomy(
        meta=Meta(name="x", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[_token("A"), _token("B")],
        participants=_participants(),
        governance=GovernanceSpec(type=GovernanceType.DAO),
        non_tokenized_assets=[
            _asset("a1", "A"),
            _asset("a2", "A"),
            _asset("a3", "A"),
            _asset("a4", "A"),
            _asset("b1", "B"),
        ],
    )
    A = next(t for t in te.tokens if t.id == "A")
    B = next(t for t in te.tokens if t.id == "B")
    assert A.offer_variety_K.min == A.offer_variety_K.max == 4
    assert B.offer_variety_K.min == B.offer_variety_K.max == 1


def test_asset_referencing_multiple_tokens_counts_for_each() -> None:
    """One asset referencing A and B contributes 1 to both."""
    te = TokenEconomy(
        meta=Meta(name="x", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[_token("A"), _token("B")],
        participants=_participants(),
        governance=GovernanceSpec(type=GovernanceType.DAO),
        non_tokenized_assets=[
            _asset("shared", "A", "B"),
            _asset("just_A", "A"),
        ],
    )
    A = next(t for t in te.tokens if t.id == "A")
    B = next(t for t in te.tokens if t.id == "B")
    assert A.offer_variety_K.min == A.offer_variety_K.max == 2
    assert B.offer_variety_K.min == B.offer_variety_K.max == 1


# ---------------------------------------------------------------------------
# variety_contribution + Likert mapping
# ---------------------------------------------------------------------------


def test_variety_contribution_sums() -> None:
    """K = sum of variety_contribution across referencing assets."""
    te = TokenEconomy(
        meta=Meta(name="x", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[_token("T")],
        participants=_participants(),
        governance=GovernanceSpec(type=GovernanceType.DAO),
        non_tokenized_assets=[
            _asset("a1", "T", variety_contribution=8),
            _asset("a2", "T", variety_contribution=4),
        ],
    )
    # 8 + 4 = 12
    assert te.tokens[0].offer_variety_K.min == 12
    assert te.tokens[0].offer_variety_K.max == 12


def test_default_variety_contribution_is_one() -> None:
    """Field defaults to 1 — preserves prior asset-count semantics."""
    te = TokenEconomy(
        meta=Meta(name="x", archetype=Archetype.OTHER, nfrs=NFRs()),
        tokens=[_token("T")],
        participants=_participants(),
        governance=GovernanceSpec(type=GovernanceType.DAO),
        non_tokenized_assets=[_asset("a1", "T")],
    )
    assert te.tokens[0].offer_variety_K.min == 1


@pytest.mark.parametrize("likert,expected", [
    (1, 1), (2, 3), (3, 5), (4, 10), (5, 20),
])
def test_likert_mapping(likert: int, expected: int) -> None:
    assert likert_to_variety_contribution(likert) == expected


def test_likert_clamped_out_of_range() -> None:
    assert likert_to_variety_contribution(0) == 1
    assert likert_to_variety_contribution(99) == 20
    assert likert_to_variety_contribution(-5) == 1


def test_variety_contribution_must_be_positive() -> None:
    with pytest.raises(Exception):
        NonTokenizedAsset(
            id="a", label="a", kind=AssetKind.GOOD,
            referenced_tokens=["T"], variety_contribution=0,
        )
