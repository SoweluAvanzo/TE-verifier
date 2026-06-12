"""Flask route tests for the webapp.

These tests use Flask's test client — no live server, no browser.
Coverage:

  * the form and YAML editor pages render
  * the simulator page renders
  * /api/example, /api/yaml-to-ir, /api/verify, /api/build-and-verify
    work against the five real example specs
  * /api/minimal-verdicts emits the ReachabilityVerdict contract
  * /api/simulate runs the real ABM (small N for test speed)
  * /api/cadcad-export emits the cadCAD config shape
  * VoteWeighting and DistributionSpec round-trip through the form
    pipeline (build IR via the JSON endpoint, verify, emit YAML)
"""

from __future__ import annotations

import pytest

# webapp imports flask; skip the suite cleanly if flask isn't installed.
flask = pytest.importorskip("flask")

from webapp.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------------------
# Pages render
# ---------------------------------------------------------------------------


def test_form_page_renders(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    html = r.data.decode("utf-8")
    # The page has the new VoteWeighting + DistributionSpec widgets.
    assert "gov-vote-weighting" in html
    assert "vw-cap_fraction" in html
    assert "vw-delegate_concentration_gini" in html
    assert "vw-reputation_gini" in html
    assert "vw-avg_lock_fraction" in html
    assert "dist-toggle" in html
    assert "dist-kind" in html
    # COMMITTEE_TRUSTED is in the actor dropdowns.
    assert "committee_trusted" in html
    # Minimal reachability view is the only verdict surface (the
    # Rich/Minimal toggle was removed; minimal is the default).
    assert 'id="minimal-view"' in html
    assert 'id="minimal-table"' in html
    assert "view-toggle-btn" not in html


def test_yaml_editor_renders(client) -> None:
    r = client.get("/yaml")
    assert r.status_code == 200


def test_simulator_page_was_removed(client) -> None:
    """Phase L2: the /simulate UI page was removed to simplify the
    pipeline. The JSON ``/api/simulate`` endpoint is retained for the
    backend (cadCAD export + tests)."""
    r = client.get("/simulate")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Example loading + verify (existing pipeline still works)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["bitcoin", "ethereum", "makerdao", "curve_vecrv", "axie_infinity"],
)
def test_example_loads_and_verifies(client, name: str) -> None:
    r = client.get(f"/api/example/{name}")
    assert r.status_code == 200
    yaml_text = r.get_json()["yaml"]
    assert yaml_text.strip().startswith(("#", "meta:"))

    r = client.post("/api/verify", json={"yaml": yaml_text})
    assert r.status_code == 200
    report = r.get_json()
    assert "verdicts" in report
    assert "severity" in report


def test_yaml_to_ir_round_trip(client) -> None:
    yaml_text = client.get("/api/example/curve_vecrv").get_json()["yaml"]
    r = client.post("/api/yaml-to-ir", json={"yaml": yaml_text})
    assert r.status_code == 200
    ir = r.get_json()["ir"]
    # New v1 field: vote_weighting survives the round-trip.
    assert ir["governance"]["vote_weighting"] == "time_locked"
    assert "vote_weighting_params" in ir["governance"]


def test_build_and_verify_with_vote_weighting(client) -> None:
    """Posting a JSON IR with vote_weighting=delegated runs FM6 with
    the substituted delegate_concentration_gini."""
    yaml_text = client.get("/api/example/makerdao").get_json()["yaml"]
    ir = client.post("/api/yaml-to-ir", json={"yaml": yaml_text}).get_json()["ir"]
    assert ir["governance"]["vote_weighting"] == "delegated"

    r = client.post("/api/build-and-verify", json={"ir": ir})
    assert r.status_code == 200
    payload = r.get_json()
    assert "report" in payload
    assert "yaml" in payload
    # The emitted YAML carries vote_weighting + params.
    assert "vote_weighting" in payload["yaml"]
    assert "delegate_concentration_gini" in payload["yaml"]


# ---------------------------------------------------------------------------
# Minimal-verdicts endpoint
# ---------------------------------------------------------------------------


