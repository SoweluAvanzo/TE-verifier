## =============================================================================
## te_platform/elicitation/protocol.py — typed view of policy/elicitation_protocol.yaml
## =============================================================================
## GUIDE STEP   7.1
## PURPOSE      Pydantic models mirroring the protocol file (Protocol -> Stage
##              -> Slot), load_protocol(), which reads and validates it, and
##              current_protocol(), the configured file read once per process.
##              A SLOT is one piece of information the interview must collect
##              (e.g. the number of participants); a STAGE is a group of slots
##              asked together, following docs/specification-flow.md.
## ANSWER TYPES How the answer to a slot looks (answers.py turns it into the
##              shape the TE-IR field at ir_path needs, and checks it against
##              the schema):
##                enum            one of `choices` (or a list of them when the
##                                field is a list: a multi-select, e.g.
##                                tokens[].function);
##                number          one number: a point range {min: v, max: v}
##                                for a NumberRange field, an int for an int
##                                field (the NFR ratings);
##                range           {"min": a, "max": b} for a NumberRange field;
##                text            a short free text (a name);
##                list            one value per element of the "[]" list in
##                                ir_path, e.g. "tokens[].id" answered with
##                                ["MKR", "DAI"]: this is how tokens come into
##                                existence (the TE-IR has no token-count
##                                field: the count is the length of `tokens`);
##                table           a structured value in the schema's own JSON
##                                shape (rows such as governance.rule_structure
##                                or participants.agent_types, or a small
##                                object such as participants.growth_g);
##                dsl_expression  emission/burn rules in the schema's shape;
##                                their functions may use the expression DSL
##                                (docs/dsl-reference.md). One of the three
##                                LLM translations allowed by CLAUDE.md.
## UNKNOWN      A slot with allow_unknown: true must say what "I don't know"
##              is written as: `unknown_range` (number/range slots: the
##              interval the verifier sweeps) or `unknown_value` (any type: a
##              schema value the verifier treats as unknown, e.g.
##              "unspecified", or a rule whose class is "unspecified").
##              Slots whose field has no honest "unknown" representation set
##              allow_unknown: false; the interviewer then helps the user to
##              commit (examples, ranges, probes).
## USED BY      ranking.py, answers.py, coverage.py, routing.py (slot ids),
##              tools/elicit_next_questions.py and tools/elicit_record_answer.py
##              (current_protocol), mcp_server/resources.py (publishes the
##              file).
## DEPENDS ON   pydantic, PyYAML, config.py (policy_dir).
## WHY          Same reasoning as registry/policy.py (D3, D16): the protocol is
##              data reviewed by domain experts; extra="forbid" turns a typo in
##              the YAML into a startup error instead of a silently skipped
##              question.
## ACTIVATE     Uncomment; test: the real file loads, and a file with an
##              unknown key fails (test_platform_elicitation.py).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep every class, field and
## function name exactly as written here: ranking.py, answers.py, coverage.py
## and the elicitation tools use them.
##
## Guide 7.1
## [ ] 1. Imports at the top: `lru_cache` (functools), `Path` (pathlib),
##        `Any` and `Literal` (typing), `yaml`, from pydantic: BaseModel,
##        ConfigDict, Field, model_validator; `get_settings` (config.py).
## [ ] 2. A private base class `_Strict(BaseModel)` whose only content is
##          | model_config = ConfigDict(extra="forbid", frozen=True)
##        Every model below inherits from it, so an unknown YAML key fails.
## [ ] 3. `AnswerType`: a Literal of the seven answer types of the header
##        (enum, number, range, text, list, table, dsl_expression).
## [ ] 4. `class Slot(_Strict)` with these fields, in this order (the
##        SOLUTION's comments explain each one): id, ir_path (str); feeds
##        (list[str], default empty); criticality (Literal "decisive",
##        "important", "bookkeeping"); answer_type (AnswerType); choices
##        (list[str], default empty); allow_unknown (bool = True); intent,
##        why_we_ask (str); probes (list[str], default empty);
##        elicitation_method (str | None = None); validation (list[str],
##        default empty); applies_when (str | None = None); unknown_range
##        (tuple[float, float] | None); unknown_value (Any | None); default
##        (Any | None). Use Field(default_factory=list) for lists.
## [ ] 5. Inside Slot, an "after" validator `_consistent` raising
##        ValueError when: allow_unknown is true but unknown_range and
##        unknown_value are both None; unknown_range is set on a slot that
##        is not number/range; an enum slot has no choices; a list slot's
##        ir_path is not "<path>[].<field>" with exactly one "[]".
## [ ] 6. `class Stage(_Strict)`: id, title (str), order (int), applies_when
##        (str | None = None), slots (list[Slot]).
## [ ] 7. `class Protocol(_Strict)`: protocol, version (str), stages
##        (list[Stage]), plus two methods:
##        - ordered_slots(): list of (stage, slot) pairs, stages sorted by
##          `order`, slots in file order;
##        - slot(slot_id): the Slot with that id, or None.
## [ ] 8. Inside Protocol, an "after" validator `_unique_ids` that raises
##        ValueError listing any slot id used twice.
## [ ] 9. `load_protocol(path: Path) -> Protocol`: open the file as UTF-8,
##        yaml.safe_load it and return Protocol.model_validate(...).
## [ ] 10. `current_protocol() -> Protocol`, decorated with
##        @lru_cache(maxsize=1): load_protocol(get_settings().policy_dir /
##        "elicitation_protocol.yaml"). The tools use it instead of reading
##        the file on every call.
## [ ] 10b. (Extension, short interview) Slot field `approach`: "ask" (the
##        designer is asked) or "estimate" (the agent proposes a value from
##        what it already knows, shown pre-filled in a form the designer can
##        change). Default "ask".
## [ ] 11. Check: activate the 7.1 tests of
##        tests/platform_tests/test_platform_elicitation.py (real protocol
##        loads, unknown key rejected, a slot's meaning of "unknown" and
##        shape are checked, paths), then
##          | uv run pytest tests/platform_tests/test_platform_elicitation.py -q
##          | uv run mypy te_platform
##        test_real_protocol_loads needs policy/elicitation_protocol.yaml
##        uncommented too.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from te_platform.config import get_settings

