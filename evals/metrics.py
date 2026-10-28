## =============================================================================
## evals/metrics.py — compute evaluation metrics from a finished run (pure functions)
## =============================================================================
## GUIDE STEP   13.2
## PURPOSE      Turns one finished interview (the elicited spec, the transcript
##              of tool calls, the verdicts) plus the hidden spec into the
##              numbers listed in evals/README.md. No I/O and no model calls:
##              everything here is deterministic and unit-testable.
## USED BY      evals/run.py.
## DEPENDS ON   te_platform.service (validate → normalised spec; verify →
##              verdicts on both specs), te_platform.hashing (equal hash =
##              identical specs, the shortcut for a perfect interview).
## WHY          Guide 13.2 / architecture §3.9. Verdict agreement is the key
##              metric: the platform exists to get the failure-mode verdicts
##              right, not to copy every field.
## ACTIVATE     Uncomment with run.py; write small unit tests for each function
##              with hand-made inputs before trusting the numbers.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the class names, field names
## and metric keys exactly as written here: evals/run.py uses them.
## te_platform/service.py and hashing.py (guide 1.2-1.6) must be active.
##
## Guide 13.2
## [ ] 1. Imports at the top: `dataclass` and `field` from dataclasses, `Any`
##        from typing, and `hashing` and `service` from te_platform.
## [ ] 2. `@dataclass class ToolCallRecord` with `tool: str`, `ok: bool` and
##        `error_code: str | None = None`. run.py builds it with
##        ToolCallRecord(**t), so the names must equal its dict keys.
## [ ] 3. `@dataclass class RunRecord`: first the fields without defaults
##        (case, elicited_spec: dict | None, hidden_spec, user_turns: int),
##        then the list fields tool_calls, open_decisive_slots, verdicts,
##        declined_simulation_fms, each with
##          | field(default_factory=list)
##        and finally `report_rejections: int = 0`,
##        `designer_refused: bool = False`, `agent_tokens: int = 0` and
##        `designer_tokens: int = 0` (run.py fills them all).
## [ ] 4. `_leaves(obj, prefix="")`: flatten nested dicts and lists into
##        {"tokens.0.name": value, ...}, recursing with the key or index plus
##        "." added to the prefix; a plain value ends the recursion:
##          | return {prefix.rstrip("."): obj}
## [ ] 5. `_close(a, b, rel_tol=0.05)`: two numbers (no bools) are equal
##        when within 5 % of the larger one; anything else uses ==. A
##        range is two leaves (min, max), so each bound is compared alone.
## [ ] 6. `field_accuracy(elicited, hidden) -> float`: 0.0 when elicited is
##        None; normalise both with service.validate(...).normalised_spec
##        (or {}); 1.0 when their hashing.spec_hash values are equal; else
##        the share of the hidden spec's leaves present in the elicited one
##        and _close to it (1.0 if the hidden spec has no leaves).
## [ ] 7. `_verdict_map(spec)`: run service.verify(spec) and map
##        (failure_mode, subject) to status for each item of
##        result.report["verdicts"].
## [ ] 8. `verdict_agreement(elicited, hidden) -> float`: 0.0 when elicited
##        is None; else the share of the hidden map's pairs whose status is
##        the same in the elicited map (divide by max(len, 1)).
## [ ] 9. `precondition_violations(run)`: count the tool calls whose
##        error_code is "precondition_failed".
## [ ] 10. `unnecessary_simulations(run)`: collect the verdicts'
##         structural_status values, minus "not_applicable" and None. If
##         some remain and all are "sound" or "broken", count the successful
##         calls whose tool starts with "sim."; otherwise return 0.
## [ ] 11. `missed_simulations(run)`: the failure modes whose status is
##         "inconclusive" or whose structural_status is "fragile". Return 0
##         if any successful sim.monte_carlo.v1 call exists; else the number
##         of those failure modes not in run.declined_simulation_fms.
## [ ] 12. `summarise(run) -> dict`: one dict with the keys case,
##         field_accuracy, verdict_agreement, turns, decisive_slots_missed
##         (len of open_decisive_slots), precondition_violations,
##         unnecessary_simulations, missed_simulations,
##         narrative_number_failures (from report_rejections),
##         designer_refused, agent_tokens and designer_tokens.
## [ ] 13. Check: as the header's ACTIVATE says, write small unit tests with
##         hand-made inputs, e.g. a RunRecord with two "precondition_failed"
##         calls gives precondition_violations(run) == 2, and run them with
##         `uv run pytest <your test file> -q`.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from dataclasses import dataclass, field
from typing import Any

from te_platform import hashing, service


@dataclass
class ToolCallRecord:
    """One tool call of the interviewer, as logged by run.py."""

    tool: str
    ok: bool
    error_code: str | None = None  # e.g. "precondition_failed"


