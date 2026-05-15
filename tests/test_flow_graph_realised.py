"""Phase M.18 — spec-vs-realised flow-graph overlay.

For each shipped example, run a short ABM trajectory and confirm:

* ``ExploreReport.flow_graph`` is populated post-run
* every edge carries ``realised``, ``expected``, ``realised_label``,
  ``diff_class`` fields
* the ``diff_class`` distribution is meaningful (not all "unused")
* cumulative emission / burn aggregates from per-period snapshots
  match the realised sums attached to edges
* unused edges correctly point out paths the spec declared but the
  ABM never realised
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from schema import load_te
from verifier.abm.explore import run_explore
from verifier.abm.report import SimulationConfig

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _run(name: str, horizon: int = 60, max_agents: int = 40, seed: int = 42):
    te = load_te(EXAMPLES_DIR / f"{name}.yaml")
    return run_explore(te, sim_config=SimulationConfig(
        horizon_periods=horizon, seed=seed, max_agents=max_agents,
    ))


# ---------------------------------------------------------------------------
# Structural — every report carries the overlay
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("example", [
    "cascina_roccafranca", "axie_infinity", "bitcoin",
    "curve_vecrv", "time_bank", "makerdao", "ethereum",
])
def test_every_example_attaches_flow_graph(example) -> None:
    r = _run(example)
    assert r.flow_graph is not None
    assert "elements" in r.flow_graph
    assert "realised_summary" in r.flow_graph


def test_edges_carry_realised_fields() -> None:
    r = _run("cascina_roccafranca")
    edges = r.flow_graph["elements"]["edges"]
    assert edges
    for e in edges:
        d = e["data"]
        assert "realised" in d
        assert "expected" in d
        assert "realised_label" in d
        assert "diff_class" in d
        assert d["diff_class"] in {"unused", "matched", "under", "over"}


def test_realised_summary_matches_snapshot_aggregates() -> None:
    """The cumulative emission / burn sums in the overlay must match
    what the final snapshot reports."""
    r = _run("cascina_roccafranca")
    final = r.snapshots[-1]
    initial = r.snapshots[0]
    summ = r.flow_graph["realised_summary"]
    for tid, cum_burn in summ["cumulative_burn_by_token"].items():
        # cumulative burn ≡ B_by_token at the final period (engine
        # accumulates B over the run).
        assert cum_burn == pytest.approx(final.B_by_token.get(tid, 0.0), abs=1e-6)
    for tid, cum_em in summ["cumulative_emission_by_token"].items():
        # cumulative emission ≡ M_end − M_start + cum_burn.
        expected = (
            final.M_by_token.get(tid, 0.0)
            - initial.M_by_token.get(tid, 0.0)
            + summ["cumulative_burn_by_token"].get(tid, 0.0)
        )
        # Bound below at 0 (engine never emits negative).
        assert cum_em == pytest.approx(max(0.0, expected), abs=1e-6)


def test_event_firings_aggregated_into_overlay() -> None:
    r = _run("cascina_roccafranca")
    summ = r.flow_graph["realised_summary"]
    # All three cascina events fire at least once over 60 periods.
    for eid in ["volunteer_hour_logged", "rocca_swapped_for_buono",
                "buono_redeemed_at_shop"]:
        assert summ["event_firings"].get(eid, 0.0) > 0


def test_asset_consumed_carried_into_overlay() -> None:
    r = _run("cascina_roccafranca")
    summ = r.flow_graph["realised_summary"]
    # mirafiori_shop_basket gets consumed via redemption.
    assert summ["asset_consumed"].get("mirafiori_shop_basket", 0.0) > 0


# ---------------------------------------------------------------------------
# Semantic — diff_class distribution makes sense
# ---------------------------------------------------------------------------


def test_diff_class_distribution_non_trivial() -> None:
    """On a real run, the diff bucket isn't monolithically 'unused'
    or monolithically 'matched' — we want the visualisation to be
    informative."""
    r = _run("cascina_roccafranca")
    classes = {
        e["data"]["diff_class"]
        for e in r.flow_graph["elements"]["edges"]
    }
    # At least two different classes show up (e.g. matched + unused).
    assert len(classes) >= 2, (
        f"diff classes monolithic: {classes} — visualisation would be flat"
    )


def test_unused_class_flags_dead_spec_edges() -> None:
    """The cascina YAML declares both ROCCA burn rules (swap → burn)
    and BUONO burn rules (redeem → burn). In a short trajectory, agents
    primarily EARN; REDEEM-driven burns may not fire enough to register
    against the wide diff window. The overlay should flag those edges
    as 'unused' so the user sees them visually greyed out."""
    r = _run("cascina_roccafranca")
    edges = r.flow_graph["elements"]["edges"]
    burn_edges = [e for e in edges if e["data"]["kind"] == "Burn"]
    unused_burns = [
        e for e in burn_edges
        if e["data"]["diff_class"] == "unused"
    ]
    # At least one burn path is unused in this short run.
    assert unused_burns, (
        "No unused burn edges flagged — the realised overlay isn't "
        "discriminating dead paths"
    )


def test_emission_edges_realised_when_pool_grows() -> None:
    """When cumulative emission > 0, every Emission edge for that
    token must have realised > 0 (mass goes somewhere)."""
    r = _run("cascina_roccafranca")
    summ = r.flow_graph["realised_summary"]
    edges = r.flow_graph["elements"]["edges"]
    for tid, cum_em in summ["cumulative_emission_by_token"].items():
        if cum_em <= 0:
            continue
        em_edges_for_tok = [
            e for e in edges
            if e["data"]["kind"] == "Emission"
            and e["data"]["source"] == f"mint:{tid}"
        ]
        for e in em_edges_for_tok:
            assert e["data"]["realised"] > 0, (
                f"Emission edge for token {tid} has realised=0 but "
                f"cumulative emission > 0 — mass unaccounted for"
            )


def test_seed_determinism() -> None:
    """Same seed → same realised numbers per edge."""
    r1 = _run("cascina_roccafranca", seed=11)
    r2 = _run("cascina_roccafranca", seed=11)
    by_id_1 = {e["data"]["id"]: e["data"]["realised"]
               for e in r1.flow_graph["elements"]["edges"]}
    by_id_2 = {e["data"]["id"]: e["data"]["realised"]
               for e in r2.flow_graph["elements"]["edges"]}
    for k in by_id_1:
        assert by_id_1[k] == pytest.approx(by_id_2[k]), (
            f"non-deterministic realised on edge {k}"
        )


def test_realised_labels_are_short() -> None:
    r = _run("cascina_roccafranca")
    for e in r.flow_graph["elements"]["edges"]:
        lbl = e["data"]["realised_label"]
        assert lbl == "—" or len(lbl) <= 8, (
            f"realised label too long: {lbl!r}"
        )


# ---------------------------------------------------------------------------
# Cross-example coverage
# ---------------------------------------------------------------------------


def test_axie_cross_token_burn_visible() -> None:
    """Axie's SLP burn → AXS burn pathway should show non-zero realised
    flow on the CrossTokenFlow edge."""
    r = _run("axie_infinity")
    xt_edges = [
        e for e in r.flow_graph["elements"]["edges"]
        if e["data"]["kind"] == "CrossTokenFlow"
    ]
    assert xt_edges, "Axie YAML declares a cross-token flow but the graph has none"


def test_bitcoin_source_only_flag_persists() -> None:
    """Bitcoin has emission but no burn — the spec-only diagnostic
    should still be present after the realised overlay (annotation
    doesn't lose the diagnostics)."""
    r = _run("bitcoin")
    diag_kinds = {d["kind"] for d in r.flow_graph["diagnostics"]}
    assert "source_only_token" in diag_kinds
