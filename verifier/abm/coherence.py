"""FM-coherence panel — verifier verdicts vs ABM-realized trajectories.

For every safety predicate the verifier emits, walk the realised
trajectory and compute the *ABM-observed* value of the predicate's
variable. Compare against the declared threshold. Surface four cases:

* ``aligned``      — verifier says SOUND ⋀ ABM trajectory satisfies safety
* ``confirmed``    — verifier says BROKEN/FAIL ⋀ ABM trajectory violates
* ``abm_drift``    — verifier says SOUND but ABM crosses the threshold
                     (parameter-box edge case the verifier missed, OR an
                     emergent dynamic the static check can't capture)
* ``verifier_pessimistic``
                   — verifier says BROKEN/FAIL but ABM never violates
                     (tight parameter box; verifier conservative)
* ``inconclusive`` — N/A, INCONCLUSIVE, or no recorded data

The output rows are the audit trail the user reads on the /explore
page to gauge whether the trajectory backs the static verdict up.
"""

from __future__ import annotations

import statistics
from typing import Any


def _violates(value: float, op: str, threshold: float) -> bool:
    """Return True when ``value`` *violates* the safety condition
    (i.e. the safety predicate would evaluate to False)."""
    if op == ">=":
        return value < threshold
    if op == "<=":
        return value > threshold
    if op == ">":
        return value <= threshold
    if op == "<":
        return value >= threshold
    if op == "==":
        return value != threshold
    return False


def _resolve_one(snap: Any, variable: str) -> float | None:
    """Resolve a predicate variable name against one PeriodSnapshot.

    Handles scalar fields (``effective_gini``, ``phi``, ``N``,
    ``average_degree``) and token-subscripted names with
    ``name[token_id]`` syntax (``tau_bar[ROCCA]``, ``rho[BUONO]``,
    ``net_emission_per_period[ROCCA]``).
    """
    if not variable:
        return None
    # Subscripted: name[token_id]
    if "[" in variable and variable.endswith("]"):
        name, _, rest = variable.partition("[")
        token = rest[:-1].strip()
        E = (snap.E_by_token or {}).get(token)
        B = (snap.B_by_token or {}).get(token)
        if name == "tau_bar":
            v = (snap.tau_bar_by_token or {}).get(token)
            return float(v) if v is not None else None
        if name == "net_emission_per_period":
            if E is None and B is None:
                return None
            return float((E or 0.0) - (B or 0.0))
        if name == "rho":
            # ρ = B / E. When E ≈ 0, ρ is undefined; treat as 0 for the
            # safety check (no burn coverage). This matches the
            # verifier's PASS_AS_INTENDED reasoning for non-burning
            # tokens.
            if E is None or E <= 1e-12:
                return 0.0
            if B is None:
                return 0.0
            return float(B / E)
        if name == "M":
            v = (snap.M_by_token or {}).get(token)
            return float(v) if v is not None else None
        if name == "E":
            return float(E) if E is not None else None
        if name == "B":
            return float(B) if B is not None else None
        return None
    # Scalar attribute.
    direct = getattr(snap, variable, None)
    if isinstance(direct, (int, float)):
        return float(direct)
    return None


def _series(report: Any, variable: str) -> list[float]:
    out: list[float] = []
    for snap in report.snapshots:
        v = _resolve_one(snap, variable)
        if v is None:
            continue
        out.append(float(v))
    return out


