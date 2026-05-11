"""Byte-equality regression test for the v2 FM2 entry point."""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import load_te, v2
from verifier.failure_modes.fm2_velocity import FM2VelocityTrap
from verifier.failure_modes.fm2_v2 import FM2VelocityTrapV2

EXAMPLES = ["bitcoin", "ethereum", "makerdao", "curve_vecrv", "axie_infinity"]
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _verdict_dump(verdicts):
    return [v.model_dump(mode="json") for v in verdicts]


@pytest.mark.parametrize("name", EXAMPLES)
def test_fm2v2_verdicts_byte_identical_to_v1(name: str) -> None:
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2 = v2.from_v1(te_v1)

    v1_verdicts = FM2VelocityTrap().check(te_v1)
    v2_verdicts = FM2VelocityTrapV2().check(te_v2)

    assert len(v1_verdicts) == len(v2_verdicts), (
        f"verdict count differs: v1={len(v1_verdicts)} v2={len(v2_verdicts)}"
    )

    v1_dump = _verdict_dump(v1_verdicts)
    v2_dump = _verdict_dump(v2_verdicts)
    if v1_dump != v2_dump:
        for v1d, v2d in zip(v1_dump, v2_dump):
            for k in sorted(set(v1d) | set(v2d)):
                if v1d.get(k) != v2d.get(k):
                    pytest.fail(
                        f"{name}: verdict[{v1d.get('subject')}] field "
                        f"{k!r} differs:\n  v1={v1d.get(k)!r}\n  v2={v2d.get(k)!r}"
                    )
    assert v1_dump == v2_dump


@pytest.mark.parametrize("name", EXAMPLES)
def test_fm2v2_verdict_counts_match_token_counts(name: str) -> None:
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2 = v2.from_v1(te_v1)
    v2_verdicts = FM2VelocityTrapV2().check(te_v2)
    assert len(v2_verdicts) == len(te_v2.tokens)


def test_fm2v2_passes_config_through() -> None:
    from verifier.config import VerifierConfig

    te_v1 = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    te_v2 = v2.from_v1(te_v1)
    cfg = VerifierConfig.paper_defaults()
    v1_verdicts = FM2VelocityTrap().check(te_v1, config=cfg)
    v2_verdicts = FM2VelocityTrapV2().check(te_v2, config=cfg)
    assert _verdict_dump(v1_verdicts) == _verdict_dump(v2_verdicts)


def test_fm2v2_nfr6_per_token_gating_preserved() -> None:
    """The Phase-5 fix (FM2 NFR6 circulate_fast only applies to
    medium-of-exchange tokens) must survive the v2 round-trip — AXS
    is store_of_value, so it should still FAIL while SLP gets
    PASS_AS_INTENDED."""
    te_v1 = load_te(EXAMPLES_DIR / "axie_infinity.yaml")
    te_v2 = v2.from_v1(te_v1)
    v2_verdicts = FM2VelocityTrapV2().check(te_v2)
    by_subject = {v.subject: v.status.value for v in v2_verdicts}
    assert by_subject["AXS"] == "fail"
    assert by_subject["SLP"] == "pass_as_intended"
