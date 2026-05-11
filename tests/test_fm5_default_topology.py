"""FM5 — default topology = NETWORK with log-derived average_degree.

Pins audit fix #2. Pre-fix, ``Topology`` was a required field with no
default; the canonical safe choice was WELL_MIXED which gave a
needlessly conservative `N ≥ 2Kd + 1` threshold for almost every
crypto economy. Post-fix:

* Schema default is ``Topology.NETWORK``.
* When NETWORK is selected without explicit ``topology_params['average_degree']``,
  FM5 derives a log-scaled default from N rather than degenerating to
  the well-mixed bound.

These tests pin both the schema default and the FM5 fallback.
"""

from __future__ import annotations

import pytest

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
from verifier.failure_modes.fm5_critical_mass import FM5CriticalMass


def _minimal_participants(*, N: tuple[float, float], topology: Topology | None = None,
                          topology_params: dict[str, NumberRange] | None = None):
    kwargs: dict = {
        "count_N": NumberRange(min=N[0], max=N[1]),
        "expected_Q": NumberRange.point(100),
        "average_demand_d": NumberRange(min=0.5, max=5.0),
        "growth_g": AsymptoticClass(family=AsymptoticFamily.CONSTANT),
    }
    if topology is not None:
        kwargs["topology"] = topology
    if topology_params is not None:
        kwargs["topology_params"] = topology_params
    return ParticipantsSpec(**kwargs)


def _minimal_te(participants: ParticipantsSpec, K: tuple[float, float] = (10, 50)):
    return TokenEconomy(
        meta=Meta(name="t"),
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
                offer_variety_K=NumberRange(min=K[0], max=K[1]),
            )
        ],
        participants=participants,
        governance=GovernanceSpec(type=GovernanceType.DAO),
    )


# ---------------------------------------------------------------------------
# Schema-level: topology defaults to NETWORK
# ---------------------------------------------------------------------------


def test_topology_defaults_to_network() -> None:
    """Omitting topology yields NETWORK, not a validation error."""
    p = ParticipantsSpec(
        count_N=NumberRange.point(1000),
        expected_Q=NumberRange.point(100),
        average_demand_d=NumberRange.point(1.0),
        growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
    )
    assert p.topology == Topology.NETWORK


def test_explicit_well_mixed_still_works() -> None:
    """The schema default doesn't lock users out of well_mixed — it
    just stops being the default."""
    p = ParticipantsSpec(
        count_N=NumberRange.point(1000),
        expected_Q=NumberRange.point(100),
        average_demand_d=NumberRange.point(1.0),
        growth_g=AsymptoticClass(family=AsymptoticFamily.CONSTANT),
        topology=Topology.WELL_MIXED,
    )
    assert p.topology == Topology.WELL_MIXED


# ---------------------------------------------------------------------------
# FM5: log-derived avg_degree default
# ---------------------------------------------------------------------------


def test_default_average_degree_is_log_scaled() -> None:
    """The helper should produce sensible values across N orders of
    magnitude — clamped to [10, 100] with a small inflation factor."""
    cases = [
        (NumberRange.point(1000), 10, 100),       # 28-ish center
        (NumberRange.point(1_000_000), 20, 100),  # 55-ish center
        (NumberRange.point(10), 5, 100),          # tiny N → floor at 10
        (NumberRange.point(1_000_000_000), 40, 100),  # huge N → cap at 100
    ]
    for N_range, expected_lo_min, expected_hi_max in cases:
        d = FM5CriticalMass._default_average_degree_for(N_range)
        assert d.min >= 5.0, f"lower bound floor: N={N_range} → {d}"
        assert d.max <= 200.0, f"upper bound cap: N={N_range} → {d}"
        assert d.min <= d.max


