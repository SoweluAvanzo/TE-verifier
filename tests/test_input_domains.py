"""Inputs outside the domains the paper and the proofs assume are refused.

verifier/paper.py gives each variable's domain (N ∈ ℕ≥1, K ∈ ℕ≥1, Q ≥ 0,
d ≥ 0, γ, S, G ∈ [0, 1], M ≥ 0, τ > 0). Before these checks the schema
accepted any number, and the verifier gave confident verdicts on impossible
inputs: N = -5 "passed" FM5 because the solver's box {N ≥ 1} ∩ [-5, -5] is
empty, so no violation could be found (a vacuous PASS). A rate or event
frequency that can be negative cannot be checked here, field by field: it is
a property of the whole parameter box, so its FM1/FM3 verdicts become
INCONCLUSIVE instead (verifier/dispatcher.py).
"""

from __future__ import annotations

import copy
import glob

import pytest
import yaml
from pydantic import ValidationError

from schema import TokenEconomy
from verifier import verify
from verifier.failure_modes.base import Status

BASE = yaml.safe_load(open("examples/time_bank.yaml"))


def _with(path: list, value) -> dict:
    spec = copy.deepcopy(BASE)
    node = spec
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return spec


def _range(lo, hi=None):
    return {"min": lo, "max": lo if hi is None else hi}


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["participants", "count_N"], _range(-5)),
        (["participants", "count_N"], _range(0)),
        (["participants", "count_N"], _range(0.5)),
        (["tokens", 0, "offer_variety_K"], _range(-3)),
        (["tokens", 0, "offer_variety_K"], _range(0)),
        (["participants", "expected_Q"], _range(-1)),
        (["participants", "average_demand_d"], _range(-1, 2)),
        (["governance", "monitoring_capacity_gamma"], _range(1.5)),
        (["governance", "monitoring_capacity_gamma"], _range(-0.1)),
        (["governance", "token_balance_gini"], _range(1.5)),
        (["governance", "token_balance_gini"], _range(-0.2)),
        (["governance", "vote_weighting_params"], {"cap_fraction": _range(5)}),
        (["participants", "topology_params"], {"average_degree": _range(-6)}),
    ],
)
def test_out_of_domain_values_are_refused(path, value) -> None:
    with pytest.raises(ValidationError):
        TokenEconomy.model_validate(_with(path, value))


def test_boundary_values_are_accepted() -> None:
    spec = _with(["participants", "average_demand_d"], _range(0))
    spec["governance"]["monitoring_capacity_gamma"] = _range(0, 1)
    spec["governance"]["token_balance_gini"] = _range(0, 1)
    TokenEconomy.model_validate(spec)


def test_balance_shares_must_add_up_when_all_are_given() -> None:
    spec = copy.deepcopy(BASE)
    for a in spec["participants"]["agent_types"]:
        a["balance_share"] = 0.9
    with pytest.raises(ValidationError):
        TokenEconomy.model_validate(spec)


@pytest.mark.parametrize("path", sorted(glob.glob("examples/*.yaml")))
def test_every_example_still_validates(path: str) -> None:
    TokenEconomy.model_validate(yaml.safe_load(open(path)))


def _fm(report, fm: str, subject: str = "HOUR"):
    return next(v for v in report.verdicts if v.failure_mode.startswith(fm) and v.subject == subject)


def test_a_negative_emission_rate_withholds_fm1_and_fm3() -> None:
    spec = copy.deepcopy(BASE)
    spec["tokens"][0]["emission_rules"][0]["function"]["asymptotic_class"][
        "parameter_ranges"]["c"] = _range(-2)
    report = verify(TokenEconomy.model_validate(spec))
    for fm in ("FM1", "FM3"):
        assert _fm(report, fm).status == Status.INCONCLUSIVE
    assert any(i.severity == "error" for i in report.coherence_issues)


def test_a_negative_event_frequency_withholds_fm1_and_fm3() -> None:
    spec = copy.deepcopy(BASE)
    event_id = spec["tokens"][0]["emission_rules"][0]["trigger"]["event_id"]
    event = next(e for e in spec["events"] if e["id"] == event_id)
    event["frequency"] = {"family": "constant", "parameter_ranges": {"c": _range(-50)}}
    report = verify(TokenEconomy.model_validate(spec))
    for fm in ("FM1", "FM3"):
        assert _fm(report, fm).status == Status.INCONCLUSIVE
