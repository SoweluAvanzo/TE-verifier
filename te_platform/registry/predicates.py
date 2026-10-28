## =============================================================================
## te_platform/registry/predicates.py — the named rules the policy refers to
## =============================================================================
## GUIDE STEP   2.2
## PURPOSE      policy/tool_policy.yaml refers to rules by NAME
##              ("verified_spec", "any_inconclusive_or_fragile", ...). This
##              file implements each name as a small Python function and
##              records it in a dictionary, so the pipeline can look it up.
##              Three kinds:
##              - preconditions: (ctx) -> bool, checked BEFORE a tool runs;
##              - predicates:    (ctx) -> bool, used for states and
##                               suggested_next (may read ctx.result);
##              - args_from:     (ctx) -> dict, suggested arguments for a
##                               suggested tool.
## USED BY      loader.py (checks every name in the policy exists here),
##              pipeline.py (calls preconditions and suggestion predicates),
##              state.py (calls the `enter_when` predicates).
## DEPENDS ON   registry/context.py. Nothing else: rules are pure functions of
##              the CallContext, so they are trivial to unit-test.
## WHY          D3: no expression language and no eval() on policy text (that
##              would be a code-injection risk on a public server); D7:
##              next-step suggestions are computed by code, deterministically.
## ACTIVATE     Uncomment the registry section first, then the rules one by
##              one, each with its test in test_platform_predicates.py.
##              Add a rule here BEFORE using its name in the policy: the
##              consistency test (loader.py) fails otherwise.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Every rule name in quotes
## must be EXACTLY the name used in policy/tool_policy.yaml, and keep the
## decorator names (te_platform/README.md, contracts table). Activate
## context.py first.
##
## Guide 2.2
## [ ] 1. Imports at the top: `Callable` from collections.abc, `Any` from
##        typing, `CallContext` from te_platform.registry.context.
## [ ] 2. The registry section: the aliases `Rule` (ctx -> bool) and `ArgsFn`
##        (ctx -> dict[str, Any]), then three empty dicts PRECONDITIONS,
##        PREDICATES and ARGS_FROM.
## [ ] 3. The decorators: a private `_register(table, name)` that returns an
##        inner `deco(fn)`; deco raises ValueError if the name is already in
##        the table, else stores fn and returns it unchanged. Then the public
##        `precondition(name)`, `predicate(name)` and `args_from(name)`, each
##        one line calling _register with its own table. Every public
##        function in this file (decorators and rules) gets a one-line
##        docstring saying what it allows or detects (ruff's D103).
## [ ] 4. Helper `_verdicts(ctx)`: the "verdicts" list of ctx.result, or []
##        when there is no result.
## [ ] 5. The five preconditions, each a one-line read of ctx.facts or
##        ctx.session: valid_spec, decisive_slots_resolved (True for a
##        stateless call), verified_spec, verification_ref_matches_spec,
##        job_quota_available. Shape of each:
##          | @precondition("valid_spec")
##          | def valid_spec(ctx: CallContext) -> bool:
## [ ] 6. The state predicates (@predicate): session_created,
##        elicitation_complete, elicitation_incomplete (its negation),
##        current_spec_verified (the stored ref belongs to the CURRENT spec
##        hash), simulation_finished_for_current_ref,
##        report_rendered_for_current_ref. Wrap results in bool(...).
## [ ] 7. The suggestion predicates, which read ctx.result:
##        has_error_level_coherence_issue, any_inconclusive_or_fragile,
##        inconclusive_due_to_swept_slot, any_fail, all_decided (False when
##        there are no verdicts), simulation_job_finished.
## [ ] 8. The two argument builders (@args_from):
##        inconclusive_or_fragile_failure_modes returns failure_modes (sorted,
##        no duplicates) and verification_ref; failed_failure_mode_topics
##        returns a "query" string. Keys must be valid input of the target.
## [ ] 9. Check: activate tests/platform_tests/test_platform_predicates.py,
##        each test with the rule it tests, then
##          | uv run pytest tests/platform_tests/test_platform_predicates.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from collections.abc import Callable
from typing import Any

