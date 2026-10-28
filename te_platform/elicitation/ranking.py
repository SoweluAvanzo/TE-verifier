## =============================================================================
## te_platform/elicitation/ranking.py — choose the next questions with the verifier
## =============================================================================
## GUIDE STEP   7.5
## PURPOSE      next_questions(protocol, spec, answers) decides WHAT TO ASK
##              NEXT and WHETHER THE INTERVIEW IS COMPLETE (architecture §4.3).
##
##              Algorithm, in plain words:
##              1. List the OPEN items: applicable slots (routing.py, which
##                 reads the spec) that have no recorded answer AND no value
##                 in the spec yet. Per-item slots ("tokens[]...") give one
##                 item per element already in the spec (paths.index_combos);
##                 a `list` slot (e.g. tokens.ids) is one item, open until
##                 every element has its value.
##              2. Build a SWEPT COPY of the partial spec: every open item is
##                 filled as "unknown" (answers.py), i.e. with its full
##                 plausible range. This is the most pessimistic version of
##                 what the user might still say.
##              3. If that copy is schema-valid, run the verifier's triage on
##                 it (service.minimal: structural_status and
##                 minimum_param_shift per failure mode). If not (early in the
##                 interview, required parts are still missing), fall back to
##                 protocol order.
##              4. SCORE each open item, highest first, by a tuple compared
##                 left to right:
##                   (a) impact on verdicts:
##                       2 = its parameter appears in `minimum_param_shift` of
##                           a verdict that is not settled (fragile,
##                           inconclusive or broken): pinning it down can
##                           change that verdict directly;
##                       1 = it feeds (slot.feeds) a failure mode whose verdict
##                           is not settled;
##                       0 = no unsettled verdict depends on it;
##                   (b) criticality: decisive > important > bookkeeping;
##                   (c) protocol order (earlier stage, earlier slot first),
##                       so the conversation still flows like the
##                       specification flow.
##              5. Return the top 1-3 items, and complete=True when no
##                 decisive item is open AND no open item has impact > 0
##                 (stopping rule: nothing still unknown can change a verdict).
##                 Items with impact 0 are listed in `not_needed` (as
##                 Questions, with their indices): the agent records those
##                 that allow unknown as "unknown" (swept) without asking,
##                 telling the user why; the others may stay unanswered (the
##                 schema's defaults apply, and the verifier already ran
##                 without them).
##
## USED BY      tools/elicit_next_questions.py (next_questions), db/repo.py
##              (open_decisive_slots, for
##              SessionFacts and the session state).
## DEPENDS ON   protocol.py (incl. current_protocol), paths.py, routing.py,
##              answers.py, te_platform.service (validate, minimal),
##              verifier/paper.py (ALL_CONDITIONS: provides the
##              why-we-ask text).
## WHY          Interviews short FOR THE SPECIFIC DESIGN; the stopping rule is
##              computed from the verifier's own output, not guessed by the
##              model (architecture P1, §4.3).
## SHIFT KEYS  `minimum_param_shift` keys come from the verifier's
##              NumericRecommendation(parameter=...) (verifier/minimal.py,
##              _threshold_from). They were checked against the real verifier
##              when this scaffold was written and are mapped explicitly in
##              _SHIFT_KEY_TO_IR_PATH below; a test fails if a new key appears.
## ACTIVATE     Uncomment; tests (guide 7.5): for each case study with one
##              decisive slot removed, that slot is ranked first; complete
##              spec -> complete=True; invalid partial spec -> protocol order.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. The header's "Algorithm, in plain
## words" is your map: steps 1-5 there match the functions below. Keep the
## public names exactly (Question, NextQuestions, open_decisive_slots,
## next_questions, _shift_key_to_path): the tools, db/repo.py and the tests
## use them. Activate protocol.py, paths.py, routing.py, answers.py and
## service.py first.
##
## Guide 7.5
## [ ] 1. Imports at the top: `Any`, `Literal`, pydantic's BaseModel and
##        Field, ALL_CONDITIONS (verifier.paper), `service`, `routing`,
##        apply_answer (answers.py), has_value and index_combos (paths.py),
##        Protocol, Slot, Stage and current_protocol (protocol.py).
## [ ] 2. Two output models. `Question`: slot_id, indices (list[int]),
##        intent, why_we_ask, answer_type, choices, allow_unknown,
##        criticality, probes, elicitation_method. `NextQuestions`:
##        questions, complete, open_decisive_slots, not_needed, and
##        ranking_basis (Literal "verifier" or "protocol_order").
## [ ] 3. Module constants: the alias `Item = tuple[Stage, Slot, tuple[int,
##        ...]]`, `_CRIT` (decisive 2, important 1, bookkeeping 0) and
##        `_SETTLED = {"sound", "not_applicable"}`.
## [ ] 4. `_answered(answers)`: the set of (slot_id, tuple(indices)) pairs.
## [ ] 5. `_open_items(protocol, spec, answers)`: walk ordered_slots(); skip
##        a slot unless routing.applies(name, spec, protocol) is True for
##        BOTH its stage's and its own applies_when. A `list` slot is one
##        item with indices (), open unless answered or every element of
##        index_combos has a value; any other slot gives one item per
##        combo of index_combos(spec, ir_path) that is neither answered nor
##        has_value in the spec (see the comment).
## [ ] 6. `_SHIFT_KEY_TO_IR_PATH`: copy the table exactly (it is checked
##        against the verifier). Then `_shift_key_to_path(key)`: any key
##        starting with "tau[" maps to "participants.agent_types", others are
##        looked up in the table (None if missing).
## [ ] 7. `_why(slot)`: why_it_matters of ALL_CONDITIONS[slot.why_we_ask],
##        or "" if absent. `_question(item)`: build a Question from the slot
##        and its indices, with why_we_ask=_why(slot).
## [ ] 8. `open_decisive_slots(spec, answers)`: sorted unique ids of the
##        decisive open items of current_protocol() (protocol.py: the
##        protocol file, read once per process).
## [ ] 9. `next_questions(protocol, spec, answers, *, max_questions=3)`:
##        a) open items, their protocol order, open decisive ids;
##        b) swept copy: apply_answer(..., None, "unknown", indices=idx) for
##           each open item whose slot allows unknown;
##        c) if service.validate(swept).valid is False, return the top items
##           by (criticality, order) with complete=False and
##           ranking_basis="protocol_order";
##        d) otherwise triage = service.minimal(swept); the unsettled
##           verdicts give shift paths (via _shift_key_to_path) and FM ids;
##        e) an inner `impact(item)`: 2 if the slot's ir_path equals or lies
##           under a shift path, 1 if slot.feeds meets an unsettled FM, else 0;
##          | key=lambda it: (-impact(it), -_CRIT[it[1].criticality], ...)
##        f) needed = items with impact > 0 or decisive; return the first
##           max_questions of them, complete=not needed, not_needed = the
##           rest as Questions, ranking_basis="verifier".
## [ ] 9b. (Extension) Structured answers: a Question for a `table`,
##        `dsl_expression` or `list` slot carries `value_schema`, the JSON
##        schema of its TE-IR field (paths.validation_type), so the agent
##        writes the schema's shape instead of guessing it. When the swept
##        copy is invalid, NextQuestions.spec_errors says why (step c), so
##        "no questions, not complete" is never a silent dead end.
## [ ] 9c. (Extension, short interview) `questions` holds only slots with
##        approach "ask"; `to_estimate` holds EVERY open slot with approach
##        "estimate" (with value_schema and `matters`: whether it can change
##        a verdict), so the agent proposes all estimates in one round.
## [ ] 10. Check: activate the 7.5 tests in
##        tests/platform_tests/test_platform_elicitation.py, then
##          | uv run pytest tests/platform_tests/test_platform_elicitation.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from functools import cache
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter
from verifier.paper import ALL_CONDITIONS

