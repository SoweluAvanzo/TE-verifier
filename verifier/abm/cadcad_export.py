"""cadCAD-compatible export — produces a config dict that a real
cadCAD pipeline can consume.

This module **does not import cadCAD** (it would be a heavy optional
dependency). Instead, it produces the four artifacts a cadCAD config
needs, in the same shape:

  • ``initial_state``        — the genesis state dict.
  • ``state_update_blocks``  — list of PSUB dicts.
  • ``sim_config``           — { N (replicates), T (timesteps), … }.
  • ``params``               — sweepable parameter dict.

The user then drops these into their own cadCAD ``Experiment`` /
``Executor`` setup. We provide the data; cadCAD's runtime is left to
the user's environment.

Why a passthrough export instead of a wrapped engine? Two reasons:

1. cadCAD installation is heavyweight and version-volatile. A native-
   Python reference engine (``verifier.abm.engine``) covers the
   common case without forcing the dependency.
2. Users who want cadCAD almost always want to embed it into their
   own pipeline (parameter sweeps, sensitivity panels, dashboarding).
   Emitting the config dict gives them maximum flexibility.

The shape produced here is documented in
``docs/abm-bridge.md`` § "Mapping to cadCAD".
"""

from __future__ import annotations

from typing import Any

from schema import TokenEconomy
from verifier.abm.report import SimulationConfig
from verifier.config import VerifierConfig
from verifier.minimal import ReachabilityVerdict, StructuralStatus, minimal_verdicts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_cadcad_config(
    te: TokenEconomy,
    verdicts: list[ReachabilityVerdict] | None = None,
    sim_config: SimulationConfig | None = None,
    verifier_config: VerifierConfig | None = None,
) -> dict[str, Any]:
    """Build a cadCAD-shaped config dict from a TE-IR + verifier output.

    The returned dict has four top-level keys:

    * ``initial_state`` (dict): the genesis state. Keys mirror
      ``verifier.abm.state.initial_state``; values are sampled
      midpoints from the IR.
    * ``state_update_blocks`` (list[dict]): one PSUB per
      (failure-mode, subject) pair that should be simulated. Each
      PSUB has a ``label``, a ``policies`` dict (one per safety
      predicate, returning the predicate's evaluation), and a
      ``variables`` dict that writes a violation counter into state.
    * ``sim_config`` (dict): ``N`` (replicate count), ``T`` (horizon),
      and a ``seeds`` list.
    * ``params`` (dict): parameter values the cadCAD experiment can
      sweep. Each key maps to a list of values cadCAD will iterate.

    cadCAD consumers translate this into their actual ``Experiment``
    / ``Executor`` configuration; the field names match cadCAD's
    expectations so the translation is mechanical.
    """
    sim_cfg = sim_config or SimulationConfig()
    if verdicts is None:
        verdicts = list(minimal_verdicts(te, config=verifier_config))

    # 1. Initial state — same shape the native engine uses, with
    # midpoint values for now. The cadCAD pipeline can override.
    init_state = _build_initial_state_midpoint(te, verifier_config)

    # 2. PSUBs — one per simulable (FM, subject).
    psubs = []
    simulable = [
        v
        for v in verdicts
        if v.structural_status
        in (StructuralStatus.FRAGILE, StructuralStatus.INCONCLUSIVE)
        and v.safety_predicates
    ]
    for v in simulable:
        psubs.append(_psub_for_verdict(v))

    # 3. Sim config — cadCAD field names.
    sim_dict = {
        "N": sim_cfg.n_runs,
        "T": sim_cfg.horizon_periods,
        "M": 1,  # M=1 means one variant of params; sweeps inflate it.
    }

    # 4. Params — the sweepable parameter space. We surface the
    # NumberRange-typed inputs so a cadCAD user can configure sweeps.
    params = _sweepable_params(te)

    # Metadata block — helps the user verify the config matches their
    # IR (and serves as the audit trail). Not consumed by cadCAD.
    metadata = {
        "te_name": te.meta.name,
        "verifier_verdicts": [v.model_dump(mode="json") for v in verdicts],
        "skipped_fms": [
            {
                "failure_mode": v.failure_mode,
                "subject": v.subject,
                "status": v.structural_status.value,
                "reason": _skip_reason(v),
            }
            for v in verdicts
            if v.structural_status
            not in (StructuralStatus.FRAGILE, StructuralStatus.INCONCLUSIVE)
        ],
        "max_agents_per_run": 200,
    }

    return {
        "initial_state": init_state,
        "state_update_blocks": psubs,
        "sim_config": sim_dict,
        "params": params,
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# Initial state (midpoint values)
# ---------------------------------------------------------------------------


def _build_initial_state_midpoint(
    te: TokenEconomy,
    config: VerifierConfig | None,
) -> dict[str, Any]:
    """Sample-free midpoint state. cadCAD users can override values
    via the params sweep; this gives them a sane starting point."""
    state = {
        "t": 0,
        "tokens": {
            t.id: {
                "M": _midpoint(t.initial_distribution.amount)
                if t.initial_distribution.amount is not None
                else 0.0,
                "E": 0.0,
                "B": 0.0,
            }
            for t in te.tokens
        },
        "Q": _midpoint(
            getattr(te.participants, "expected_Q", None)
            or getattr(te.participants, "expected_Q_override", None)
        ),
        "N": _midpoint(te.participants.count_N),
        "d": _midpoint(te.participants.average_demand_d),
        "K": {
            t.id: _midpoint(t.offer_variety_K) if t.offer_variety_K is not None else 0.0
            for t in te.tokens
        },
        "gamma": _midpoint(te.governance.monitoring_capacity_gamma),
        "S": _midpoint(te.governance.sanction_structure.S_normalized),
        "phi": 0.0,
        "Gamma_central": _gamma(te),
        "effective_gini": (
            _midpoint(te.governance.token_balance_gini)
            if te.governance.token_balance_gini is not None
            else 0.0
        ),
        "tau_bar": {t.id: 0.0 for t in te.tokens},
        "average_degree": _midpoint(
            te.participants.topology_params.get("average_degree")
        ),
        "agents": [],  # populated lazily by the cadCAD runtime
    }
    return state


def _midpoint(rng) -> float:
    if rng is None:
        return 0.0
    return (rng.min + rng.max) / 2.0


def _gamma(te: TokenEconomy) -> float:
    from verifier.failure_modes.fm6_governance import UNILATERAL_ACTORS

    rules = te.governance.rule_structure
    if not rules:
        return 0.0
    unilateral = sum(1 for a in rules.values() if a in UNILATERAL_ACTORS)
    return unilateral / len(rules)


# ---------------------------------------------------------------------------
# PSUB per simulable verdict
# ---------------------------------------------------------------------------


def _psub_for_verdict(v: ReachabilityVerdict) -> dict[str, Any]:
    """One Partial State Update Block per (FM, subject).

    Structure:
      label    — human-readable
      policies — dict of policy_name → predicate-eval description
      variables — dict of state-key → "update function" description
                  (cadCAD users write the actual Python function;
                  we just declare which state key gets written)
    """
    policies = {}
    for p in v.safety_predicates:
        policies[f"safety_{p.variable}"] = {
            "predicate": {
                "variable": p.variable,
                "operator": p.operator,
                "threshold": p.threshold,
            },
            "description": (
                f"Returns True iff the safety condition "
                f"{p.variable} {p.operator} {p.threshold} holds."
            ),
            "formula": p.formula,
            "inputs": p.inputs,
        }
    return {
        "label": f"{v.failure_mode}[{v.subject}]",
        "policies": policies,
        "variables": {
            f"violations_{v.failure_mode}_{v.subject}": {
                "description": (
                    f"Per-period count of safety-condition failures "
                    f"for {v.failure_mode}[{v.subject}]. Aggregate "
                    f"over the trajectory to get total violation "
                    f"periods; check `> 0` to ask 'did this run ever "
                    f"violate?'."
                ),
            }
        },
    }


def _skip_reason(v: ReachabilityVerdict) -> str:
    status = v.structural_status
    if status == StructuralStatus.SOUND:
        return (
            "Verifier proved unreachability of violation — no need "
            "to simulate."
        )
    if status == StructuralStatus.BROKEN:
        return (
            "Verifier proved no parameter assignment in the box "
            "satisfies the FM. Redesign required before simulation."
        )
    if status == StructuralStatus.NOT_APPLICABLE:
        return "FM is not applicable to this subject."
    return "Skipped per triage."


# ---------------------------------------------------------------------------
# Sweepable parameter dict
# ---------------------------------------------------------------------------


def _sweepable_params(te: TokenEconomy) -> dict[str, list[float]]:
    """Emit a dict of parameter values cadCAD can sweep across.

    Each key maps to a list — cadCAD interprets a length-N list as
    "sweep across these N values." We emit (min, midpoint, max) per
    NumberRange-typed input by default; the user can lengthen or
    replace these lists in their cadCAD config.
    """
    params: dict[str, list[float]] = {}

    def _add(name: str, rng) -> None:
        if rng is None:
            return
        mid = (rng.min + rng.max) / 2.0
        # de-dup if range is a point
        vals = [rng.min, mid, rng.max] if rng.min != rng.max else [rng.min]
        params[name] = vals

    _add("count_N", te.participants.count_N)
    _add(
        "expected_Q",
        getattr(te.participants, "expected_Q", None)
        or getattr(te.participants, "expected_Q_override", None),
    )
    _add("average_demand_d", te.participants.average_demand_d)
    _add(
        "monitoring_capacity_gamma",
        te.governance.monitoring_capacity_gamma,
    )
    _add(
        "S_normalized",
        te.governance.sanction_structure.S_normalized,
    )
    _add("token_balance_gini", te.governance.token_balance_gini)
    for token in te.tokens:
        if token.offer_variety_K is not None:
            _add(f"offer_variety_K[{token.id}]", token.offer_variety_K)
    return params