def compute_fm_coherence(
    te: Any, report: Any, verifier_config: Any = None
) -> list[dict[str, Any]]:
    """Build per-FM coherence rows. Uses the verifier's minimal_verdicts
    output (same path the engine uses to triage simulable FMs) so the
    coherence panel speaks the same vocabulary as the rest of the
    pipeline.
    """
    try:
        from verifier.minimal import minimal_verdicts, StructuralStatus
    except ImportError:
        return []
    verdicts = minimal_verdicts(te, config=verifier_config)
    out: list[dict[str, Any]] = []
    for v in verdicts:
        row: dict[str, Any] = {
            "failure_mode": v.failure_mode,
            "subject": v.subject,
            "structural_status": v.structural_status.value,
            "predicates": [],
            "coherence": "inconclusive",
            "notes": "",
        }
        status = v.structural_status
        if status in (StructuralStatus.NOT_APPLICABLE,
                      StructuralStatus.INCONCLUSIVE):
            row["coherence"] = "inconclusive"
            row["notes"] = (
                "Verifier marked this FM not-applicable or inconclusive; "
                "no coherence check possible."
            )
            out.append(row)
            continue
        pred_rows: list[dict[str, Any]] = []
        any_violate = False
        any_data = False
        for p in v.safety_predicates:
            series = _series(report, p.variable)
            if not series:
                pred_rows.append({
                    "variable": p.variable,
                    "operator": p.operator,
                    "threshold": float(p.threshold),
                    "observed_min": None,
                    "observed_median": None,
                    "observed_max": None,
                    "violation_periods": 0,
                    "note": (
                        f"ABM never reported a value for '{p.variable}'."
                    ),
                })
                continue
            any_data = True
            v_min = min(series)
            v_med = statistics.median(series)
            v_max = max(series)
            viol_periods = sum(
                1 for x in series
                if _violates(x, p.operator, float(p.threshold))
            )
            if viol_periods > 0:
                any_violate = True
            pred_rows.append({
                "variable": p.variable,
                "operator": p.operator,
                "threshold": float(p.threshold),
                "observed_min": v_min,
                "observed_median": v_med,
                "observed_max": v_max,
                "violation_periods": viol_periods,
                "note": (
                    f"{viol_periods}/{len(series)} periods crossed "
                    f"the {p.operator}{p.threshold:g} boundary."
                ),
            })
        row["predicates"] = pred_rows
        # Alternative-predicate semantics for SOUND verdicts: when an
        # FM emits multiple safety predicates as alternatives (e.g. FM5
        # well-mixed N OR network-corrected avg_degree), the verifier's
        # verdict reflects EITHER condition securing safety. The
        # coherence panel should consider the FM aligned when ≥ 1
        # predicate has 0 ABM violations — the alternative that secured
        # the verifier's SOUND verdict is also satisfied empirically.
        any_pred_clean = any(
            (p.get("observed_min") is not None) and (p.get("violation_periods", 0) == 0)
            for p in pred_rows
        )
        if not any_data:
            row["coherence"] = "inconclusive"
            row["notes"] = (
                "Verifier emitted predicates but the ABM didn't surface "
                "matching state variables — wire missing inputs to compare."
            )
        elif status == StructuralStatus.SOUND and not any_violate:
            row["coherence"] = "aligned"
            row["notes"] = (
                "Verifier proved safety across the parameter box; ABM "
                "trajectory never crossed the threshold. Consistent."
            )
        elif status == StructuralStatus.SOUND and any_pred_clean:
            row["coherence"] = "aligned"
            row["notes"] = (
                "Verifier proved safety via ≥ 1 alternative predicate "
                "(other predicates in this FM are emitted as alternatives, "
                "not as conjunctions). The ABM trajectory satisfies the "
                "alternative the verifier used. Consistent."
            )
        elif status == StructuralStatus.SOUND and any_violate:
            row["coherence"] = "abm_drift"
            row["notes"] = (
                "Verifier said SOUND but every emitted safety predicate "
                "is crossed in the ABM trajectory. Either the static "
                "analysis missed a corner of the parameter box, or the "
                "ABM exposed an emergent dynamic the static check can't "
                "capture (e.g. realized velocity vs declared holding "
                "time). Investigate the witness."
            )
        elif status == StructuralStatus.BROKEN and any_violate:
            row["coherence"] = "confirmed"
            row["notes"] = (
                "Verifier proved violation reachable; ABM trajectory "
                "confirms it materialises with the declared parameters."
            )
        elif status == StructuralStatus.BROKEN and not any_violate:
            row["coherence"] = "verifier_pessimistic"
            row["notes"] = (
                "Verifier said BROKEN, but the ABM trajectory never "
                "crossed the threshold in this run. The parameter box "
                "likely contains harmless points; rerun with multiple "
                "seeds to confirm rarity."
            )
        elif status == StructuralStatus.FRAGILE:
            if any_violate:
                row["coherence"] = "fragile_realised"
                row["notes"] = (
                    "Verifier said FRAGILE (violation reachable in some "
                    "subset of the box); ABM trajectory landed in that "
                    "subset."
                )
            else:
                row["coherence"] = "fragile_avoided"
                row["notes"] = (
                    "Verifier said FRAGILE; ABM trajectory stayed in the "
                    "safe subset of the parameter box. Rerun more seeds "
                    "to estimate probability."
                )
        out.append(row)
    return out
