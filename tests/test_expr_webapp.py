"""Phase K6 — webapp build-and-verify integration for DSL rules.

POSTs a form-built JSON IR carrying a DSL ``expression`` and confirms
the server validates it, runs the verifier, and returns a report.
"""

from __future__ import annotations

import pytest

flask = pytest.importorskip("flask")

from webapp.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def _ir_with_dsl() -> dict:
    """Minimal IR shape the form posts when the user picks
    ``expression`` in the function-class dropdown."""
    return {
        "meta": {
            "name": "form-dsl",
            "archetype": "other",
            "nfrs": {},
        },
        "tokens": [{
            "id": "T",
            "function": ["medium_of_exchange"],
            "emission_rules": [{
                "trigger": {"kind": "time_based"},
                "function": {
                    "sign": "always_positive",
                    "expression": "param.a * state.t + param.b",
                    "parameters": [
                        {"name": "a", "range": {"min": 2.0, "max": 2.0}},
                        {"name": "b", "range": {"min": 5.0, "max": 5.0}},
                    ],
                },
            }],
            "offer_variety_K": {"min": 5, "max": 5},
        }],
        "participants": {
            "count_N": {"min": 1000, "max": 1000},
            "expected_Q": {"min": 100, "max": 100},
            "average_demand_d": {"min": 1, "max": 1},
            "growth_g": {"family": "constant"},
            "topology": "well_mixed",
        },
        "governance": {"type": "dao"},
    }


def test_build_and_verify_accepts_dsl(client) -> None:
    """The /api/build-and-verify endpoint validates a DSL FunctionShape
    and returns a successful verifier report."""
    resp = client.post(
        "/api/build-and-verify",
        json={"ir": _ir_with_dsl()},
    )
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert "report" in body
    assert "yaml" in body
    # The serialized YAML should round-trip the expression AST (not
    # the source string, but the structural form).
    assert "expression" in body["yaml"]


def test_build_and_verify_rejects_malformed_dsl(client) -> None:
    """A syntactically invalid expression triggers a 400 with the
    parser's diagnostic — not a 500 from the verifier."""
    ir = _ir_with_dsl()
    ir["tokens"][0]["emission_rules"][0]["function"]["expression"] = (
        "this is not valid syntax"
    )
    resp = client.post("/api/build-and-verify", json={"ir": ir})
    assert resp.status_code == 400
    err = resp.get_json().get("error", "")
    assert "validate" in err.lower() or "expr" in err.lower() or "parse" in err.lower()