from te_platform import service
from te_platform.elicitation import routing
from te_platform.elicitation.answers import apply_answer
from te_platform.elicitation.paths import has_value, index_combos, validation_type
from te_platform.elicitation.protocol import Protocol, Slot, Stage, current_protocol


class Question(BaseModel):
    """One question for the interviewer to ask."""

    slot_id: str
    indices: list[int] = Field(default_factory=list)  # which token, for per-token slots
    intent: str
    why_we_ask: str  # text from verifier/paper.py, not from the YAML
    answer_type: str
    choices: list[str] = Field(default_factory=list)
    allow_unknown: bool
    criticality: str
    probes: list[str] = Field(default_factory=list)
    elicitation_method: str | None = None
    # The JSON schema of the answer's TE-IR field, for answers that are
    # objects or lists (table, dsl_expression, list): the value given to
    # elicit.record_answer.v1 must match it. None for the simple types.
    value_schema: dict[str, Any] | None = None
    # "ask": ask the designer; "estimate": propose a value (protocol Slot.approach).
    approach: Literal["ask", "estimate"] = "ask"
    # For estimates: whether the value can change a verdict (show these first).
    matters: bool = True


class NextQuestions(BaseModel):
    """What to ask next, and whether the interview is complete."""

    questions: list[Question]
    complete: bool
    open_decisive_slots: list[str]
    # Open questions that cannot change any verdict (header, step 5).
    not_needed: list[Question] = Field(default_factory=list)
    # Tells the agent (and tests) how the order was decided.
    ranking_basis: Literal["verifier", "protocol_order"]
    # Why the design does not validate yet, when it does not ("location:
    # message"). With no questions left and complete=False, these say what
    # is missing or contradictory, instead of a silent dead end.
    spec_errors: list[str] = Field(default_factory=list)
    # Every open slot the agent estimates instead of asking (approach
    # "estimate"), all at once: it proposes them in one round of forms.
    to_estimate: list[Question] = Field(default_factory=list)