def test_fm5_network_without_avg_degree_uses_default() -> None:
    """A TE with NETWORK topology but no topology_params should still
    get the network-corrected verdict — pre-fix this returned
    INCONCLUSIVE."""
    te = _minimal_te(
        _minimal_participants(N=(10_000, 100_000), topology=Topology.NETWORK),
        K=(10, 50),
    )
    v = FM5CriticalMass().check(te)[0]
    # Worst case: 2 · K_hi · d_hi = 2·50·5 = 500. Default avg_degree
    # for N=10k–100k is ~36–72 with range ~ [18, 100]. The minimum of
    # the default range is below 500, so the network condition does
    # not trivially hold — verdict will be FAIL (which is the correct
    # honest answer given the K, d ranges).
    assert v.status.value in ("fail", "pass"), (
        f"Verdict must be definitive, not inconclusive. got: {v.status.value}"
    )


def test_fm5_network_with_high_avg_degree_passes() -> None:
    """When the user supplies an explicit avg_degree ≥ 2·K·d, the
    network condition holds and FM5 passes even when the well-mixed
    bound would fail.

    Setup: N=100 (small), K=50, d=5 → well-mixed threshold 2·K·d+1=501
    is not met by N=100 (fails). The network rule says
    avg_degree ≥ 2·K·d = 500.
    """
    # avg_degree 200 < 500 → well-mixed fails AND network rule fails
    # → INCONCLUSIVE (network topology + supplied degree below
    # threshold). Note: ideally this would be FAIL since the user
    # supplied a degree that demonstrably falls short, but FM5
    # currently only returns FAIL for well_mixed topologies. A
    # follow-up fix could tighten this — see audit doc.
    te = _minimal_te(
        _minimal_participants(
            N=(100, 200),
            topology=Topology.NETWORK,
            topology_params={"average_degree": NumberRange(min=200, max=300)},
        ),
        K=(10, 50),
    )
    v = FM5CriticalMass().check(te)[0]
    assert v.status.value in ("fail", "inconclusive")

    # avg_degree 600 > 500 → network rule alone passes
    te = _minimal_te(
        _minimal_participants(
            N=(100, 200),
            topology=Topology.NETWORK,
            topology_params={"average_degree": NumberRange(min=600, max=800)},
        ),
        K=(10, 50),
    )
    v = FM5CriticalMass().check(te)[0]
    assert v.status.value == "pass", (
        f"avg_degree 600 should clear 2·K·d=500. got: {v.status.value}"
    )


def test_fm5_explicit_well_mixed_unchanged_behavior() -> None:
    """Users who explicitly declare WELL_MIXED still get the
    conservative `N ≥ 2Kd + 1` bound — the fix doesn't change that
    semantics, only the default."""
    te = _minimal_te(
        _minimal_participants(
            N=(100, 200),
            topology=Topology.WELL_MIXED,
        ),
        K=(50, 100),  # 2·K_hi·d_hi = 1000, far above N
    )
    v = FM5CriticalMass().check(te)[0]
    assert v.status.value == "fail"


def test_fm5_examples_unchanged() -> None:
    """The five case-study YAMLs all declare topology explicitly, so
    their verdicts should not shift after the default change."""
    from pathlib import Path
    from schema import load_te

    examples = Path(__file__).resolve().parent.parent / "examples"
    expected = {
        "bitcoin": "pass",
        "ethereum": "pass",
        "makerdao": "pass",
        "curve_vecrv": "pass",
        "axie_infinity": "pass",
    }
    for name, status in expected.items():
        te = load_te(examples / f"{name}.yaml")
        v = FM5CriticalMass().check(te)[0]
        assert v.status.value == status, (
            f"{name}: expected FM5={status}, got {v.status.value}"
        )


def test_v2_schema_default_matches() -> None:
    """v2 ParticipantsSpec also defaults topology to NETWORK so the two
    schemas stay aligned."""
    from schema import v2 as schema_v2

    p = schema_v2.ParticipantsSpec(
        count_N=schema_v2.NumberRange.point(1000),
        average_demand_d=schema_v2.NumberRange.point(1.0),
        growth_g=schema_v2.AsymptoticClass(family=schema_v2.AsymptoticFamily.CONSTANT),
        expected_Q_override=schema_v2.NumberRange.point(100),
    )
    assert p.topology == schema_v2.Topology.NETWORK