## The seven answer types of the header (ANSWER TYPES).
AnswerType = Literal["enum", "number", "range", "text", "list", "table", "dsl_expression"]


class _Strict(BaseModel):
    """Reject unknown keys; loaded objects are read-only."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Slot(_Strict):
    """One question's worth of information (architecture §4.1)."""

    # Unique id across the whole protocol, e.g. "participants.N".
    id: str
    # Where the answer goes in the TE-IR, as a dotted path. "[]" marks a list
    # (e.g. "tokens[].offer_variety_K" = that field of one token); the
    # caller says which element via `indices` (paths.py). The same notation
    # is used by verifier/paper.py (PaperVariable.elicitation_field).
    ir_path: str
    # Failure modes that consume this value, e.g. ["FM4", "FM5"]. Used by the
    # ranking (an open slot feeding an undecided failure mode matters).
    feeds: list[str] = Field(default_factory=list)
    # decisive: can decide a verdict on its own; important: refines one;
    # bookkeeping: needed for a complete spec but rarely changes a verdict.
    criticality: Literal["decisive", "important", "bookkeeping"]
    answer_type: AnswerType
    # For enum slots: the allowed values (must match the schema's Enum;
    # answers.py checks every answer against the schema anyway).
    choices: list[str] = Field(default_factory=list)
    allow_unknown: bool = True
    # What the question is trying to learn, in plain words. The agent turns
    # this into a natural question; it is NOT read out verbatim.
    intent: str
    # Key into verifier/paper.py ALL_CONDITIONS (e.g. "FM5"): the "why we
    # ask" text comes from there (why_it_matters), never copied here, so the
    # paper remains the single source (CLAUDE.md: the paper wins).
    why_we_ask: str
    # Follow-up questions for vague answers (method: architecture §4.2).
    probes: list[str] = Field(default_factory=list)
    # How to ask for uncertain numbers, e.g. "quartile_range" (ask for a
    # plausible low, high and middle value, O'Hagan et al. 2006).
    elicitation_method: str | None = None
    # Names of coherence rules (verifier/elicitation.py) this slot takes part
    # in; informative, shown to reviewers.
    validation: list[str] = Field(default_factory=list)
    # Name of a routing rule in routing.py; None = always applies.
    applies_when: str | None = None
    # What an "unknown" answer becomes (header, UNKNOWN): the [min, max] the
    # verifier sweeps, or a value of the field's own shape.
    unknown_range: tuple[float, float] | None = None
    unknown_value: Any | None = None
    # The archetype default, used only when the user explicitly accepts it.
    default: Any | None = None
    # How the agent fills it (short interview): "ask" = a question to the
    # designer; "estimate" = the agent proposes a value from what it knows,
    # shown pre-filled in a form the designer can change with a click.
    approach: Literal["ask", "estimate"] = "ask"
    # For an optional field whose absence is itself the honest "unknown"
    # (no outstanding supply cap declared = no cap, the conservative case):
    # an "unknown" answer leaves the field empty (null) instead of writing
    # unknown_value or sweeping unknown_range.
    unknown_means_absent: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> "Slot":
        # If "I don't know" is allowed, the protocol must say what it means;
        # otherwise answers.py could not build a sweepable spec.
        if (
            self.allow_unknown
            and not self.unknown_means_absent
            and self.unknown_range is None
            and self.unknown_value is None
        ):
            raise ValueError(f"slot {self.id}: allow_unknown needs unknown_range or unknown_value")
        if self.unknown_range is not None and self.answer_type not in ("number", "range"):
            raise ValueError(f"slot {self.id}: unknown_range is only for number/range slots")
        if self.answer_type == "enum" and not self.choices:
            raise ValueError(f"slot {self.id}: an enum slot needs choices")
        if self.answer_type == "list":
            head, _, field = self.ir_path.rpartition("[].")
            if not head or "[]" in head or "[]" in field or "." in field:
                raise ValueError(
                    f"slot {self.id}: a list slot's ir_path must look like "
                    "'<path>[].<field>' with one '[]'"
                )
        return self


