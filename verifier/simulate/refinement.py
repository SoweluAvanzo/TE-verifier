"""Refined-diagnosis orchestration.

For each verdict that is FAIL / INCONCLUSIVE / PASS_AS_INTENDED, we
compose a small ``RefinedDiagnosis`` block combining:

- A trajectory simulation (for per-token FMs: FM1, FM3) showing what
  M(t), E(t), B(t) look like under typical values. The samples list
  feeds the inline sparkline; the metrics drive the headline note.

- A sensitivity ranking (for any FAIL): which declared input would
  flip the verdict if you moved it to its extreme.

- A one-paragraph synthesised note that puts both into plain English,
  e.g. *"Static FM3 says ρ=0. Trajectory shows M growing 4% over 260
  periods; rho averages 1.18; the binding input is K (lowering K_lo
  flips this to PASS)"*.

The block lives on Verdict.refined_diagnosis and is rendered by both
the CLI and the webapp's verdict.js.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from schema import TokenEconomy
from verifier.simulate.sensitivity import (
    InputElasticity,
    PairElasticity,
    compute_pairwise_sensitivity,
    compute_sensitivity,
)
from verifier.simulate.trajectory import (
    Trajectory,
    simulate_token_trajectory,
)


# Imported lazily inside refine_verdicts to keep this module decoupled
# from `verifier.failure_modes.base.Verdict` (which stores the result
# as a serialised dict, see Verdict.refined_diagnosis).


# Per-token FMs that can produce a meaningful trajectory.
_PER_TOKEN_FMS: set[str] = {"FM1", "FM3"}

# All FMs that get a sensitivity ranking.
_SENSITIVITY_FMS: set[str] = {"FM1", "FM3", "FM4", "FM5", "FM6"}


class RefinedDiagnosis(BaseModel):
    """Compact synthesis of dynamic + sensitivity findings for a verdict.

    Attached to FAIL / INCONCLUSIVE / PASS_AS_INTENDED verdicts only —
    PASS verdicts already say what the user needs to know.
    """

    model_config = ConfigDict(extra="forbid")

    headline: str
    trajectory: Trajectory | None = None
    binding_inputs: list[InputElasticity] = Field(default_factory=list)
    # Joint flips found by the pairwise sweep — only includes pairs
    # where neither input flips alone. Empty when the verdict's
    # one-at-a-time picture is already complete.
    joint_flips: list[PairElasticity] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Headline composition
# ---------------------------------------------------------------------------


def _trajectory_headline(traj: Trajectory) -> str:
    """One-line summary of the trajectory."""
    m = traj.metrics
    parts = []
    # When M_initial is 0 (no initial_distribution declared), the
    # percentage form is meaningless; report the absolute terminal
    # value instead.
    if m.M_initial == 0 and m.M_terminal > 0:
        parts.append(
            f"M reaches ≈{m.M_terminal:g} tokens over {m.horizon_periods} "
            f"periods (no initial supply declared)"
        )
    elif m.diverges:
        parts.append(
            f"M diverges from {m.M_initial:g} to {m.M_terminal:g} "
            f"over {m.horizon_periods} periods"
        )
    elif m.M_growth_pct > 1.0:
        parts.append(
            f"M grows {m.M_growth_pct:.1f}% over {m.horizon_periods} periods"
        )
    elif m.M_growth_pct < -1.0:
        parts.append(
            f"M contracts {abs(m.M_growth_pct):.1f}% over "
            f"{m.horizon_periods} periods"
        )
    else:
        parts.append(f"M stays roughly flat over {m.horizon_periods} periods")
    if m.rho_avg is not None:
        parts.append(f"average ρ ≈ {m.rho_avg:.2f}")
    if m.saturates_at is not None:
        parts.append(f"saturates around period {m.saturates_at}")
    if m.rho_below_one_at_period is not None and m.rho_below_one_at_period < m.horizon_periods:
        parts.append(
            f"ρ falls below 1 at period {m.rho_below_one_at_period}"
        )
    return "; ".join(parts) + "."


def _sensitivity_headline(inputs: list[InputElasticity]) -> str:
    """One-line summary of which inputs would flip the verdict."""
    flippers = [i for i in inputs if i.flips_verdict]
    if not flippers:
        return "No single input flips the verdict — failure is robust to one-at-a-time changes."
    if len(flippers) == 1:
        f = flippers[0]
        return f"Binding input: {f.field} (flips verdict at extreme)."
    fields = ", ".join(f.field for f in flippers[:3])
    return f"Binding inputs: {fields}{' …' if len(flippers) > 3 else ''}."


def _pairwise_headline(pairs: list[PairElasticity]) -> str | None:
    """One-line summary of joint-flip pairs. None when nothing to report."""
    if not pairs:
        return None
    p = pairs[0]
    base = (
        f"Joint fix: moving {p.field_a} ({p.corner.split(',')[0]}) "
        f"and {p.field_b} ({p.corner.split(',')[1]}) together flips "
        f"the verdict to {p.verdict} — neither input does so alone"
    )
    if len(pairs) > 1:
        return base + f" (+ {len(pairs) - 1} more pair-corners)."
    return base + "."


def _synthesise_headline(
    status_value: str,
    traj: Trajectory | None,
    inputs: list[InputElasticity],
    pairs: list[PairElasticity],
) -> str:
    """Combine trajectory + sensitivity into a short paragraph."""
    parts = []
    if status_value == "pass_as_intended":
        parts.append("Static check would FAIL but role / NFR marks this as design-intended.")
    elif status_value == "inconclusive":
        parts.append("Static check is inconclusive; the dynamic view below is informative.")
    if traj is not None:
        parts.append(_trajectory_headline(traj))
    if inputs:
        parts.append(_sensitivity_headline(inputs))
    pair_line = _pairwise_headline(pairs)
    if pair_line:
        parts.append(pair_line)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def refine_verdicts(te: TokenEconomy, verdicts: list) -> None:
    """Mutate verdicts in place to attach RefinedDiagnosis dicts.

    Skips PASS and NOT_APPLICABLE — those don't need a refinement.
    The Verdict's ``refined_diagnosis`` field is set to a dict
    (RefinedDiagnosis.model_dump) rather than a typed object — see
    `verifier.failure_modes.base.Verdict.refined_diagnosis` for why.
    """
    # Per-token trajectories cached by token id (avoid re-simulating
    # the same token for FM1 + FM3 verdicts).
    trajectory_cache: dict[str, Trajectory] = {}
    token_by_id = {t.id: t for t in te.tokens}

    for v in verdicts:
        status_value = (
            v.status.value if hasattr(v.status, "value") else str(v.status)
        )
        if status_value in ("pass", "not_applicable"):
            continue
        fm_id = v.failure_mode.split(":")[0].strip()

        traj: Trajectory | None = None
        if fm_id in _PER_TOKEN_FMS and v.subject in token_by_id:
            if v.subject in trajectory_cache:
                traj = trajectory_cache[v.subject]
            else:
                try:
                    traj = simulate_token_trajectory(te, token_by_id[v.subject])
                    trajectory_cache[v.subject] = traj
                except Exception:
                    traj = None

        inputs: list[InputElasticity] = []
        pairs: list[PairElasticity] = []
        if fm_id in _SENSITIVITY_FMS and status_value == "fail":
            try:
                inputs = compute_sensitivity(te, fm_id, subject=v.subject)
            except Exception:
                inputs = []
            try:
                pairs = compute_pairwise_sensitivity(
                    te, fm_id, subject=v.subject, single_results=inputs
                )
            except Exception:
                pairs = []

        if (
            traj is None
            and not inputs
            and not pairs
            and status_value != "pass_as_intended"
        ):
            continue

        diag = RefinedDiagnosis(
            headline=_synthesise_headline(status_value, traj, inputs, pairs),
            trajectory=traj,
            binding_inputs=inputs,
            joint_flips=pairs,
        )
        v.refined_diagnosis = diag.model_dump(mode="json")
