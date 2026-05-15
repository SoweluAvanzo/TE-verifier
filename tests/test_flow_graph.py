"""Phase M — declared-flow graph builder + /api/flow-graph endpoint.

The graph is a pure read of the TE-IR (no simulation). Tests confirm:

* Builder produces Cytoscape-shaped JSON with expected node + edge kinds
* Isolated wallets are pruned for compactness
* Diagnostics surface declared-vs-realisable inconsistencies
* /api/flow-graph round-trips a YAML body
* Every shipped example yields a non-empty graph
"""

from __future__ import annotations

from pathlib import Path

import pytest

flask = pytest.importorskip("flask")

from schema import load_te
from verifier.abm.flow_graph import build_flow_graph
from webapp.app import app

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------------------
# Builder — shape + content
# ---------------------------------------------------------------------------


def test_builder_returns_cytoscape_shape() -> None:
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    g = build_flow_graph(te)
    assert "elements" in g and "diagnostics" in g and "summary" in g
    assert "nodes" in g["elements"] and "edges" in g["elements"]
    for n in g["elements"]["nodes"]:
        assert "data" in n and "id" in n["data"] and "kind" in n["data"]
    for e in g["elements"]["edges"]:
        d = e["data"]
        assert {"id", "source", "target", "kind"} <= d.keys()


def test_node_kinds_cover_expected_categories() -> None:
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    g = build_flow_graph(te)
    kinds = {n["data"]["kind"] for n in g["elements"]["nodes"]}
    # All four core kinds present for cascina (mint/burn pools, wallets,
    # asset inventory, event nodes).
    assert "MintPool" in kinds
    assert "BurnSink" in kinds
    assert "RoleWallet" in kinds or "AdminWallet" in kinds
    assert "AssetInventory" in kinds
    assert "Event" in kinds


def test_edge_kinds_cover_expected_categories() -> None:
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    g = build_flow_graph(te)
    kinds = {e["data"]["kind"] for e in g["elements"]["edges"]}
    # Cascina has emission + burn + cross-token + redemption + event-drives.
    assert "Emission" in kinds
    assert "Burn" in kinds
    assert "CrossTokenFlow" in kinds
    assert "Redemption-AssetLeg" in kinds
    assert "EventDrives" in kinds


def test_compactness_below_threshold() -> None:
    """Pruning + aggregation keep every shipped example below 25 edges.
    Anything higher would be visually overwhelming."""
    for name in [
        "cascina_roccafranca", "axie_infinity", "bitcoin",
        "curve_vecrv", "time_bank", "makerdao", "ethereum",
    ]:
        te = load_te(EXAMPLES_DIR / f"{name}.yaml")
        g = build_flow_graph(te)
        assert g["summary"]["n_edges"] <= 25, (
            f"{name} has {g['summary']['n_edges']} edges — too dense"
        )
        assert g["summary"]["n_nodes"] <= 30


def test_isolated_wallets_pruned() -> None:
    """Cascina has governance_only role with no EARN/REDEEM. Its
    wallets would be isolated; the builder must prune them."""
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    g = build_flow_graph(te)
    node_ids = {n["data"]["id"] for n in g["elements"]["nodes"]}
    # casa_quartiere_staff has action_set=[hold, vote, transfer] (no
    # earn/redeem), so its wallets should be pruned for compactness.
    assert "wallet:casa_quartiere_staff@ROCCA" not in node_ids
    assert "wallet:casa_quartiere_staff@BUONO" not in node_ids


def test_diagnostics_surface_source_only_tokens() -> None:
    """Axie SLP has emission but no burn rule of its own (only via
    AXS-breed pattern). Bitcoin has no burn either."""
    te = load_te(EXAMPLES_DIR / "bitcoin.yaml")
    g = build_flow_graph(te)
    diag_kinds = {d["kind"] for d in g["diagnostics"]}
    assert "source_only_token" in diag_kinds


def test_event_nodes_only_for_referenced_events() -> None:
    """Events declared in the catalog but never referenced by any rule
    are omitted from the graph — keeps it compact."""
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    g = build_flow_graph(te)
    event_ids = {
        n["data"]["event"]
        for n in g["elements"]["nodes"]
        if n["data"]["kind"] == "Event"
    }
    # Every rule on cascina references one of these three.
    assert event_ids == {
        "volunteer_hour_logged",
        "rocca_swapped_for_buono",
        "buono_redeemed_at_shop",
    }


def test_rate_labels_are_short() -> None:
    te = load_te(EXAMPLES_DIR / "cascina_roccafranca.yaml")
    g = build_flow_graph(te)
    for e in g["elements"]["edges"]:
        label = e["data"].get("label", "")
        # Hard cap so the visual stays readable.
        assert len(label) <= 30, f"label too long: {label!r}"


# ---------------------------------------------------------------------------
# /api/flow-graph endpoint
# ---------------------------------------------------------------------------


def test_api_flow_graph_round_trips_yaml(client) -> None:
    with open(EXAMPLES_DIR / "cascina_roccafranca.yaml") as f:
        yaml_text = f.read()
    r = client.post("/api/flow-graph", json={"yaml": yaml_text})
    assert r.status_code == 200
    body = r.get_json()
    assert "elements" in body and "summary" in body
    assert body["summary"]["n_nodes"] > 0
    assert body["summary"]["n_edges"] > 0


def test_api_flow_graph_rejects_malformed_yaml(client) -> None:
    r = client.post("/api/flow-graph", json={"yaml": "not: [valid: yaml"})
    assert r.status_code == 400


@pytest.mark.parametrize("example", [
    "cascina_roccafranca", "axie_infinity", "bitcoin", "curve_vecrv",
    "time_bank", "makerdao", "ethereum",
])
def test_all_examples_build_flow_graph(example) -> None:
    """Every shipped example must produce a non-empty, structurally
    sound flow graph (catches regressions in the builder when schema
    extensions land)."""
    te = load_te(EXAMPLES_DIR / f"{example}.yaml")
    g = build_flow_graph(te)
    assert g["summary"]["n_nodes"] > 0
    # Every edge endpoint must point to an existing node id.
    node_ids = {n["data"]["id"] for n in g["elements"]["nodes"]}
    for e in g["elements"]["edges"]:
        assert e["data"]["source"] in node_ids
        assert e["data"]["target"] in node_ids