from te_platform.registry.context import CallContext

# --- The three registries ------------------------------------------------------
# Module-level dictionaries, filled once at import time by the decorators
# below. This is the only module-level state allowed in te_platform
# (README rule 5), because it never changes after startup.
Rule = Callable[[CallContext], bool]
ArgsFn = Callable[[CallContext], dict[str, Any]]

PRECONDITIONS: dict[str, Rule] = {}
PREDICATES: dict[str, Rule] = {}
ARGS_FROM: dict[str, ArgsFn] = {}


# --- Decorators ----------------------------------------------------------------
# A decorator is a function that receives another function. Writing
#     @precondition("valid_spec")
#     def valid_spec(ctx): ...
# is the same as `valid_spec = precondition("valid_spec")(valid_spec)`:
# the function is stored in PRECONDITIONS under that name and returned
# unchanged.
def _register(table: dict[str, Any], name: str) -> Callable[[Any], Any]:
    def deco(fn: Any) -> Any:
        if name in table:
            raise ValueError(f"rule {name!r} registered twice")
        table[name] = fn
        return fn
    return deco


def precondition(name: str) -> Callable[[Rule], Rule]:
    """Register the decorated function as the precondition `name`."""
    return _register(PRECONDITIONS, name)


def predicate(name: str) -> Callable[[Rule], Rule]:
    """Register the decorated function as the predicate `name`."""
    return _register(PREDICATES, name)


def args_from(name: str) -> Callable[[ArgsFn], ArgsFn]:
    """Register the decorated function as the argument builder `name`."""
    return _register(ARGS_FROM, name)


# --- Small helper -----------------------------------------------------------------
def _verdicts(ctx: CallContext) -> list[dict[str, Any]]:
    """Per-FM verdicts from a verify.run.v1 result (ctx.result)."""
    verdicts: list[dict[str, Any]] = (ctx.result or {}).get("verdicts", [])
    return verdicts


# --- Preconditions (names from policy -> preconditions) ---------------------------
# Each returns True when the tool MAY run. They only READ ctx.facts, which
# registry/facts.py filled in before (pipeline step 3b).

@precondition("valid_spec")
def valid_spec(ctx: CallContext) -> bool:
    """Allow the call only if it carries a spec that passed schema validation."""
    return ctx.facts.spec_present and ctx.facts.spec_valid


@precondition("decisive_slots_resolved")
def decisive_slots_resolved(ctx: CallContext) -> bool:
    """Allow the call only if no decisive interview question is still open."""
    # Stateless calls have no interview, so nothing can be "open".
    return ctx.session is None or not ctx.session.open_decisive_slots


@precondition("verified_spec")
def verified_spec(ctx: CallContext) -> bool:
    """Allow the call only if a verification_ref is presented."""
    # Stateless clients prove verification by passing the verification_ref
    # that verify.run.v1 returned; sessions have it stored.
    return ctx.facts.verification_ref is not None


@precondition("verification_ref_matches_spec")
def verification_ref_matches_spec(ctx: CallContext) -> bool:
    """Allow the call only if the verification_ref was computed from this spec."""
    # True only if the ref was computed from exactly this spec (D5):
    # an edited spec, or a ref copied from another spec, fails here.
    return ctx.facts.verification_matches_spec


@precondition("job_quota_available")
def job_quota_available(ctx: CallContext) -> bool:
    """Allow the call only if the caller may start another background job."""
    return ctx.facts.quota_ok


# --- Predicates for states (policy -> states -> enter_when) ------------------------
@predicate("session_created")
def session_created(ctx: CallContext) -> bool:
    """Enter `eliciting` when the call belongs to a session."""
    return ctx.session is not None


@predicate("elicitation_complete")
def elicitation_complete(ctx: CallContext) -> bool:
    """Enter `spec_ready` when a spec exists and no decisive question is open."""
    s = ctx.session
    # Coherence issues deliberately do NOT block (see the `spec_ready` state
    # in the policy): they are reported and discussed, not enforced.
    return bool(s and s.current_spec_hash and not s.open_decisive_slots)