def test_minimal_verdicts_endpoint(client) -> None:
    yaml_text = client.get("/api/example/axie_infinity").get_json()["yaml"]
    r = client.post("/api/minimal-verdicts", json={"yaml": yaml_text})
    assert r.status_code == 200
    verdicts = r.get_json()["verdicts"]
    assert len(verdicts) == 9  # 6 FMs across 2 tokens + 3 system-level
    # Every verdict has the contract fields.
    for v in verdicts:
        assert "structural_status" in v
        assert v["structural_status"] in {
            "sound", "fragile", "broken", "inconclusive", "not_applicable"
        }
        assert "violation_reachable" in v
        assert "satisfaction_reachable" in v
        assert "safety_predicates" in v


def test_minimal_verdicts_handles_invalid_yaml(client) -> None:
    r = client.post("/api/minimal-verdicts", json={"yaml": "not: valid: te-ir"})
    assert r.status_code == 400
    assert "error" in r.get_json()


# ---------------------------------------------------------------------------
# Simulate endpoint
# ---------------------------------------------------------------------------


def test_simulate_endpoint_returns_real_report(client) -> None:
    yaml_text = client.get("/api/example/axie_infinity").get_json()["yaml"]
    r = client.post(
        "/api/simulate",
        json={"yaml": yaml_text, "n_runs": 30, "seed": 42, "horizon_periods": 100},
    )
    assert r.status_code == 200
    report = r.get_json()
    assert report["te_name"] == "Axie Infinity"
    assert report["config"]["n_runs"] == 30
    assert report["config"]["seed"] == 42
    assert len(report["per_fm_results"]) == 9
    # At least one simulated FM with real numbers.
    simulated = [r for r in report["per_fm_results"] if r["simulated"]]
    assert simulated
    # Real numbers, not zeros.
    fm1_slp = next(
        r for r in report["per_fm_results"]
        if r["failure_mode"] == "FM1" and r["subject"] == "SLP"
    )
    assert fm1_slp["simulated"]
    assert 0.0 < fm1_slp["p_violation"] <= 1.0
    assert fm1_slp["n_violations"] > 0


def test_simulate_bounds_inputs(client) -> None:
    """The endpoint clamps n_runs and horizon to prevent abuse."""
    yaml_text = client.get("/api/example/bitcoin").get_json()["yaml"]
    r = client.post(
        "/api/simulate",
        json={"yaml": yaml_text, "n_runs": 999_999, "horizon_periods": 999_999},
    )
    assert r.status_code == 200
    cfg = r.get_json()["config"]
    assert cfg["n_runs"] <= 5000
    assert cfg["horizon_periods"] <= 5000


def test_simulate_with_bad_yaml_returns_400(client) -> None:
    r = client.post("/api/simulate", json={"yaml": "(((not yaml"})
    assert r.status_code == 400


def test_simulate_skips_broken_fms(client) -> None:
    """Axie's FM6 is BROKEN — should be in skipped, not simulated."""
    yaml_text = client.get("/api/example/axie_infinity").get_json()["yaml"]
    r = client.post(
        "/api/simulate",
        json={"yaml": yaml_text, "n_runs": 20, "seed": 1},
    )
    report = r.get_json()
    fm6 = next(r for r in report["per_fm_results"] if r["failure_mode"] == "FM6")
    assert fm6["simulated"] is False
    assert fm6["structural_status"] == "broken"


# ---------------------------------------------------------------------------
# cadCAD export endpoint
# ---------------------------------------------------------------------------


