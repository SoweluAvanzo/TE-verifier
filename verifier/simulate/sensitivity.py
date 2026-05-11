"""Sensitivity ranking — which declared input flips the FAIL verdict?

The static verifier returns a list of "swept fields" without ranking.
For an FM that is FAIL, the user wants to know: "which declared input,
if I changed it, would flip me to PASS?". This module answers that by
running one-at-a-time perturbations.

Algorithm (per FM verdict):

1. Identify the candidate inputs the FM consumes (per FM-id table
   below — kept small so the loop is bounded and fast).
2. For each candidate that is range-typed, build two altered TEs:
   one with the field collapsed to its minimum, one with the maximum
   value held while everything else stays at its declared range.
3. Re-run the same FM on each altered TE.
4. Record which alterations would flip the verdict from FAIL to PASS
   (or from PASS to FAIL — useful for showing how robust a PASS is).
5. Rank by "verdict change" first, then by which extreme produces
   the change.

This is an O(2 × |candidates|) re-verification, typically 6-12 calls
per FAIL — under a second on the case studies. Cheaper than a full
Monte Carlo, dramatically more interpretable than nothing.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from schema import NumberRange, TokenEconomy
from verifier.config import VerifierConfig
from verifier.failure_modes import (
    FM1Oversupply,
    FM3BurnEmission,
    FM4FreeRider,
    FM5CriticalMass,
    FM6GovernanceCapture,
)
from verifier.failure_modes.base import FailureMode, Status, Verdict


# Map FM id → (FM class, list of candidate IR-path getters/setters).
# Each candidate is a (label, getter, setter) tuple. Label is what the
# user sees in the binding-input ranking.

CandidateGetter = "callable[[TokenEconomy], NumberRange | None]"
CandidateSetter = "callable[[TokenEconomy, NumberRange], TokenEconomy]"


def _set_participants_field(field: str):
    def setter(te: TokenEconomy, rng: NumberRange) -> TokenEconomy:
        return te.model_copy(
            update={
                "participants": te.participants.model_copy(update={field: rng})
            }
        )

    def getter(te: TokenEconomy) -> NumberRange | None:
        return getattr(te.participants, field, None)

    return getter, setter


def _set_token_K(token_idx: int):
    def setter(te: TokenEconomy, rng: NumberRange) -> TokenEconomy:
        new_tokens = list(te.tokens)
        new_tokens[token_idx] = new_tokens[token_idx].model_copy(
            update={"offer_variety_K": rng}
        )
        return te.model_copy(update={"tokens": tuple(new_tokens) if isinstance(te.tokens, tuple) else new_tokens})

    def getter(te: TokenEconomy) -> NumberRange | None:
        return te.tokens[token_idx].offer_variety_K if token_idx < len(te.tokens) else None

    return getter, setter


def _set_governance_gamma():
    def setter(te: TokenEconomy, rng: NumberRange) -> TokenEconomy:
        return te.model_copy(
            update={
                "governance": te.governance.model_copy(
                    update={"monitoring_capacity_gamma": rng}
                )
            }
        )

    def getter(te: TokenEconomy) -> NumberRange | None:
        return te.governance.monitoring_capacity_gamma

    return getter, setter


def _set_governance_S():
    def setter(te: TokenEconomy, rng: NumberRange) -> TokenEconomy:
        return te.model_copy(
            update={
                "governance": te.governance.model_copy(
                    update={
                        "sanction_structure": te.governance.sanction_structure.model_copy(
                            update={"S_normalized": rng}
                        )
                    }
                )
            }
        )

    def getter(te: TokenEconomy) -> NumberRange | None:
        return te.governance.sanction_structure.S_normalized

    return getter, setter


def _set_governance_gini():
    def setter(te: TokenEconomy, rng: NumberRange) -> TokenEconomy:
        return te.model_copy(
            update={
                "governance": te.governance.model_copy(
                    update={"token_balance_gini": rng}
                )
            }
        )

    def getter(te: TokenEconomy) -> NumberRange | None:
        return te.governance.token_balance_gini

    return getter, setter


def _candidates_for(fm_id: str, te: TokenEconomy) -> list[tuple[str, "CandidateGetter", "CandidateSetter"]]:
    """List of (label, getter, setter) per FM. Tokens iterated for K."""
    candidates: list[tuple[str, "CandidateGetter", "CandidateSetter"]] = []
    if fm_id == "FM1":
        get, sett = _set_participants_field("expected_Q")
        candidates.append(("participants.expected_Q", get, sett))
    elif fm_id == "FM3":
        get, sett = _set_participants_field("expected_Q")
        candidates.append(("participants.expected_Q", get, sett))
    elif fm_id == "FM4":
        get, sett = _set_participants_field("average_demand_d")
        candidates.append(("participants.average_demand_d", get, sett))
        get, sett = _set_governance_gamma()
        candidates.append(("governance.monitoring_capacity_gamma", get, sett))
        get, sett = _set_governance_S()
        candidates.append(("governance.sanction_structure.S_normalized", get, sett))
        for i, tok in enumerate(te.tokens):
            if tok.offer_variety_K is None:
                continue
            get, sett = _set_token_K(i)
            candidates.append((f"tokens[{tok.id}].offer_variety_K", get, sett))
    elif fm_id == "FM5":
        get, sett = _set_participants_field("count_N")
        candidates.append(("participants.count_N", get, sett))
        get, sett = _set_participants_field("average_demand_d")
        candidates.append(("participants.average_demand_d", get, sett))
        for i, tok in enumerate(te.tokens):
            if tok.offer_variety_K is None:
                continue
            get, sett = _set_token_K(i)
            candidates.append((f"tokens[{tok.id}].offer_variety_K", get, sett))
    elif fm_id == "FM6":
        get, sett = _set_governance_gini()
        candidates.append(("governance.token_balance_gini", get, sett))
    return candidates


_FM_CLASSES: dict[str, type[FailureMode]] = {
    "FM1": FM1Oversupply,
    "FM3": FM3BurnEmission,
    "FM4": FM4FreeRider,
    "FM5": FM5CriticalMass,
    "FM6": FM6GovernanceCapture,
}


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class InputElasticity(BaseModel):
    """How a single declared input affects the verdict."""

    model_config = ConfigDict(extra="forbid")

    field: str
    current_min: float
    current_max: float
    verdict_at_min: str
    verdict_at_max: str
    flips_verdict: bool


class PairElasticity(BaseModel):
    """How a *pair* of inputs jointly affects the verdict.

    Reported only when a pair flips the verdict at a corner that
    neither input flips by itself. Catches the classic one-at-a-time
    blindspot where two clauses in the same FM (e.g. φ ≥ d/K AND γS > T-R
    in FM4) require simultaneous fixes.
    """

    model_config = ConfigDict(extra="forbid")

    field_a: str
    field_b: str
    corner: str  # one of: "min,min", "min,max", "max,min", "max,max"
    verdict: str  # status string at this corner
    baseline: str  # status string with no overrides


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _verdict_status_for(
    te: TokenEconomy, fm_id: str, subject: str | None
) -> str:
    fm_cls = _FM_CLASSES.get(fm_id)
    if fm_cls is None:
        return "unknown"
    fm = fm_cls()
    try:
        verdicts = fm.check(te, config=VerifierConfig.paper_defaults())
    except TypeError:
        verdicts = fm.check(te)
    # Pick the verdict matching subject, or first verdict
    if subject is not None:
        for v in verdicts:
            if v.subject == subject:
                return v.status.value
    if verdicts:
        return verdicts[0].status.value
    return "unknown"


def compute_sensitivity(
    te: TokenEconomy, fm_id: str, *, subject: str | None = None
) -> list[InputElasticity]:
    """Rank inputs by their ability to flip the FM's verdict.

    Each candidate input is collapsed to its min then max while the
    rest of the IR is held fixed; the FM is re-run and the resulting
    status recorded. Returns the candidates ordered with verdict-
    flipping inputs first.
    """
    candidates = _candidates_for(fm_id, te)
    out: list[InputElasticity] = []
    baseline = _verdict_status_for(te, fm_id, subject)
    for label, getter, setter in candidates:
        current = getter(te)
        if current is None:
            continue
        min_rng = NumberRange.point(current.min)
        max_rng = NumberRange.point(current.max)
        try:
            te_min = setter(te, min_rng)
            te_max = setter(te, max_rng)
        except Exception:
            continue
        v_min = _verdict_status_for(te_min, fm_id, subject)
        v_max = _verdict_status_for(te_max, fm_id, subject)
        flips = (v_min != baseline) or (v_max != baseline)
        out.append(
            InputElasticity(
                field=label,
                current_min=current.min,
                current_max=current.max,
                verdict_at_min=v_min,
                verdict_at_max=v_max,
                flips_verdict=flips,
            )
        )
    out.sort(key=lambda e: (not e.flips_verdict, e.field))
    return out


def compute_pairwise_sensitivity(
    te: TokenEconomy,
    fm_id: str,
    *,
    subject: str | None = None,
    single_results: list[InputElasticity] | None = None,
) -> list[PairElasticity]:
    """Find pairs of inputs that *jointly* flip the verdict at a corner.

    Skips pairs where either input is already a single-input flipper —
    those are covered by ``compute_sensitivity`` and would just add
    noise. Iterates the four corners (min,min)/(min,max)/(max,min)/
    (max,max) for each remaining pair and records the corner if its
    verdict differs from baseline.

    Cost: ``O(C(n,2) × 4)`` re-verifications where ``n`` is the number
    of FM-specific candidates that did *not* single-flip. For the
    case-study FMs this is at most ~24 calls.
    """
    candidates = _candidates_for(fm_id, te)
    if len(candidates) < 2:
        return []

    baseline = _verdict_status_for(te, fm_id, subject)

    # Inputs already covered by single-input ranking — skip them.
    single_flipping_fields: set[str] = set()
    if single_results:
        single_flipping_fields = {e.field for e in single_results if e.flips_verdict}

    pairs_out: list[PairElasticity] = []
    corners = (("min", "min"), ("min", "max"), ("max", "min"), ("max", "max"))

    for i, (label_a, get_a, set_a) in enumerate(candidates):
        if label_a in single_flipping_fields:
            continue
        rng_a = get_a(te)
        if rng_a is None:
            continue
        for label_b, get_b, set_b in candidates[i + 1 :]:
            if label_b == label_a or label_b in single_flipping_fields:
                continue
            rng_b = get_b(te)
            if rng_b is None:
                continue
            for c_a, c_b in corners:
                a_val = rng_a.min if c_a == "min" else rng_a.max
                b_val = rng_b.min if c_b == "min" else rng_b.max
                try:
                    te_pair = set_a(te, NumberRange.point(a_val))
                    te_pair = set_b(te_pair, NumberRange.point(b_val))
                except Exception:
                    continue
                v = _verdict_status_for(te_pair, fm_id, subject)
                if v != baseline:
                    pairs_out.append(
                        PairElasticity(
                            field_a=label_a,
                            field_b=label_b,
                            corner=f"{c_a},{c_b}",
                            verdict=v,
                            baseline=baseline,
                        )
                    )
    return pairs_out