@dataclass
class RunRecord:
    """Everything run.py collected for one case."""

    case: str
    elicited_spec: dict[str, Any] | None
    hidden_spec: dict[str, Any]
    user_turns: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    open_decisive_slots: list[str] = field(default_factory=list)
    # Verdicts the interviewer obtained (from verify.run.v1), if any.
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    # Failure modes the user explicitly declined to simulate (not "missed").
    declined_simulation_fms: list[str] = field(default_factory=list)
    # report.render_pdf.v1 calls refused as invalid input: the narrative
    # number check (guide 10.2), see evals/README.md.
    report_rejections: int = 0
    # The simulated designer refused to answer: the case stopped early.
    designer_refused: bool = False
    # Tokens the API reported (cached ones included) for the interviewer
    # (from the `done` events) and for the simulated designer.
    agent_tokens: int = 0
    designer_tokens: int = 0


## --- Field accuracy ----------------------------------------------------------------
def _leaves(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested spec into {"tokens.0.name": "BTC", ...} so two specs
    can be compared field by field."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            out.update(_leaves(v, f"{prefix}{k}."))
        return out
    if isinstance(obj, list):
        out = {}
        for i, v in enumerate(obj):
            out.update(_leaves(v, f"{prefix}{i}."))
        return out
    return {prefix.rstrip("."): obj}


def _close(a: Any, b: Any, rel_tol: float = 0.05) -> bool:
    """Numbers within 5 %, everything else equal. (Ranges are stored as
    {min, max} leaves, so each bound is compared separately.)"""
    numbers = (int, float)
    # bool is a subclass of int in Python: flags are compared with ==.
    if (
        isinstance(a, numbers)
        and isinstance(b, numbers)
        and not isinstance(a, bool)
        and not isinstance(b, bool)
    ):
        return abs(a - b) <= rel_tol * max(abs(a), abs(b), 1e-12)
    return bool(a == b)


def field_accuracy(elicited: dict[str, Any] | None, hidden: dict[str, Any]) -> float:
    """Share of the hidden spec's (normalised) fields reproduced by the interview."""
    if elicited is None:
        return 0.0
    e = service.validate(elicited).normalised_spec or {}
    h = service.validate(hidden).normalised_spec or {}
    # Identical hashes = identical specs: no need to compare field by field.
    if hashing.spec_hash(e) == hashing.spec_hash(h):
        return 1.0
    hl, el = _leaves(h), _leaves(e)
    if not hl:
        return 1.0
    return sum(1 for k, v in hl.items() if k in el and _close(el[k], v)) / len(hl)


## --- Verdict agreement --------------------------------------------------------------
def _verdict_map(spec: dict[str, Any]) -> dict[tuple[str, str], str]:
    r = service.verify(spec)
    return {(v["failure_mode"], v["subject"]): v["status"] for v in r.report["verdicts"]}


def verdict_agreement(elicited: dict[str, Any] | None, hidden: dict[str, Any]) -> float:
    """Share of (failure mode, subject) pairs with the same verdict status.

    A multi-token economy has one verdict per failure mode AND subject
    (token), so pairs are compared, not failure modes alone. Runs the
    verifier twice (Z3): slow, call once per case.
    """
    if elicited is None:
        return 0.0
    h = _verdict_map(hidden)
    e = _verdict_map(elicited)
    return sum(1 for k, s in h.items() if e.get(k) == s) / max(len(h), 1)


## --- Behaviour counters --------------------------------------------------------------
def precondition_violations(run: RunRecord) -> int:
    return sum(1 for c in run.tool_calls if c.error_code == "precondition_failed")


def unnecessary_simulations(run: RunRecord) -> int:
    """Simulations when every applicable FM was sound or broken (policy:
    sim.monte_carlo.v1 -> do_not_use_when)."""
    statuses = {v.get("structural_status") for v in run.verdicts} - {"not_applicable", None}
    if statuses and statuses <= {"sound", "broken"}:
        return sum(1 for c in run.tool_calls if c.tool.startswith("sim.") and c.ok)
    return 0


def missed_simulations(run: RunRecord) -> int:
    """Inconclusive/fragile FMs left without a simulation and without an
    explicit user decision not to simulate."""
    needing = {
        v["failure_mode"]
        for v in run.verdicts
        if v.get("status") == "inconclusive" or v.get("structural_status") == "fragile"
    }
    simulated = any(c.tool == "sim.monte_carlo.v1" and c.ok for c in run.tool_calls)
    return 0 if simulated else len(needing - set(run.declined_simulation_fms))


def summarise(run: RunRecord) -> dict[str, Any]:
    """All metrics of one case, as written to results/<case>.json."""
    return {
        "case": run.case,
        "field_accuracy": field_accuracy(run.elicited_spec, run.hidden_spec),
        "verdict_agreement": verdict_agreement(run.elicited_spec, run.hidden_spec),
        "turns": run.user_turns,
        "decisive_slots_missed": len(run.open_decisive_slots),
        "precondition_violations": precondition_violations(run),
        "unnecessary_simulations": unnecessary_simulations(run),
        "missed_simulations": missed_simulations(run),
        "narrative_number_failures": run.report_rejections,
        "designer_refused": run.designer_refused,
        "agent_tokens": run.agent_tokens,
        "designer_tokens": run.designer_tokens,
    }
