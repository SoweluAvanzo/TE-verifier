"""Minimal verifier output — the Point-5 redesign.

This module exposes a *narrow* projection on top of the existing FM
checkers. Where the standard ``verifier.dispatcher.verify()`` returns
rich verdicts (status enums, narratives, NFR reframings, sensitivity
deltas, refined diagnoses), the minimal API returns only what the
verifier can *honestly* guarantee at the formal layer:

* **Reachability of violation** — does there exist a parameter
  assignment in the declared box where the failure mode is violated?
  Three-valued: True / False / Unknown.
* **Reachability of satisfaction** — does there exist a parameter
  assignment where the FM holds? Three-valued.
* **Minimum parameter shift** — when violation is reachable, the
  closed-form threshold (taken from the FM's existing
  ``NumericRecommendation.safe_threshold``) that would make the
  violation unreachable. A single number, not a paragraph.

The four (violation, satisfaction) reachability combinations map onto
``StructuralStatus``:

* ``SOUND``         — violation unreachable. The design provably
                       satisfies the FM across the declared box.
* ``FRAGILE``       — both reachable. The design works in some
                       parameter corners and breaks in others — the
                       commonest real-world case.
* ``BROKEN``        — violation reachable, satisfaction unreachable.
                       The design has no parameter assignment in the
                       box that satisfies the FM — it's structurally
                       broken, not just under-tuned.
* ``NOT_APPLICABLE`` — the FM doesn't apply (e.g. reputation marker
                       for FM2).
* ``INCONCLUSIVE``  — verification couldn't decide either question.

What this output deliberately omits, and why:

* No ``PASS_AS_INTENDED`` — NFR-driven reframings belong in the
  simulator / scoring layer, where intent matters.
* No free-text recommendations beyond the single threshold value.
* No role-gated alternates.
* No coherence narrative.

This is the contract the ABM layer is intended to consume: ABM adds
likelihood, time-resolved trajectory, and per-agent dynamics on top
of these reachability facts.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schema import TokenEconomy
from verifier.config import VerifierConfig
from verifier.safety_predicate import SafetyPredicate


class StructuralStatus(str, Enum):
    SOUND = "sound"
    FRAGILE = "fragile"
    BROKEN = "broken"
    NOT_APPLICABLE = "not_applicable"
    INCONCLUSIVE = "inconclusive"


_TriState = Literal["true", "false", "unknown"]


class ReachabilityVerdict(BaseModel):
    """Per-FM minimal output.

    Every field is either a fact about the declared parameter box or
    None — there is no narrative, no NFR reframing, no role gating.
    """

    model_config = ConfigDict(extra="forbid")

    failure_mode: str  # e.g. "FM1"
    subject: str  # token id or "system"

    violation_reachable: _TriState
    satisfaction_reachable: _TriState
    structural_status: StructuralStatus

    # The single threshold (typically taken from the FM's
    # NumericRecommendation.safe_threshold). None when the FM is
    # passing, not-applicable, or doesn't expose a threshold.
    minimum_param_shift: dict[str, float] | None = None

    # Parameter values witnessing a violation, when one was found.
    # Same data as in the standard Verdict's counterexample.
    witness: dict[str, float] | None = None

    # Structured safety predicates for ABM consumption. Each
    # predicate names a per-period state variable, an operator, and a
    # threshold — the simulator evaluates ``state[variable] op
    # threshold`` per step; aggregate over runs gives likelihood-of-
    # violation. See ``docs/abm-bridge.md`` for the cadCAD mapping.
    safety_predicates: list[SafetyPredicate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def _violation_reachable_from(status_value: str) -> _TriState:
    """Map the existing FM status to a three-valued reachability fact.

    PASS_AS_INTENDED is treated as "violation reachable" because the
    underlying Z3 search did find a violating assignment — the NFR
    reframing that turned FAIL into PASS_AS_INTENDED is exactly the
    kind of context-dependence we want to drop in the minimal output.
    """
    if status_value == "fail":
        return "true"
    if status_value == "pass":
        return "false"
    if status_value == "pass_as_intended":
        return "true"
    if status_value == "inconclusive":
        return "unknown"
    return "unknown"  # not_applicable


_FM_REGISTRY: dict[str, type] = {}


def _fm_class(fm_id: str):
    """Lazy-lookup of the FM class by id, cached on first call."""
    global _FM_REGISTRY
    if not _FM_REGISTRY:
        from verifier.failure_modes.fm1_oversupply import FM1Oversupply
        from verifier.failure_modes.fm2_velocity import FM2VelocityTrap
        from verifier.failure_modes.fm3_burn_emission import FM3BurnEmission
        from verifier.failure_modes.fm4_freerider import FM4FreeRider
        from verifier.failure_modes.fm5_critical_mass import FM5CriticalMass
        from verifier.failure_modes.fm6_governance import FM6GovernanceCapture

        _FM_REGISTRY = {
            "FM1": FM1Oversupply,
            "FM2": FM2VelocityTrap,
            "FM3": FM3BurnEmission,
            "FM4": FM4FreeRider,
            "FM5": FM5CriticalMass,
            "FM6": FM6GovernanceCapture,
        }
    return _FM_REGISTRY.get(fm_id)


def _satisfaction_reachable_from(
    te: TokenEconomy,
    config: VerifierConfig | None,
    fm_id: str,
    subject: str,
    baseline_status: str,
) -> _TriState:
    """Phase-C: formal dual-form Z3 check.

    For PASS / PASS_AS_INTENDED the answer is "true" by definition — a
    witness exists by virtue of the original check having confirmed the
    safety predicate holds for all (or some) assignments. For
    NOT_APPLICABLE / INCONCLUSIVE the answer is "unknown". For FAIL we
    delegate to the FM's ``is_satisfaction_reachable_when_failing``,
    which runs Z3 on the safety predicate directly.

    This replaces the Phase-B sensitivity-flip heuristic. Phase-B
    answered "could a single-knob change rescue this?"; Phase-C answers
    "does the design's declared box contain ANY safe corner?", which
    is what cleanly distinguishes FRAGILE from BROKEN.
    """
    if baseline_status in ("pass", "pass_as_intended"):
        return "true"
    if baseline_status == "not_applicable":
        return "unknown"
    if baseline_status == "inconclusive":
        return "unknown"

    fm_cls = _fm_class(fm_id)
    if fm_cls is None:
        return "unknown"
    try:
        result = fm_cls().is_satisfaction_reachable_when_failing(te, config, subject)
    except Exception:
        return "unknown"
    if result in ("true", "false", "unknown"):
        return result  # type: ignore[return-value]
    return "unknown"


def _classify(
    violation: _TriState, satisfaction: _TriState, baseline_status: str
) -> StructuralStatus:
    if baseline_status == "not_applicable":
        return StructuralStatus.NOT_APPLICABLE
    if violation == "unknown" or satisfaction == "unknown":
        return StructuralStatus.INCONCLUSIVE
    if violation == "false":
        return StructuralStatus.SOUND
    if satisfaction == "false":
        return StructuralStatus.BROKEN
    return StructuralStatus.FRAGILE  # both true


def _threshold_from(verdict) -> dict[str, float] | None:
    """Extract the safe_threshold from a Verdict's NumericRecommendation."""
    rec = getattr(verdict, "recommendation", None)
    if rec is None:
        return None
    if rec.safe_threshold is None:
        return None
    return {rec.parameter: rec.safe_threshold}