## (stage, slot, indices) — one open item.
Item = tuple[Stage, Slot, tuple[int, ...]]
_CRIT = {"decisive": 2, "important": 1, "bookkeeping": 0}
_SETTLED = {"sound", "not_applicable"}


def _answered(answers: list[dict[str, Any]]) -> set[tuple[str, tuple[int, ...]]]:
    """Return the (slot_id, indices) pairs that have an answer, of any status."""
    return {(a["slot_id"], tuple(a.get("indices", []))) for a in answers}


def _open_items(
    protocol: Protocol, spec: dict[str, Any], answers: list[dict[str, Any]]
) -> list[Item]:
    """List the applicable questions that nothing answers yet, in protocol order."""
    done = _answered(answers)
    items: list[Item] = []
    for stage, slot in protocol.ordered_slots():
        if not (
            routing.applies(stage.applies_when, spec, protocol)
            and routing.applies(slot.applies_when, spec, protocol)
        ):
            continue
        combos = index_combos(spec, slot.ir_path)
        # A question is open only if it has no recorded answer AND the spec
        # holds no value for it yet. The second test matters when a spec
        # arrives WHOLE (saved from the form, uploaded YAML, or an evals
        # scenario): it already answers its own questions, so the session
        # can leave `eliciting` without re-asking what the spec says.
        if slot.answer_type == "list":
            # One question for all elements (e.g. the token names).
            filled = bool(combos) and all(has_value(spec, slot.ir_path, c) for c in combos)
            if (slot.id, ()) not in done and not filled:
                items.append((stage, slot, ()))
            continue
        # Per-item slots: one question per element that already exists
        # (no tokens yet -> no per-token questions yet).
        items += [
            (stage, slot, c)
            for c in combos
            if (slot.id, c) not in done and not has_value(spec, slot.ir_path, c)
        ]
    return items


