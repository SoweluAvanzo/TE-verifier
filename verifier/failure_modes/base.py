"""Common types for failure-mode evaluators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Literal

import z3
from pydantic import BaseModel, ConfigDict, Field

from schema import TokenEconomy


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PASS_AS_INTENDED = "pass_as_intended"  # an NFR declared this is a goal
    INCONCLUSIVE = "inconclusive"
    NOT_APPLICABLE = "not_applicable"


class RiskLevel(str, Enum):
    """Numerical risk band complementary to Status (Simulator.pdf §4).

    Status answers "is there *any* parameter assignment that violates the
    condition?" (existential over the declared box). RiskLevel answers
    "at the midpoint of the declared box, how bad is the violation?"
    (point evaluation). The two surfaces are complementary:

    - PASS + GREEN          → solid design, no concern
    - PASS + AMBER          → safe but margin is tight at typical values
    - FAIL + GREEN          → a corner of the box fails; midpoint is fine
    - FAIL + RED_CRITICAL   → broadly broken at any typical configuration

    Used by the verdict UI to colour-code each card and by the report's
    overall risk score (per Simulator.pdf §6).
    """

    GREEN = "green"
    GREEN_BORDERLINE = "green_borderline"
    AMBER = "amber"
    RED = "red"
    RED_CRITICAL = "red_critical"
    NOT_APPLICABLE = "not_applicable"


class CriticalValue(BaseModel):
    """The boundary value of a parameter at which the FM verdict flips.

    Computed by `optimize_threshold` either via Z3 optimization over the
    declared parameter ranges, or by direct evaluation of the closed-form
    formula in `verifier.paper.PaperCondition.critical_values`.

    Attributes
    ----------
    parameter:
        Variable symbol from `paper.py`. Examples: ``"gamma"``, ``"N"``,
        ``"n_demote"``.
    value:
        The numeric boundary. Always populated for `direction=">="` and
        `"<="`; the value is the worst-case threshold over the declared
        ranges of the other variables.
    direction:
        ``">="`` if the system is sustainable when the parameter is **at
        least** ``value``; ``"<="`` for the reverse.
    formula:
        Plain-text formula the value was derived from (matches
        `CriticalValueFormula.formula_ascii` in `paper.py`).
    explanation:
        One-paragraph explanation rendered by the verdict screen.
    source:
        How the value was obtained: ``"optimize"`` (Z3 over ranges),
        ``"closed_form"`` (direct algebraic formula), or ``"config"``
        (a configurable threshold like τ_ceiling).
    """

    model_config = ConfigDict(extra="forbid")

    parameter: str
    value: float
    direction: Literal[">=", "<="]
    formula: str
    explanation: str
    source: Literal["optimize", "closed_form", "config"] = "optimize"


class NumericRecommendation(BaseModel):
    """An actionable redesign instruction emitted with a failing verdict.

    The user-facing form of a `CriticalValue`: tells the user *what to
    change* and *to what value*. Phase 2 populates `mechanism_mappings`
    with the structured-choice options that satisfy the threshold (e.g.
    "for FM4 γ ≥ 0.62, choose smart_contract_automation or
    physical_presence verification").

    Attributes
    ----------
    parameter:
        Variable symbol the user can adjust.
    current_range:
        The user-declared range, if any, as ``(min, max)``. ``None`` for
        derived parameters that have no direct user input.
    safe_threshold:
        The boundary value the user must clear (``≥`` or ``≤`` per
        ``direction``).
    direction:
        ``">="`` or ``"<="``.
    narrative:
        One-sentence plain-language instruction. Example: ``"Increase K
        to at least 7 tokens to satisfy FM5 across the full N range."``
    mechanism_mappings:
        Structured-choice alternatives that satisfy the threshold,
        populated by the elicitation layer in Phase 2. Empty in Phase 1.
    """

    model_config = ConfigDict(extra="forbid")

    parameter: str
    current_range: tuple[float, float] | None = None
    safe_threshold: float
    direction: Literal[">=", "<="]
    narrative: str
    mechanism_mappings: list[str] = Field(default_factory=list)


class Counterexample(BaseModel):
    """A concrete parameter assignment that exhibits a failure-mode violation.

    Attributes
    ----------
    parameter_values:
        The Z3-model values of every variable in the encoding, as a flat
        dict. Verdict screens render the most relevant 4–6 entries.
    narrative:
        Plain-language description of why the values constitute a
        violation.
    binding_constraint:
        For multi-clause violations (FM4 with both Ostrom and monitoring
        clauses), identifies which clause is the binding one — the
        actionable signal the user needs to fix first. Empty when there
        is a single clause.
    """

    model_config = ConfigDict(extra="forbid")

    parameter_values: dict[str, float] = Field(default_factory=dict)
    narrative: str = ""
    binding_constraint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_values": self.parameter_values,
            "narrative": self.narrative,
            "binding_constraint": self.binding_constraint,
        }


class Verdict(BaseModel):
    """The result of evaluating one failure mode on one subject."""

    model_config = ConfigDict(extra="forbid")

    failure_mode: str
    subject: str  # "system" or a token id
    status: Status
    formal_condition: str
    explanation: str
    counterexample: Counterexample | None = None
    margin: float | None = None
    suggestions: list[str] = Field(default_factory=list)
    critical_values: list[CriticalValue] = Field(default_factory=list)
    recommendation: NumericRecommendation | None = None
    swept_fields: list[str] = Field(default_factory=list)
    committed_fields: list[str] = Field(default_factory=list)
    # Phase D — risk band evaluated at midpoint values (Simulator.pdf §4).
    # Defaults to NOT_APPLICABLE for verdicts where the FM did not run
    # (archetype skip, applicability gate). Populated by `verifier.risk`.
    risk_level: RiskLevel = RiskLevel.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def z3_real_in_range(name: str, lo: float, hi: float) -> tuple[z3.ArithRef, list[Any]]:
    """Declare a Z3 real variable bounded to [lo, hi].

    Returns the variable and the list of bound assertions to add to a solver.
    """
    v = z3.Real(name)
    return v, [v >= lo, v <= hi]


def z3_value_to_float(model: z3.ModelRef, expr: z3.ArithRef) -> float:
    """Extract a Python float from a Z3 model value.

    Works for both leaf constants (`model[var]`) and compound arithmetic
    expressions (`model.eval(expr)`), letting callers pass either uniformly.
    """
    try:
        val = model[expr]
    except z3.Z3Exception:
        val = None
    if val is None:
        # Compound expression — use eval, ask for a model completion.
        val = model.eval(expr, model_completion=True)
    if val is None:
        return 0.0
    if z3.is_int_value(val):
        return float(val.as_long())
    if z3.is_rational_value(val):
        return float(val.numerator_as_long()) / float(val.denominator_as_long())
    # algebraic fallback
    s = val.as_decimal(12).rstrip("?")
    return float(s)


# ---------------------------------------------------------------------------
# Threshold extraction primitive (Phase 1)
# ---------------------------------------------------------------------------


def optimize_threshold(
    constraints: list[z3.BoolRef],
    target: z3.ArithRef,
    direction: Literal["max", "min"],
) -> float | None:
    """Find the extremum of `target` subject to `constraints`.

    The threshold-extraction primitive on which every Phase-1 critical-
    value extraction is built. Uses Z3's `Optimize` engine (the νZ
    optimization layer; see `docs/proofs/optimization.md`).

    Parameters
    ----------
    constraints:
        Iterable of `z3.BoolRef` constraints defining the feasibility
        region. The caller is responsible for ensuring the feasibility
        region is bounded; for unbounded regions the result is ``None``.
    target:
        The expression to extremize. Typically a single variable or a
        small algebraic combination of declared variables.
    direction:
        ``"max"`` for the upper bound, ``"min"`` for the lower bound.

    Returns
    -------
    float | None
        The optimal value of `target`, or ``None`` when the constraint
        set is unsatisfiable or `target` is unbounded over the
        feasibility region.

    Notes
    -----
    Z3 reasons over `ℚ` exactly. When the model returns a rational, we
    convert via numerator/denominator division (one floating-point
    rounding ulp). The conversion is well within `numeric_epsilon`
    (1e-9 default).

    `+oo` (Z3's positive infinity) maps to ``None`` rather than to
    `math.inf`, because an unbounded threshold is not actionable for
    the user — it indicates the caller's encoding under-constrained
    the variable.
    """
    opt = z3.Optimize()
    for c in constraints:
        opt.add(c)
    if direction == "max":
        opt.maximize(target)
    else:
        opt.minimize(target)
    result = opt.check()
    if result != z3.sat:
        return None
    model = opt.model()
    val = model.eval(target, model_completion=True)
    # Reject infinity / non-numeric optima (caller did not bound the region)
    if z3.is_int_value(val):
        return float(val.as_long())
    if z3.is_rational_value(val):
        return float(val.numerator_as_long()) / float(val.denominator_as_long())
    # Try the decimal fallback; if that fails, the optimum was unbounded
    try:
        s = val.as_decimal(12).rstrip("?")
        return float(s)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Failure-mode interface
# ---------------------------------------------------------------------------


class FailureMode(ABC):
    """A failure-mode evaluator.

    Subclasses implement `applies_to` (does this FM apply to this TE? possibly
    per-token) and `check` (run the Z3 query and return Verdict(s)).

    The dispatcher iterates over `ALL_FAILURE_MODES` and collects verdicts
    from each. Each FM is responsible for handling its own per-token
    multiplication: e.g. FM1 returns one Verdict per token; FM5 returns one
    system-level Verdict.

    Subclasses receive an optional `VerifierConfig` via `check`'s `config`
    parameter; FMs that consume configurable thresholds (FM3 ρ floor, FM4
    NFR multipliers, FM6 Γ threshold) should read from `config` rather
    than from the deprecated `verifier.constants` shim.
    """

    name: str = ""  # set by subclasses, e.g. "FM5: Insufficient Critical Mass"
    description: str = ""  # one-line plain-language description

    @abstractmethod
    def check(self, te: TokenEconomy, config: "Any" = None) -> list[Verdict]:
        """Run the failure-mode check.

        Returns one or more verdicts. An FM that does not apply to a given
        token or to the system as a whole returns a Verdict with
        Status.NOT_APPLICABLE (not an empty list), so the dispatcher can show
        the user that the FM was considered.

        `config` is a `VerifierConfig` or `None` (paper defaults). FMs that
        do not consume any configurable values may ignore the parameter.
        """
        raise NotImplementedError

    # Convenience for subclasses that build small Z3 queries.
    @staticmethod
    def make_solver() -> z3.Solver:
        s = z3.Solver()
        # Turn off unsat cores for speed; we only need sat models.
        s.set(unsat_core=False)
        return s