class Stage(_Strict):
    """A group of slots asked together (one stage of the specification flow)."""

    id: str  # e.g. "S8_participants"
    title: str
    # The stage number in docs/specification-flow.md; gives the default
    # order of questions (ranking.py uses it as the last tie-breaker).
    order: int
    applies_when: str | None = None
    slots: list[Slot]


class Protocol(_Strict):
    """The whole protocol file."""

    protocol: str  # the protocol's name
    version: str  # recorded in every session (architecture P5)
    stages: list[Stage]

    def ordered_slots(self) -> list[tuple[Stage, Slot]]:
        """Return every slot with its stage, in interview order."""
        stages = sorted(self.stages, key=lambda s: s.order)
        return [(st, sl) for st in stages for sl in st.slots]

    def slot(self, slot_id: str) -> Slot | None:
        """Return the slot with this id, or None."""
        return next((sl for _, sl in self.ordered_slots() if sl.id == slot_id), None)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Protocol":
        ids = [sl.id for _, sl in self.ordered_slots()]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate slot ids: {sorted(dupes)}")
        return self


def load_protocol(path: Path) -> Protocol:
    """Read and validate a protocol file."""
    with path.open(encoding="utf-8") as fh:
        return Protocol.model_validate(yaml.safe_load(fh))


@lru_cache(maxsize=1)
def current_protocol() -> Protocol:
    """Return the configured protocol file, read ONCE per process (lru_cache).

    It is read-only configuration: changing it means deploying a new
    version, which restarts the process. Both elicitation tools and
    ranking.py use it, so every caller sees the same protocol object.
    """
    return load_protocol(get_settings().policy_dir / "elicitation_protocol.yaml")
