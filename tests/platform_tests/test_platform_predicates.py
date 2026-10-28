## =============================================================================
## tests/platform_tests/test_platform_predicates.py — tests for registry/predicates.py
## =============================================================================
## GUIDE STEP   2.2 (activate each test together with the rule it tests);
##              6.2, 11.2 (labelled blocks, commented twice)
## PURPOSE      Every named rule (precondition, predicate, args builder) is a
##              pure function of a CallContext, so each is tested with small,
##              hand-built contexts: no database, no verifier, milliseconds.
## DEPENDS ON   te_platform/registry/predicates.py, registry/context.py
##              (Principal, SessionFacts, CallFacts, CallContext).
## WHY          Architecture D3/D4/D7: these rules decide what the server
##              allows and what it suggests; each needs an explicit test of
##              both outcomes (allowed / refused, true / false).
## ACTIVATE     Uncomment the fixtures first, then the tests of each rule as
##              you activate that rule. The two argument-validation tests
##              import tool input models: activate them at 6.2 and 11.2
##              (labelled, commented twice).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
## Uncomment the fixtures and helpers first (header, ACTIVATE).
##
## Guide 2.2
## [ ] 1. Imports: `pytest`, `predicates as P` from te_platform.registry,
##        and `CallContext, CallFacts, Principal, SessionFacts` from
##        te_platform.registry.context.
## [ ] 2. Fixture `principal() -> Principal`: Principal(id="u1",
##        kind="user").
## [ ] 3. Two plain helpers (not fixtures): `ctx(principal, *,
##        session=None, facts=None, result=None, tool="verify.run.v1")`
##        returning a CallContext (facts default to CallFacts()), and
##        `session(**kw)` returning SessionFacts with session_id "s1" and
##        owner_id "u1".
## [ ] 4. One test per precondition, each asserting BOTH outcomes, e.g.
##          | assert not P.PRECONDITIONS["verified_spec"](ctx(principal))
##        - test_valid_spec_needs_a_present_and_valid_spec;
##        - test_decisive_slots_resolved (no session or no open slots:
##          true; open_decisive_slots=["participants.N"]: false);
##        - test_verified_spec_needs_a_verification_ref;
##        - test_verification_ref_must_match_this_spec
##          (verification_matches_spec True vs False);
##        - test_job_quota_available (default facts: true; quota_ok=False:
##          false).
## [ ] 5. State predicates (read ctx.session):
##        - test_elicitation_complete_ignores_coherence_issues: a spec hash
##          and no open slots -> complete; open slots or no spec -> not
##          complete; an empty session -> elicitation_incomplete;
##        - test_current_spec_verified_detects_edits_after_verification:
##          equal hashes -> true, current hash edited -> false.
## [ ] 6. Constant VERDICTS: verification_ref "vref:1" and three verdicts:
##        FM1 pass/sound, FM3 inconclusive/fragile with swept_fields
##        ["participants.growth"], FM5 fail/broken.
## [ ] 7. test_suggestion_predicates_on_mixed_verdicts: with result=VERDICTS
##        any_inconclusive_or_fragile, inconclusive_due_to_swept_slot and
##        any_fail are true, all_decided is false.
## [ ] 8. test_has_error_level_coherence_issue: a "warn" issue -> false, an
##        "error" issue -> true.
## [ ] 9. test_simulation_job_finished: a finished "monte_carlo" job ->
##        true, a finished "report" job -> false.
## [ ] 10. Argument builders (P.ARGS_FROM):
##        - test_args_for_simulation_restrict_to_undecided_failure_modes:
##          the result equals {"failure_modes": ["FM3"],
##          "verification_ref": "vref:1"};
##        - test_args_for_literature: "FM5" is in the built "query".
## [ ] 11. test_a_name_cannot_be_registered_twice: registering
##        P.precondition("valid_spec") again raises ValueError.
## [ ] 12. Check:
##          | uv run pytest tests/platform_tests/test_platform_predicates.py -q
##
## Guide 6.2 (later: the "# # " block under its label)
## [ ] 13. test_simulation_arguments_are_valid_sim_monte_carlo_input:
##        import SimMonteCarloInput inside the test; the keys built by
##        inconclusive_or_fragile_failure_modes on VERDICTS are fields of
##        it, and model_validate accepts them.
## [ ] 14. Check: the step 12 command.
##
## Guide 11.2 (later: the "# # " block under its label)
## [ ] 15. test_literature_arguments_are_valid_lit_search_input: the same
##        for failed_failure_mode_topics and LitSearchInput.
## [ ] 16. Check: the step 12 command.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import pytest

