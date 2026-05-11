"""Byte-equality regression tests for the v2 FM4 / FM5 / FM6 entry points.

Mirrors the FM1/FM2/FM3 equivalence tests. Per-example byte-equality +
verdict-count sanity + config propagation, for each of the three
remaining failure modes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schema import load_te, v2
from verifier.config import VerifierConfig
from verifier.failure_modes.fm4_freerider import FM4FreeRider
from verifier.failure_modes.fm4_v2 import FM4FreeRiderV2
from verifier.failure_modes.fm5_critical_mass import FM5CriticalMass
from verifier.failure_modes.fm5_v2 import FM5CriticalMassV2
from verifier.failure_modes.fm6_governance import FM6GovernanceCapture
from verifier.failure_modes.fm6_v2 import FM6GovernanceCaptureV2

EXAMPLES = ["bitcoin", "ethereum", "makerdao", "curve_vecrv", "axie_infinity"]
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


PAIRS = [
    ("FM4", FM4FreeRider, FM4FreeRiderV2),
    ("FM5", FM5CriticalMass, FM5CriticalMassV2),
    ("FM6", FM6GovernanceCapture, FM6GovernanceCaptureV2),
]


def _verdict_dump(verdicts):
    return [v.model_dump(mode="json") for v in verdicts]


@pytest.mark.parametrize("fm_label, v1_cls, v2_cls", PAIRS)
@pytest.mark.parametrize("name", EXAMPLES)
def test_v2_verdicts_byte_identical_to_v1(
    fm_label: str, v1_cls, v2_cls, name: str
) -> None:
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2 = v2.from_v1(te_v1)

    v1_verdicts = v1_cls().check(te_v1)
    v2_verdicts = v2_cls().check(te_v2)

    assert len(v1_verdicts) == len(v2_verdicts), (
        f"{fm_label} {name}: verdict count differs: "
        f"v1={len(v1_verdicts)} v2={len(v2_verdicts)}"
    )

    v1_dump = _verdict_dump(v1_verdicts)
    v2_dump = _verdict_dump(v2_verdicts)
    if v1_dump != v2_dump:
        for v1d, v2d in zip(v1_dump, v2_dump):
            for k in sorted(set(v1d) | set(v2d)):
                if v1d.get(k) != v2d.get(k):
                    pytest.fail(
                        f"{fm_label} {name}: verdict[{v1d.get('subject')}] "
                        f"field {k!r} differs:\n"
                        f"  v1={v1d.get(k)!r}\n  v2={v2d.get(k)!r}"
                    )
    assert v1_dump == v2_dump


@pytest.mark.parametrize("fm_label, v1_cls, v2_cls", PAIRS)
def test_v2_config_propagates(fm_label: str, v1_cls, v2_cls) -> None:
    te_v1 = load_te(EXAMPLES_DIR / "makerdao.yaml")
    te_v2 = v2.from_v1(te_v1)
    cfg = VerifierConfig.paper_defaults()
    v1_verdicts = v1_cls().check(te_v1, config=cfg)
    v2_verdicts = v2_cls().check(te_v2, config=cfg)
    assert _verdict_dump(v1_verdicts) == _verdict_dump(v2_verdicts), (
        f"{fm_label}: config propagation diverged"
    )


def test_fm4v2_pegged_exemption_preserved() -> None:
    """The Phase-5 fix (FM4 not applicable to value_anchor=pegged
    tokens like DAI) must survive the v2 round-trip — MakerDAO's FM4
    should be N/A, not FAIL on the contribution clause."""
    te_v1 = load_te(EXAMPLES_DIR / "makerdao.yaml")
    te_v2 = v2.from_v1(te_v1)
    v2_verdicts = FM4FreeRiderV2().check(te_v2)
    assert len(v2_verdicts) == 1
    assert v2_verdicts[0].status.value == "not_applicable"


def test_fm6v2_indefinite_centralization_reframed() -> None:
    """When NFR7 = indefinite, an FM6 fail driven by Γ alone should
    be reframed as design-intended. Bitcoin uses indefinite + non-
    adjustable block reward but DOES have a Gini concern; that
    Gini-driven fail should still hold."""
    te_v1 = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    te_v2 = v2.from_v1(te_v1)
    v2_verdicts = FM6GovernanceCaptureV2().check(te_v2)
    # Should be fail (Gini) regardless of NFR7
    assert v2_verdicts[0].status.value == "fail"


def test_fm5v2_network_topology_param_preserved() -> None:
    """Curve declares topology=network with average_degree in
    topology_params. The adapter must carry it through so FM5's
    network-corrected threshold applies."""
    te_v1 = load_te(EXAMPLES_DIR / "curve_vecrv.yaml")
    te_v2 = v2.from_v1(te_v1)
    assert "average_degree" in te_v2.participants.topology_params
    v1_verdicts = FM5CriticalMass().check(te_v1)
    v2_verdicts = FM5CriticalMassV2().check(te_v2)
    assert _verdict_dump(v1_verdicts) == _verdict_dump(v2_verdicts)