## The verifier names the parameter of each threshold in `minimum_param_shift`
## (verifier/minimal.py, which takes it from each failure mode's
## NumericRecommendation(parameter=...) in verifier/failure_modes/*.py).
## Those names are short technical keys, NOT the paper's symbols: checked
## against the real verifier, they are e.g. "net_emission", "B_per_period",
## "gamma", "K", "N", "tau[<agent type>]". This table maps each to the TE-IR
## field a question must fill to move that threshold. The test
## test_every_verifier_shift_key_is_mapped (test_platform_elicitation.py)
## scans the failure modes for parameter=... and fails if a new key appears
## that is missing here, so the table cannot go stale silently.
_SHIFT_KEY_TO_IR_PATH: dict[str, str] = {
    "net_emission": "tokens[].emission_rules",  # FM1: emission minus burn
    "B_per_period": "tokens[].burn_rules",  # FM3: required burn
    "gamma": "governance.monitoring_capacity_gamma",  # FM4: monitoring capacity
    "K": "tokens[].offer_variety_K",  # FM4/FM5: offer variety
    "N": "participants.count_N",  # FM5: participant count
    "n_demote": "governance.rule_structure",  # FM6: decisions to decentralise
    "token_gini": "governance.token_balance_gini",  # FM6: secondary signal
    "agent_types[].role": "participants.agent_types",  # FM2: role mix
    # FM2: holding times are declared per agent type.
    "tau_bar": "participants.agent_types",
    "rho": "tokens[].burn_rules",  # FM3: burn/emission coverage ratio
    "supply_cap": "tokens[].emission_rules",  # FM1/FM3: hard cap on minting
    # FM1/FM3: cap on tokens outstanding (docs/proofs/outstanding_cap.md).
    "outstanding_supply_cap": "tokens[].outstanding_supply_cap",
    # FM4: active contributor rate, derived from the verification mechanism.
    "phi": "tokens[].contribution_verification",
    "Gamma": "governance.rule_structure",  # FM6: centralisation index
    # FM5: network connections.
    "average_degree": "participants.topology_params.average_degree",
}


def _shift_key_to_path(key: str) -> str | None:
    """Return the IR path for one minimum_param_shift key (None if unknown).

    "tau[manager]" (FM2: holding time of agent type "manager") is
    parameterised, so it is matched by its prefix; holding times are
    declared per agent type.
    """
    if key.startswith("tau["):
        return "participants.agent_types"
    return _SHIFT_KEY_TO_IR_PATH.get(key)


def _why(slot: Slot) -> str:
    """Return the paper's why-it-matters text for the slot's failure mode."""
    cond = ALL_CONDITIONS.get(slot.why_we_ask)
    return cond.why_it_matters if cond else ""


_STRUCTURED = {"table", "dsl_expression", "list"}


@cache
def _value_schema(ir_path: str, answer_type: str) -> dict[str, Any] | None:
    """Return the JSON schema an answer to this slot must match (built once per path)."""
    if answer_type not in _STRUCTURED:
        return None
    # A list slot is answered with one value per element ("tokens[].id").
    target = validation_type(ir_path)
    if target is None:
        return None
    schema = TypeAdapter(target).json_schema()
    return {"type": "array", "items": schema} if answer_type == "list" else schema


def _question(item: Item, *, with_schema: bool = True, matters: bool = True) -> Question:
    """Turn one open item into a Question (not_needed ones skip the schema)."""
    _, slot, idx = item
    return Question(
        slot_id=slot.id,
        indices=list(idx),
        intent=slot.intent,
        why_we_ask=_why(slot),
        answer_type=slot.answer_type,
        choices=slot.choices,
        allow_unknown=slot.allow_unknown,
        criticality=slot.criticality,
        probes=slot.probes,
        elicitation_method=slot.elicitation_method,
        value_schema=_value_schema(slot.ir_path, slot.answer_type) if with_schema else None,
        approach=slot.approach,
        matters=matters,
    )


def _asked(items: list[Item]) -> list[Item]:
    return [it for it in items if it[1].approach == "ask"]