from te_platform.registry import predicates as P
from te_platform.registry.context import CallContext, CallFacts, Principal, SessionFacts


## --- Fixtures: small factories for contexts -------------------------------------------
@pytest.fixture
def principal() -> Principal:
    return Principal(id="u1", kind="user")


def ctx(principal, *, session=None, facts=None, result=None, tool="verify.run.v1") -> CallContext:
    return CallContext(
        principal=principal,
        tool_id=tool,
        tool_input={},
        session=session,
        facts=facts or CallFacts(),
        result=result,
    )


def session(**kw) -> SessionFacts:
    return SessionFacts(session_id="s1", owner_id="u1", **kw)


## --- Preconditions ------------------------------------------------------------------------
def test_valid_spec_needs_a_present_and_valid_spec(principal):
    assert P.PRECONDITIONS["valid_spec"](
        ctx(principal, facts=CallFacts(spec_present=True, spec_valid=True))
    )
    assert not P.PRECONDITIONS["valid_spec"](
        ctx(principal, facts=CallFacts(spec_present=True, spec_valid=False))
    )
    assert not P.PRECONDITIONS["valid_spec"](ctx(principal, facts=CallFacts(spec_present=False)))


def test_decisive_slots_resolved(principal):
    assert P.PRECONDITIONS["decisive_slots_resolved"](ctx(principal))  # stateless: nothing open
    assert P.PRECONDITIONS["decisive_slots_resolved"](ctx(principal, session=session()))
    assert not P.PRECONDITIONS["decisive_slots_resolved"](
        ctx(principal, session=session(open_decisive_slots=["participants.N"]))
    )


def test_verified_spec_needs_a_verification_ref(principal):
    assert P.PRECONDITIONS["verified_spec"](
        ctx(principal, facts=CallFacts(verification_ref="vref:x"))
    )
    assert not P.PRECONDITIONS["verified_spec"](ctx(principal))


def test_verification_ref_must_match_this_spec(principal):
    ok = CallFacts(verification_ref="vref:x", verification_matches_spec=True)
    stale = CallFacts(verification_ref="vref:x", verification_matches_spec=False)
    assert P.PRECONDITIONS["verification_ref_matches_spec"](ctx(principal, facts=ok))
    assert not P.PRECONDITIONS["verification_ref_matches_spec"](ctx(principal, facts=stale))


def test_job_quota_available(principal):
    assert P.PRECONDITIONS["job_quota_available"](ctx(principal))
    assert not P.PRECONDITIONS["job_quota_available"](
        ctx(principal, facts=CallFacts(quota_ok=False))
    )


## --- State predicates ------------------------------------------------------------------------
def test_elicitation_complete_ignores_coherence_issues(principal):
    # Coherence issues are discussed, never blocking (see the policy's
    # `spec_ready` state): only a spec and no open decisive slots matter.
    assert P.PREDICATES["elicitation_complete"](
        ctx(principal, session=session(current_spec_hash="spec:a"))
    )
    assert not P.PREDICATES["elicitation_complete"](
        ctx(principal, session=session(current_spec_hash="spec:a", open_decisive_slots=["x"]))
    )
    assert not P.PREDICATES["elicitation_complete"](ctx(principal, session=session()))
    assert P.PREDICATES["elicitation_incomplete"](ctx(principal, session=session()))


