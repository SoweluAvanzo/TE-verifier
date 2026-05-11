"""Per-period simulation state.

Plain dict + thin accessors. cadCAD-compatible: the dict is the
state, period-update functions take and return a dict. No hidden
classes the future cadCAD config would have to unwrap.

Layout (all values are floats unless noted):

    state["t"]                            current period
    state["tokens"][token_id]["M"]        circulating supply
    state["tokens"][token_id]["E"]        per-period emission rate
    state["tokens"][token_id]["B"]        per-period burn rate
    state["Q"]                            transaction volume / period
    state["N"]                            participant count
    state["phi"]                          contributor fraction
    state["gamma"]                        monitoring capacity
    state["S"]                            sanction magnitude
    state["d"]                            average demand
    state["K"][token_id]                  offer variety
    state["Gamma_central"]                FM6 Γ (centralization)
    state["effective_gini"]               FM6 Gini under vote_weighting
    state["tau_bar"][token_id]            wealth-weighted holding time
    state["average_degree"]               for NETWORK topology

Convention: only the keys an FM uses get populated. The engine knows
which keys are needed per predicate and pre-populates accordingly.
"""

from __future__ import annotations

from typing import Any

State = dict[str, Any]


def initial_state(*, token_ids: list[str], t: int = 0) -> State:
    """Build an empty state shell. Engine fills it via the per-FM
    initializers before the simulation loop."""
    return {
        "t": t,
        "tokens": {tid: {"M": 0.0, "E": 0.0, "B": 0.0} for tid in token_ids},
        "Q": 0.0,
        "N": 0.0,
        "phi": 0.0,
        "gamma": 0.0,
        "S": 0.0,
        "d": 0.0,
        "K": {tid: 0.0 for tid in token_ids},
        "Gamma_central": 0.0,
        "effective_gini": 0.0,
        "tau_bar": {tid: 0.0 for tid in token_ids},
        "average_degree": 0.0,
    }


def derived_variable(state: State, var: str) -> float:
    """Resolve a predicate variable name to a state value.

    Names follow the convention used by ``FailureMode.safety_predicates``:

    * ``net_emission_per_period[TOKEN]``   → tokens[T].E - tokens[T].B
    * ``rho[TOKEN]``                       → tokens[T].B / tokens[T].E
    * ``tau_bar[TOKEN]``                   → tau_bar[T]
    * ``phi_times_K``                      → phi · max(K_t for any t)
    * ``gamma_times_S``                    → gamma · S
    * ``N``, ``average_degree``            → flat keys
    * ``Gamma``                            → Gamma_central
    * ``effective_gini``                   → effective_gini
    * ``token_balance_gini``               → effective_gini (alias for LINEAR)

    Unknown names raise ``KeyError`` — predicate authors should not
    introduce variables without updating this resolver.
    """
    # Per-token shaped names: variable[token_id]
    if "[" in var and var.endswith("]"):
        base, _, token_id = var.partition("[")
        token_id = token_id[:-1]
        token = state["tokens"].get(token_id)
        if token is None:
            raise KeyError(f"no state for token {token_id} in '{var}'")
        if base == "net_emission_per_period":
            return token["E"] - token["B"]
        if base == "rho":
            E = token["E"]
            return token["B"] / E if E > 0 else 0.0
        if base == "tau_bar":
            return state["tau_bar"].get(token_id, 0.0)
        if base == "M":
            return token["M"]
        raise KeyError(f"unknown per-token variable base: {base!r}")
    # Flat names
    if var == "phi_times_K":
        K_max = max(state["K"].values()) if state["K"] else 0.0
        return state["phi"] * K_max
    if var == "gamma_times_S":
        return state["gamma"] * state["S"]
    if var == "Gamma":
        return state["Gamma_central"]
    if var in ("effective_gini", "token_balance_gini"):
        return state["effective_gini"]
    if var in state:
        v = state[var]
        if isinstance(v, (int, float)):
            return float(v)
    raise KeyError(f"unknown state variable: {var!r}")