def _estimated(items: list[Item], needed: list[Item]) -> list[Question]:
    """Every open estimate slot, the ones that can change a verdict first."""
    est = [it for it in items if it[1].approach == "estimate"]
    est.sort(key=lambda it: it not in needed)  # stable: keeps the ranking within each group
    return [_question(it, matters=it in needed) for it in est]


def open_decisive_slots(spec: dict[str, Any], answers: list[dict[str, Any]]) -> list[str]:
    """Return the ids of decisive slots that apply and are not answered yet.

    Used by db/repo.py (SessionFacts.open_decisive_slots), which feeds the
    `decisive_slots_resolved` precondition and the session state. The
    protocol is the configured one, read once per process.
    """
    items = _open_items(current_protocol(), spec, answers)
    return sorted({it[1].id for it in items if it[1].criticality == "decisive"})


def next_questions(
    protocol: Protocol,
    spec: dict[str, Any],
    answers: list[dict[str, Any]],
    *,
    max_questions: int = 3,
) -> NextQuestions:
    """Choose the next questions with the verifier (header, Algorithm)."""
    items = _open_items(protocol, spec, answers)
    order = {id(it): n for n, it in enumerate(items)}  # protocol order, for tie-breaks
    open_decisive = [it[1].id for it in items if it[1].criticality == "decisive"]

    # 2. swept copy: every open item as "unknown" (only where unknown is allowed).
    swept = spec
    for _, slot, idx in items:
        if slot.allow_unknown:
            swept = apply_answer(swept, slot, None, "unknown", indices=idx)

    # 3. verifier triage, if the swept copy is a valid TE-IR.
    checked = service.validate(swept)
    if not checked.valid:
        chosen = sorted(items, key=lambda it: (-_CRIT[it[1].criticality], order[id(it)]))
        return NextQuestions(
            questions=[_question(i) for i in _asked(chosen)[:max_questions]],
            to_estimate=_estimated(chosen, chosen),
            complete=False,
            open_decisive_slots=open_decisive,
            ranking_basis="protocol_order",
            spec_errors=[f"{e.location}: {e.message}" for e in checked.errors],
        )
    triage = service.minimal(swept)

    # 4. impact of each open item on unsettled verdicts.
    unsettled = [v for v in triage if v.get("structural_status") not in _SETTLED]
    shift_paths = {
        _shift_key_to_path(p) for v in unsettled for p in (v.get("minimum_param_shift") or {})
    }
    unsettled_fms = {v["failure_mode"] for v in unsettled}

    def impact(it: Item) -> int:
        slot = it[1]
        # 2: the slot fills (or lies under) a field whose value decides a
        #    threshold, e.g. slot "participants.count_N" for shift key "N";
        # 1: the slot feeds an undecided failure mode in a less direct way.
        if any(
            path and (slot.ir_path == path or slot.ir_path.startswith(path + "."))
            for path in shift_paths
        ):
            return 2
        # An optional field whose "unknown" is its absence (an outstanding
        # supply cap) leaves the swept copy unchanged, so the triage cannot
        # show that it matters through the failure modes it feeds: only a
        # shift key naming it (above) does.
        if slot.unknown_means_absent:
            return 0
        return 1 if unsettled_fms.intersection(slot.feeds) else 0

    ranked = sorted(items, key=lambda it: (-impact(it), -_CRIT[it[1].criticality], order[id(it)]))
    needed = [it for it in ranked if impact(it) > 0 or it[1].criticality == "decisive"]
    return NextQuestions(
        questions=[_question(i) for i in _asked(needed)[:max_questions]],
        to_estimate=_estimated(ranked, needed),
        complete=not needed,
        open_decisive_slots=open_decisive,
        # Estimate slots are all in to_estimate (matters=False when not needed).
        not_needed=[
            _question(it, with_schema=False)
            for it in ranked
            if it not in needed and it[1].approach == "ask"
        ],
        ranking_basis="verifier",
    )