def test_current_spec_verified_detects_edits_after_verification(principal):
    fresh = session(
        current_spec_hash="spec:a", verification_ref="vref:1", verified_spec_hash="spec:a"
    )
    edited = session(
        current_spec_hash="spec:b", verification_ref="vref:1", verified_spec_hash="spec:a"
    )
    assert P.PREDICATES["current_spec_verified"](ctx(principal, session=fresh))
    assert not P.PREDICATES["current_spec_verified"](ctx(principal, session=edited))


## --- Suggestion predicates (read ctx.result) --------------------------------------------------
VERDICTS = {
    "verification_ref": "vref:1",
    "verdicts": [
        {"failure_mode": "FM1", "status": "pass", "structural_status": "sound", "swept_fields": []},
        {
            "failure_mode": "FM3",
            "status": "inconclusive",
            "structural_status": "fragile",
            "swept_fields": ["participants.growth"],
        },
        {
            "failure_mode": "FM5",
            "status": "fail",
            "structural_status": "broken",
            "swept_fields": [],
        },
    ],
}


def test_suggestion_predicates_on_mixed_verdicts(principal):
    c = ctx(principal, result=VERDICTS)
    assert P.PREDICATES["any_inconclusive_or_fragile"](c)
    assert P.PREDICATES["inconclusive_due_to_swept_slot"](c)
    assert P.PREDICATES["any_fail"](c)
    assert not P.PREDICATES["all_decided"](c)


def test_has_error_level_coherence_issue(principal):
    warn = {"coherence_issues": [{"severity": "warn"}]}
    err = {"coherence_issues": [{"severity": "error"}]}
    assert not P.PREDICATES["has_error_level_coherence_issue"](ctx(principal, result=warn))
    assert P.PREDICATES["has_error_level_coherence_issue"](ctx(principal, result=err))


def test_simulation_job_finished(principal):
    done = {"status": "finished", "kind": "monte_carlo"}
    report = {"status": "finished", "kind": "report"}
    assert P.PREDICATES["simulation_job_finished"](ctx(principal, result=done))
    assert not P.PREDICATES["simulation_job_finished"](ctx(principal, result=report))


## --- Argument builders -------------------------------------------------------------------------
def test_args_for_simulation_restrict_to_undecided_failure_modes(principal):
    args = P.ARGS_FROM["inconclusive_or_fragile_failure_modes"](ctx(principal, result=VERDICTS))
    assert args == {"failure_modes": ["FM3"], "verification_ref": "vref:1"}


def test_args_for_literature(principal):
    c = ctx(principal, result=VERDICTS)
    assert "FM5" in P.ARGS_FROM["failed_failure_mode_topics"](c)["query"]


## Suggested arguments must be valid input for the suggested tool, or the
## model would be handed arguments the tool rejects. The target tools are
## built later, so each test is activated with its tool (commented twice).
## Every key must be a field of the input model (the models accept unknown
## keys, so model_validate alone would not notice a misspelled key).
## Guide 6.2: sim.monte_carlo.v1 exists from this step.
def test_simulation_arguments_are_valid_sim_monte_carlo_input(principal):
    from te_platform.tools.sim_monte_carlo import SimMonteCarloInput

    args = P.ARGS_FROM["inconclusive_or_fragile_failure_modes"](ctx(principal, result=VERDICTS))
    assert set(args) <= set(SimMonteCarloInput.model_fields)
    SimMonteCarloInput.model_validate(args)


## Guide 11.2: lit.search.v1 exists from this step.
def test_literature_arguments_are_valid_lit_search_input(principal):
    from te_platform.tools.lit_search import LitSearchInput

    args = P.ARGS_FROM["failed_failure_mode_topics"](ctx(principal, result=VERDICTS))
    assert set(args) <= set(LitSearchInput.model_fields)
    LitSearchInput.model_validate(args)


## --- Registry hygiene --------------------------------------------------------------------------
def test_a_name_cannot_be_registered_twice():
    with pytest.raises(ValueError):
        P.precondition("valid_spec")(lambda ctx: True)