@predicate("elicitation_incomplete")
def elicitation_incomplete(ctx: CallContext) -> bool:
    """Negate elicitation_complete (used by suggested_next)."""
    return not elicitation_complete(ctx)


@predicate("current_spec_verified")
def current_spec_verified(ctx: CallContext) -> bool:
    """Enter `verified` when the stored verification belongs to the CURRENT spec."""
    s = ctx.session
    return bool(s and s.verification_ref and s.verified_spec_hash == s.current_spec_hash)


@predicate("simulation_finished_for_current_ref")
def simulation_finished_for_current_ref(ctx: CallContext) -> bool:
    """Enter `simulated` when a simulation finished for the current verification."""
    return bool(ctx.session and ctx.session.finished_simulation_for_current_ref)


@predicate("report_rendered_for_current_ref")
def report_rendered_for_current_ref(ctx: CallContext) -> bool:
    """Enter `reported` when a report exists for the current verification."""
    return bool(ctx.session and ctx.session.report_for_current_ref)


# --- Predicates for suggested_next (read ctx.result) --------------------------------
@predicate("has_error_level_coherence_issue")
def has_error_level_coherence_issue(ctx: CallContext) -> bool:
    """Detect a coherence issue of severity `error` in the result."""
    issues = (ctx.result or {}).get("coherence_issues", [])
    return any(i.get("severity") == "error" for i in issues)


@predicate("any_inconclusive_or_fragile")
def any_inconclusive_or_fragile(ctx: CallContext) -> bool:
    """Detect a failure mode that is inconclusive or structurally fragile."""
    return any(v.get("status") == "inconclusive" or v.get("structural_status") == "fragile"
               for v in _verdicts(ctx))


@predicate("inconclusive_due_to_swept_slot")
def inconclusive_due_to_swept_slot(ctx: CallContext) -> bool:
    """Detect an inconclusive verdict that depends on an input left unknown."""
    # An inconclusive verdict whose outcome depends on an input the user
    # left unknown: asking that question can decide it without simulation.
    return any(v.get("status") == "inconclusive" and v.get("swept_fields")
               for v in _verdicts(ctx))


@predicate("any_fail")
def any_fail(ctx: CallContext) -> bool:
    """Detect a failing failure mode."""
    return any(v.get("status") == "fail" for v in _verdicts(ctx))


@predicate("all_decided")
def all_decided(ctx: CallContext) -> bool:
    """Detect that there are verdicts and none of them is inconclusive."""
    v = _verdicts(ctx)
    return bool(v) and all(x.get("status") != "inconclusive" for x in v)


@predicate("simulation_job_finished")
def simulation_job_finished(ctx: CallContext) -> bool:
    """Detect a finished Monte Carlo or trajectory job in the result."""
    r = ctx.result or {}
    return r.get("status") == "finished" and r.get("kind") in {"monte_carlo", "trajectory"}


# --- Argument builders (policy -> suggested_next -> args_from) -----------------------
# Each returns arguments that are VALID INPUT for the suggested tool (the
# model may pass them as they are): sim.monte_carlo.v1 accepts
# failure_modes + verification_ref, lit.search.v1 accepts query. A rule
# whose target needs input only the user can give (e.g. an answer) has no
# args_from; the model asks the user instead.
@args_from("inconclusive_or_fragile_failure_modes")
def inconclusive_or_fragile_failure_modes(ctx: CallContext) -> dict[str, Any]:
    """Build sim.monte_carlo.v1 arguments: the undecided failure modes and the ref."""
    fms = sorted({v["failure_mode"] for v in _verdicts(ctx)
                  if v.get("status") == "inconclusive"
                  or v.get("structural_status") == "fragile"})
    return {"failure_modes": fms, "verification_ref": (ctx.result or {}).get("verification_ref")}


@args_from("failed_failure_mode_topics")
def failed_failure_mode_topics(ctx: CallContext) -> dict[str, Any]:
    """Build lit.search.v1 arguments: a query about the failing failure modes."""
    fms = sorted({v["failure_mode"] for v in _verdicts(ctx) if v.get("status") == "fail"})
    return {"query": " ".join(fms) + " remedies token economy design"}