def test_cadcad_export_endpoint(client) -> None:
    yaml_text = client.get("/api/example/axie_infinity").get_json()["yaml"]
    r = client.post(
        "/api/cadcad-export",
        json={"yaml": yaml_text, "n_runs": 100, "horizon_periods": 200},
    )
    assert r.status_code == 200
    config = r.get_json()
    # Required top-level keys.
    for key in ("initial_state", "state_update_blocks", "sim_config", "params", "metadata"):
        assert key in config
    # Sim config carries the request.
    assert config["sim_config"]["N"] == 100
    assert config["sim_config"]["T"] == 200
    # At least one PSUB (Axie has FRAGILE FMs).
    assert config["state_update_blocks"]
    # The PSUB's policy carries a real safety predicate.
    psub = config["state_update_blocks"][0]
    policy_names = list(psub["policies"].keys())
    assert policy_names
    p = psub["policies"][policy_names[0]]
    assert "predicate" in p
    assert "variable" in p["predicate"]
    assert "operator" in p["predicate"]
    assert "threshold" in p["predicate"]
    # Sweepable params include the core inputs.
    assert "count_N" in config["params"]


def test_cadcad_export_carries_skipped_fms(client) -> None:
    """Verifier verdicts that aren't FRAGILE/INCONCLUSIVE land in
    metadata.skipped_fms with a reason."""
    yaml_text = client.get("/api/example/bitcoin").get_json()["yaml"]
    r = client.post("/api/cadcad-export", json={"yaml": yaml_text, "n_runs": 50})
    config = r.get_json()
    skipped = config["metadata"]["skipped_fms"]
    assert any(
        s["status"] == "sound" or s["status"] == "broken" for s in skipped
    )
    for s in skipped:
        assert "reason" in s


# ---------------------------------------------------------------------------
# Conditions metadata (existing endpoint — sanity check)
# ---------------------------------------------------------------------------


def test_conditions_endpoint(client) -> None:
    r = client.get("/api/conditions")
    assert r.status_code == 200
    data = r.get_json()
    for fm in ("FM1", "FM2", "FM3", "FM4", "FM5", "FM6"):
        assert fm in data
        assert "plain_statement" in data[fm]


# ---------------------------------------------------------------------------
# Form-built (catalog-style) IR through the full verify pipeline — the
# webapp's native output format. Regression for the FM4 catalog bug:
# the form ALWAYS emits event_id-style triggers, so this is the path
# every real user exercises.
# ---------------------------------------------------------------------------


def test_build_and_verify_catalog_ir_fm4_applicable(client) -> None:
    ir = {
        "meta": {"name": "form-e2e", "archetype": "community_reward",
                 "nfrs": {}},
        "tokens": [{
            "id": "CT",
            "function": ["medium_of_exchange"],
            "earning_mechanisms": ["behavioral_reward"],
            "contribution_verification": "peer_verification",
            "redemption_mechanism": "specific_goods_or_services",
            "offer_variety_K": {"min": 10, "max": 10},
            "emission_rules": [{
                "trigger": {"event_id": "volunteer_shift"},
                "function": {
                    "sign": "always_positive",
                    "asymptotic_class": {
                        "family": "constant",
                        "parameter_ranges": {"c": {"min": 5, "max": 5}},
                    },
                },
            }],
            "burn_rules": [],
            "initial_distribution": {"kind": "none"},
        }],
        "events": [{
            "id": "volunteer_shift",
            "label": "volunteer shift completed",
            "kind": "behavioral",
            "frequency": {
                "family": "constant",
                "parameter_ranges": {"c": {"min": 1, "max": 1}},
            },
        }],
        "participants": {
            "count_N": {"min": 100, "max": 100},
            "expected_Q": {"min": 500, "max": 500},
            "average_demand_d": {"min": 0.5, "max": 0.5},
            "growth_g": {"family": "constant"},
            "topology": "well_mixed",
            "agent_types": [{
                "id": "volunteer",
                "fraction": 1.0,
                "role": "contributor",
                "expected_holding_time": {
                    "expected_periods": {"min": 2, "max": 4},
                },
            }],
        },
        "governance": {
            "type": "dao",
            "rule_structure": {"x": "token_holder_vote"},
            "sanction_structure": {"kind": "warning"},
        },
    }
    r = client.post("/api/build-and-verify", json={"ir": ir})
    assert r.status_code == 200, r.get_json()
    report = r.get_json()["report"]
    fm4 = next(
        v for v in report["verdicts"] if v["failure_mode"].startswith("FM4")
    )
    assert fm4["status"] != "not_applicable", fm4["explanation"]