def _witness_from(verdict) -> dict[str, float] | None:
    ce = getattr(verdict, "counterexample", None)
    if ce is None or ce.parameter_values is None:
        return None
    return dict(ce.parameter_values)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def minimal_verdicts(
    te: TokenEconomy,
    config: VerifierConfig | None = None,
) -> list[ReachabilityVerdict]:
    """Run every FM in minimal-output mode.

    Returns one ``ReachabilityVerdict`` per FM verdict the standard
    dispatcher would have produced (one per token for per-token FMs,
    one per system for system-level FMs).

    Implementation note: this is a *projection* on top of the existing
    FM checkers. The Z3 work is unchanged; we run the FMs and reduce
    the rich Verdict objects to the minimal contract above. When the
    full Phase-C v2 verifier lands with dual-form FM encodings, this
    projection's ``satisfaction_reachable`` field becomes a real
    formal answer instead of a sensitivity-derived heuristic.
    """
    # Avoid importing the dispatcher at module load time — keeps the
    # import graph minimal.
    from verifier.dispatcher import verify

    report = verify(te, config=config)

    out: list[ReachabilityVerdict] = []
    for v in report.verdicts:
        fm_id = v.failure_mode.split(":")[0].strip()
        status_value = v.status.value if hasattr(v.status, "value") else str(v.status)

        violation = _violation_reachable_from(status_value)
        satisfaction = _satisfaction_reachable_from(
            te, config, fm_id, v.subject, status_value
        )
        structural = _classify(violation, satisfaction, status_value)

        # Pull structured safety predicates from the FM so ABM
        # consumers can wire them as per-period state checks.
        predicates: list[SafetyPredicate] = []
        fm_cls = _fm_class(fm_id)
        if fm_cls is not None and status_value != "not_applicable":
            try:
                predicates = fm_cls().safety_predicates(te, config, v.subject)
            except Exception:
                predicates = []

        out.append(
            ReachabilityVerdict(
                failure_mode=fm_id,
                subject=v.subject,
                violation_reachable=violation,
                satisfaction_reachable=satisfaction,
                structural_status=structural,
                minimum_param_shift=_threshold_from(v) if violation == "true" else None,
                witness=_witness_from(v) if violation == "true" else None,
                safety_predicates=predicates,
            )
        )
    return out


def minimal_report_text(verdicts: list[ReachabilityVerdict]) -> str:
    """Render a minimal report as a small text table.

    Intended for human inspection or as a stable handoff format for
    the ABM layer. No emoji, no markdown.
    """
    lines = []
    header = f"{'FM':<6}{'subject':<14}{'status':<14}{'V':<3}{'S':<3}{'threshold':<24}"
    lines.append(header)
    lines.append("-" * len(header))
    for v in verdicts:
        thresh = ""
        if v.minimum_param_shift:
            k, val = next(iter(v.minimum_param_shift.items()))
            thresh = f"{k}≤{val:g}" if val < 1.0 else f"{k}={val:g}"
        lines.append(
            f"{v.failure_mode:<6}"
            f"{v.subject:<14}"
            f"{v.structural_status.value:<14}"
            f"{v.violation_reachable[0].upper():<3}"
            f"{v.satisfaction_reachable[0].upper():<3}"
            f"{thresh:<24}"
        )
    return "\n".join(lines)
