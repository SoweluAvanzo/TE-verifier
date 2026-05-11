"""Byte-equality regression test for the v2 FM3 entry point.

Phase B of the v2 migration introduces ``FM3BurnEmissionV2``, an FM3
checker whose input type is ``TokenEconomyV2``. Phase-B correctness is
*byte-identical verdicts* on every example: FM3(te_v1) must equal
FM3v2(from_v1(te_v1)).

These tests pin that contract. If a future change to the v1 → v2
migration (or to FM3's internals) breaks the equality, these tests
fail loudly with field-level diffs.

When the v2-native FM3 helpers land in Phase C, the adapter inside
``FM3BurnEmissionV2`` changes — but the equality must still hold (it's
the migration's whole point). So these tests stay relevant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import load_te, v2
from verifier.failure_modes.fm3_burn_emission import FM3BurnEmission
from verifier.failure_modes.fm3_v2 import FM3BurnEmissionV2

EXAMPLES = ["bitcoin", "ethereum", "makerdao", "curve_vecrv", "axie_infinity"]
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _verdict_dump(verdicts):
    """Canonicalize a list of Verdicts for equality comparison."""
    return [v.model_dump(mode="json") for v in verdicts]


@pytest.mark.parametrize("name", EXAMPLES)
def test_fm3v2_verdicts_byte_identical_to_v1(name: str) -> None:
    """For every example, FM3v2(from_v1(te_v1)) must equal FM3(te_v1).

    Equality is over the full Verdict model_dump — status,
    formal_condition, explanation, counterexample.parameter_values
    (including Z3 variable names), critical_values, recommendation,
    suggestions, swept_fields, committed_fields.
    """
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2 = v2.from_v1(te_v1)

    v1_verdicts = FM3BurnEmission().check(te_v1)
    v2_verdicts = FM3BurnEmissionV2().check(te_v2)

    assert len(v1_verdicts) == len(v2_verdicts), (
        f"verdict count differs: v1={len(v1_verdicts)} v2={len(v2_verdicts)}"
    )

    v1_dump = _verdict_dump(v1_verdicts)
    v2_dump = _verdict_dump(v2_verdicts)
    if v1_dump != v2_dump:
        # Surface the offending field per verdict for fast debugging.
        for v1d, v2d in zip(v1_dump, v2_dump):
            for k in sorted(set(v1d) | set(v2d)):
                if v1d.get(k) != v2d.get(k):
                    pytest.fail(
                        f"{name}: verdict[{v1d.get('subject')}] field "
                        f"{k!r} differs:\n  v1={v1d.get(k)!r}\n  v2={v2d.get(k)!r}"
                    )
    assert v1_dump == v2_dump


@pytest.mark.parametrize("name", EXAMPLES)
def test_fm3v2_verdict_counts_match_token_counts(name: str) -> None:
    """Sanity-check the verdict structure: FM3 returns one verdict per
    token; FM3v2 should produce the same shape."""
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2 = v2.from_v1(te_v1)
    v2_verdicts = FM3BurnEmissionV2().check(te_v2)
    assert len(v2_verdicts) == len(te_v2.tokens)


def test_fm3v2_passes_config_through() -> None:
    """The VerifierConfig argument must propagate from FM3v2 into the
    underlying FM3 — NFR1 multiplier comes from config."""
    from verifier.config import VerifierConfig

    te_v1 = load_te(EXAMPLES_DIR / "ethereum.yaml")  # NFR1 = 5 → multiplier 1.10
    te_v2 = v2.from_v1(te_v1)
    cfg = VerifierConfig.paper_defaults()

    # Run both with explicit config; verdicts must match.
    v1_verdicts = FM3BurnEmission().check(te_v1, config=cfg)
    v2_verdicts = FM3BurnEmissionV2().check(te_v2, config=cfg)
    assert _verdict_dump(v1_verdicts) == _verdict_dump(v2_verdicts)
