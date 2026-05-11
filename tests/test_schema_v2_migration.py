"""Phase-A v2 migration tests.

The v2 schema lives at ``schema/te_ir_v2.py`` and is exposed via the
``schema.v2`` sub-namespace. v1 imports remain authoritative — these
tests pin the migration behavior so v1→v2 conversion stays mechanical
and lossless on every example currently in the repository.

Three classes of test:

1. **Validation parity** — every v1 example migrates without raising
   and produces a structurally-valid TokenEconomyV2.
2. **Numeric leaf preservation** — every NumberRange in v1 reaches v2
   with identical min/max.
3. **Enum fidelity** — every enum value in v1 round-trips to the same
   enum value in v2 (the v2 enums share the v1 ``.value`` strings on
   purpose).
4. **Round-trip via load_te_v2** — emit v2 YAML and reload it; the
   resulting IR is structurally identical to the direct conversion.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from schema import load_te, v2

EXAMPLES = ["bitcoin", "ethereum", "makerdao", "curve_vecrv", "axie_infinity"]
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_v1_leaves(te) -> dict[str, tuple[float, float] | int | float]:
    out: dict[str, tuple[float, float] | int | float] = {}
    out["N"] = (te.participants.count_N.min, te.participants.count_N.max)
    out["Q"] = (te.participants.expected_Q.min, te.participants.expected_Q.max)
    out["d"] = (
        te.participants.average_demand_d.min,
        te.participants.average_demand_d.max,
    )
    for t in te.tokens:
        if t.offer_variety_K is not None:
            out[f"K[{t.id}]"] = (t.offer_variety_K.min, t.offer_variety_K.max)
        if t.initial_distribution.amount is not None:
            out[f"init[{t.id}]"] = (
                t.initial_distribution.amount.min,
                t.initial_distribution.amount.max,
            )
        for i, r in enumerate(t.emission_rules):
            for k, rng in r.function.asymptotic_class.parameter_ranges.items():
                out[f"{t.id}.emit[{i}].fn.{k}"] = (rng.min, rng.max)
            if r.schedule:
                if r.schedule.supply_cap is not None:
                    out[f"{t.id}.emit[{i}].cap"] = r.schedule.supply_cap
                if r.schedule.halving_period is not None:
                    out[f"{t.id}.emit[{i}].halving_period"] = r.schedule.halving_period
        for i, r in enumerate(t.burn_rules):
            for k, rng in r.function.asymptotic_class.parameter_ranges.items():
                out[f"{t.id}.burn[{i}].fn.{k}"] = (rng.min, rng.max)
    return out


def _collect_v2_leaves(te) -> dict[str, tuple[float, float] | int | float]:
    out: dict[str, tuple[float, float] | int | float] = {}
    out["N"] = (te.participants.count_N.min, te.participants.count_N.max)
    if te.participants.expected_Q_override is not None:
        out["Q"] = (
            te.participants.expected_Q_override.min,
            te.participants.expected_Q_override.max,
        )
    out["d"] = (
        te.participants.average_demand_d.min,
        te.participants.average_demand_d.max,
    )
    for t in te.tokens:
        if t.offer_variety_K_override is not None:
            out[f"K[{t.id}]"] = (
                t.offer_variety_K_override.min,
                t.offer_variety_K_override.max,
            )
        if t.initial_distribution.amount is not None:
            out[f"init[{t.id}]"] = (
                t.initial_distribution.amount.min,
                t.initial_distribution.amount.max,
            )
        for i, fn in enumerate(t.emission_rules):
            # First phase carries the v1 shape (no regimes used in v1 examples)
            ac = fn.phases[0].shape.asymptotic_class
            for k, rng in ac.parameter_ranges.items():
                out[f"{t.id}.emit[{i}].fn.{k}"] = (rng.min, rng.max)
            if fn.schedule:
                if fn.schedule.supply_cap is not None:
                    out[f"{t.id}.emit[{i}].cap"] = fn.schedule.supply_cap
                if fn.schedule.halving_period is not None:
                    out[f"{t.id}.emit[{i}].halving_period"] = fn.schedule.halving_period
        for i, fn in enumerate(t.burn_rules):
            ac = fn.phases[0].shape.asymptotic_class
            for k, rng in ac.parameter_ranges.items():
                out[f"{t.id}.burn[{i}].fn.{k}"] = (rng.min, rng.max)
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", EXAMPLES)
def test_v1_example_migrates_without_error(name: str) -> None:
    """Each v1 example produces a structurally valid TokenEconomyV2."""
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2 = v2.from_v1(te_v1)
    assert te_v2.meta.name == te_v1.meta.name
    assert len(te_v2.tokens) == len(te_v1.tokens)
    assert len(te_v2.cross_token_flows) == len(te_v1.cross_token_flows)
    # v1 examples declare no goods, redemptions, or events
    assert te_v2.goods == []
    assert te_v2.redemptions == []
    assert te_v2.events == []


@pytest.mark.parametrize("name", EXAMPLES)
def test_numeric_leaves_preserved(name: str) -> None:
    """Every v1 NumberRange must appear in v2 with identical bounds."""
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2 = v2.from_v1(te_v1)
    v1_leaves = _collect_v1_leaves(te_v1)
    v2_leaves = _collect_v2_leaves(te_v2)
    missing = set(v1_leaves) - set(v2_leaves)
    assert not missing, f"v2 missing leaves: {missing}"
    for k, expected in v1_leaves.items():
        assert v2_leaves[k] == expected, f"leaf {k}: v1={expected} v2={v2_leaves[k]}"


@pytest.mark.parametrize("name", EXAMPLES)
def test_enum_fidelity(name: str) -> None:
    """v1 enum string values survive intact in v2."""
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2 = v2.from_v1(te_v1)

    # Tokens
    for t1, t2 in zip(te_v1.tokens, te_v2.tokens):
        assert sorted(f.value for f in t1.function) == sorted(
            f.value for f in t2.function
        )
        assert t1.value_anchor.value == t2.value_anchor.value
        for r1, r2 in zip(t1.emission_rules, t2.emission_rules):
            assert r1.trigger.kind.value == r2.trigger_kind.value
            assert r1.function.sign.value == r2.phases[0].shape.sign.value
        for r1, r2 in zip(t1.burn_rules, t2.burn_rules):
            assert r1.trigger.kind.value == r2.trigger_kind.value
            assert r1.function.sign.value == r2.phases[0].shape.sign.value

    # Governance
    assert te_v1.governance.type.value == te_v2.governance.type.value
    assert (
        te_v1.governance.sanction_structure.kind.value
        == te_v2.governance.sanction_structure.kind.value
    )
    for k, actor in te_v1.governance.rule_structure.items():
        assert actor.value == te_v2.governance.rule_structure[k].value

    # Cross-token flows
    for c1, c2 in zip(te_v1.cross_token_flows, te_v2.cross_token_flows):
        assert c1.target_action.value == c2.target_action.value
        assert c1.coupling.value == c2.coupling.value


@pytest.mark.parametrize("name", EXAMPLES)
def test_emit_yaml_roundtrips_through_load_te_v2(name: str, tmp_path: Path) -> None:
    """The YAML emitted by from_v1 must reload cleanly via load_te_v2,
    producing an IR structurally identical to the direct conversion."""
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2_direct = v2.from_v1(te_v1)

    out = tmp_path / f"{name}_v2.yaml"
    out.write_text(
        yaml.safe_dump(te_v2_direct.model_dump(mode="json", exclude_none=True))
    )

    te_v2_reloaded = v2.load_te_v2(out)
    # Structural equality via canonical JSON dump
    direct_json = te_v2_direct.model_dump(mode="json", exclude_none=True)
    reloaded_json = te_v2_reloaded.model_dump(mode="json", exclude_none=True)
    assert direct_json == reloaded_json


@pytest.mark.parametrize("name", EXAMPLES)
def test_v2_default_phase_always_present(name: str) -> None:
    """Every Function emitted by from_v1 ends with an Always() phase —
    pinned because the TokenEconomyV2 validator requires it."""
    te_v1 = load_te(EXAMPLES_DIR / f"{name}.yaml")
    te_v2 = v2.from_v1(te_v1)

    def _is_always(c) -> bool:
        return c.type == "time_window" and c.start_period == 0.0 and c.end_period is None

    for t in te_v2.tokens:
        for fn in list(t.emission_rules) + list(t.burn_rules):
            assert _is_always(fn.phases[-1].condition)
    for ctf in te_v2.cross_token_flows:
        assert _is_always(ctf.amount.phases[-1].condition)


def test_event_cycle_rejected() -> None:
    """The TokenEconomyV2 validator must reject event-causality cycles
    at schema load time — required for verifier decidability."""
    s = v2
    base = v2.from_v1(load_te(EXAMPLES_DIR / "bitcoin.yaml"))
    # Inject a cycle: A → B → A
    cyclic_events = [
        s.Event(
            id="A",
            trigger=s.Always(),
            actions=[s.FireEvent(event_id="B")],
        ),
        s.Event(
            id="B",
            trigger=s.Always(),
            actions=[s.FireEvent(event_id="A")],
        ),
    ]
    with pytest.raises(ValueError, match="event cycle"):
        s.TokenEconomyV2(
            meta=base.meta,
            tokens=base.tokens,
            participants=base.participants,
            governance=base.governance,
            events=cyclic_events,
        )


def test_missing_redemption_target_rejected() -> None:
    """Redemption pointing at a non-existent good must fail validation."""
    s = v2
    base = v2.from_v1(load_te(EXAMPLES_DIR / "bitcoin.yaml"))
    bad_redemption = s.Redemption(
        id="r1",
        source_token="BTC",
        target_good="nonexistent_good",
        exchange_rate=s.ExchangeRate(
            phases=[
                s.ExchangeRatePhase(
                    condition=s.Always(),
                    driver=s.ExchangeRateDriver.CONSTANT,
                    constant_rate=s.NumberRange.point(1.0),
                )
            ]
        ),
    )
    with pytest.raises(ValueError, match="missing good"):
        s.TokenEconomyV2(
            meta=base.meta,
            tokens=base.tokens,
            participants=base.participants,
            governance=base.governance,
            redemptions=[bad_redemption],
        )
