"""P1 — counterexample parameter-name prettification.

Pins the Z3 → IR-path renaming and the dropping of `_ownE_for_fm*`
precompute duplicates so future FM additions don't silently regress
the user-visible counterexample table.
"""

from __future__ import annotations

from verifier.counterexample import (
    prettify_counterexample,
    prettify_param_name,
)


def test_emission_rule_function_param_renamed() -> None:
    assert (
        prettify_param_name("DAI_emit_0_fn__b")
        == "tokens[DAI].emission_rules[0].function.b"
    )


def test_emission_rule_event_frequency_renamed() -> None:
    assert (
        prettify_param_name("DAI_emit_0_freq__a")
        == "tokens[DAI].emission_rules[0].trigger.event_frequency.a"
    )


def test_burn_rule_renamed() -> None:
    assert (
        prettify_param_name("MKR_burn_2_fn__c")
        == "tokens[MKR].burn_rules[2].function.c"
    )


def test_cross_token_mint_renamed() -> None:
    assert (
        prettify_param_name("veCRV_xtmint_0__ratio")
        == "cross_token_flows[0] (mint→veCRV).ratio"
    )


def test_cross_token_burn_renamed() -> None:
    assert (
        prettify_param_name("MKR_xtburn_1__c")
        == "cross_token_flows[1] (burn→MKR).c"
    )


def test_per_agent_tau_renamed() -> None:
    assert (
        prettify_param_name("tau_AXS_breeder")
        == "agent_types[breeder].expected_holding_time (token AXS)"
    )


def test_aggregates_renamed() -> None:
    assert prettify_param_name("DAI__Q") == "DAI.Q (transaction volume)"
    assert prettify_param_name("DAI__E_total") == "DAI.E_total (per-period emission)"
    assert prettify_param_name("DAI__B_total") == "DAI.B_total (per-period burn)"


def test_ownE_precompute_dropped() -> None:
    """The proportional-coupling precompute duplicates have no
    user-facing meaning and should be filtered out entirely."""
    assert prettify_param_name("DAI_ownE_for_fm1_DAI_emit_0_fn__b") is None
    assert prettify_param_name("CRV_ownE_for_fm3_veCRV_emit_0_freq__a") is None


def test_unknown_name_passes_through() -> None:
    """Names we don't recognize are left unchanged so future FMs
    don't silently regress the visible output."""
    assert prettify_param_name("phi") == "phi"
    assert prettify_param_name("token_gini") == "token_gini"
    assert prettify_param_name("threshold") == "threshold"


def test_dict_renames_and_filters() -> None:
    raw = {
        "DAI_emit_0_fn__b": 5e4,
        "DAI_ownE_for_fm1_DAI_emit_0_fn__b": 5e4,  # drop
        "DAI__Q": 1e5,
        "phi": 0.0,
    }
    out = prettify_counterexample(raw)
    assert "tokens[DAI].emission_rules[0].function.b" in out
    assert "DAI.Q (transaction volume)" in out
    assert "phi" in out
    # No raw Z3 names survive
    assert all("_ownE_for_fm" not in k for k in out)
    assert all("_emit_0_fn__" not in k for k in out)
