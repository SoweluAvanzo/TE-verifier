## =============================================================================
## te_platform/elicitation/answers.py — write one answer into a spec
## =============================================================================
## GUIDE STEP   7.4
## PURPOSE      apply_answer(spec, slot, value, status, indices) returns a NEW
##              spec dict with the answer written at the slot's ir_path. It
##              never modifies the input (spec versions are append-only).
##              How each status is written:
##                committed -> the user's value;
##                unknown   -> what the slot says "I don't know" means: its
##                             `unknown_range` (an interval the verifier
##                             SWEEPS) or its `unknown_value` (e.g.
##                             "unspecified");
##                default   -> the slot's archetype default.
##              In all three cases the value is first shaped by the slot's
##              answer_type (protocol.py, ANSWER TYPES) AND by the type of
##              the TE-IR field at ir_path (paths.field_type), then checked
##              against that field with Pydantic: a value of the wrong shape
##              is refused (InvalidInput) instead of being stored in a spec
##              that can never validate.
## SHAPES       number + NumberRange field -> {"min": v, "max": v}
##              number + int field (NFR ratings) -> the int (refused if not
##                whole)
##              range + NumberRange field -> {"min": a, "max": b} (a <= b)
##              enum + list field (tokens[].function) -> [choice] (or the
##                list of choices given)
##              list ("tokens[].id" answered ["MKR", "DAI"]) -> that field
##                in each element; the list gets exactly one element per
##                value (new elements are created, extra ones removed)
##              text, table, dsl_expression -> the value as given
## HOW THE SCHEMA REPRESENTS UNCERTAINTY
##              In schema/te_ir.py, uncertain numbers are `NumberRange`
##              ({"min": a, "max": b}; min == max is a known point value).
##              The verifier checks the whole interval, i.e. it sweeps it.
##              Several enums also have an "unspecified" member (e.g.
##              AsymptoticFamily, ContributionVerification) that the verifier
##              treats as "any plausible value". So an "unknown" answer is a
##              wide range or "unspecified" — no special marker is needed.
## USED BY      tools/elicit_record_answer.py; ranking.py (builds a fully
##              swept copy of a partial spec).
## DEPENDS ON   protocol.py (Slot), paths.py, errors.py (InvalidInput),
##              pydantic (TypeAdapter). Pure: no I/O.
## WHY          Architecture P4: "I don't know" is a first-class answer and is
##              never replaced by a guess.
## ACTIVATE     Uncomment; tests: point answer -> {min: v, max: v}; unknown ->
##              the slot's range; per-token "[]" paths with indices; shapes
##              checked against the schema; the input dict is unchanged.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep `apply_answer` and its
## signature exactly: ranking.py and tools/elicit_record_answer.py call it.
## Activate protocol.py and paths.py first.
##
## Guide 7.4
## [ ] 1. Imports at the top: `copy`, `typing`, `cache` (functools), `Any`
##        and `Literal`, pydantic's TypeAdapter and ValidationError,
##        NumberRange (schema), field_type, set_value, strip_optional and
##        validation_type (paths.py), Slot (protocol.py), InvalidInput.
## [ ] 2. `_adapter(ir_path)` (@cache): a TypeAdapter for
##        validation_type(ir_path) (constraints included); InvalidInput if
##        the path is not a field.
## [ ] 3. `_check(slot, value)`: validate value with the adapter; on
##        ValidationError raise InvalidInput naming the slot and the first
##        error message. Return value unchanged (the spec stays plain JSON).
## [ ] 4. `_number(value)`: a float; refuse bool and non-numbers.
## [ ] 5. `_shaped(slot, value)`: the SHAPES table of the header for one
##        element (everything except list slots). A NumberRange field gets
##        {"min", "max"}; an int field an int; an enum answer for a list
##        field a list; the enum value must be in slot.choices.
##          | target = strip_optional(field_type(slot.ir_path))
## [ ] 6. `_set_column(doc, slot, values)`: for a list slot ("a.b[].c"),
##        walk/create "a.b" as dicts, resize the list to len(values)
##        (new elements are {}), set "c" in each element; every value is
##        checked against the field first.
## [ ] 7. `apply_answer(spec, slot, value, status, *, indices=())`:
##        pick the raw value by status (committed: value; unknown: refused
##        if not slot.allow_unknown, else unknown_value; default: refused if
##        slot.default is None, else the default). Deep-copy the spec. A
##        list slot (indices must be empty) goes through _set_column; any
##        other slot through set_value(new, ir_path, stored, indices) with
##        stored = _check(slot, ...) of {"min", "max"} from unknown_range
##        (unknown answers that have one) or of _shaped(slot, raw).
##        Return the copy.
## [ ] 8. Check: activate the 7.4 tests in
##        tests/platform_tests/test_platform_elicitation.py, then
##          | uv run pytest tests/platform_tests/test_platform_elicitation.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import copy
import typing
from functools import cache
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError
from schema import NumberRange

from te_platform.elicitation.paths import (
    field_type,
    set_value,
    strip_optional,
    validation_type,
)
from te_platform.elicitation.protocol import Slot
from te_platform.errors import InvalidInput


@cache
def _adapter(ir_path: str) -> TypeAdapter[Any]:
    """Return a validator for the TE-IR field at `ir_path` (built once per path)."""
    annotation = validation_type(ir_path)
    if annotation is None:
        raise InvalidInput(f"{ir_path} is not a TE-IR field (protocol error).")
    return TypeAdapter(annotation)


def _check(slot: Slot, value: Any, ir_path: str | None = None) -> Any:
    """Refuse a value the schema would not accept at the slot's field."""
    try:
        _adapter(ir_path or slot.ir_path).validate_python(value)
    except ValidationError as exc:
        first = exc.errors()[0]["msg"]
        raise InvalidInput(f"The answer to {slot.id} does not fit the design: {first}") from exc
    return value


def _number(value: Any) -> float:
    """Read one number (bool is refused: True is not 1 here)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidInput("Give a number.")
    return float(value)


def _shaped(slot: Slot, value: Any) -> Any:
    """Shape one answer for the slot's field (header, SHAPES)."""
    target = strip_optional(field_type(slot.ir_path))
    if slot.answer_type == "number":
        v = _number(value)
        if target is NumberRange:
            return {"min": v, "max": v}  # a known value is a point range
        if target is int:
            if not v.is_integer():
                raise InvalidInput("Give a whole number.")
            return int(v)
        return v
    if slot.answer_type == "range":
        if not isinstance(value, dict) or not {"min", "max"} <= value.keys():
            raise InvalidInput('Give a range as {"min": ..., "max": ...}.')
        lo, hi = _number(value["min"]), _number(value["max"])
        if lo > hi:
            raise InvalidInput("The lower bound is above the upper bound.")
        return {"min": lo, "max": hi}
    if slot.answer_type == "enum":
        chosen = value if isinstance(value, list) else [value]
        wrong = [c for c in chosen if c not in slot.choices]
        if wrong:
            raise InvalidInput(f"Choose from {slot.choices}.")
        # A multi-select field (e.g. tokens[].function) stores a list.
        return chosen if typing.get_origin(target) is list else value
    # text, table and dsl_expression are already in the schema's shape.
    return value


def _set_column(doc: dict[str, Any], slot: Slot, values: Any) -> None:
    """Write a list slot: field `c` of every element of list `a.b` ("a.b[].c")."""
    if not isinstance(values, list) or not values:
        raise InvalidInput(f"Answer {slot.id} with a list of values, one per item.")
    head, _, leaf = slot.ir_path.rpartition("[].")
    element_path = head + "[]." + leaf
    checked = [_check(slot, v, element_path) for v in values]
    node: Any = doc
    *parents, list_key = head.split(".")
    for key in parents:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    old = node.get(list_key)
    elements = old if isinstance(old, list) else []
    # One element per value: keep what the existing ones already hold.
    resized = [elements[i] if i < len(elements) else {} for i in range(len(checked))]
    for element, value in zip(resized, checked, strict=True):
        element[leaf] = value
    node[list_key] = resized


def apply_answer(
    spec: dict[str, Any],
    slot: Slot,
    value: Any,
    status: Literal["committed", "estimated", "unknown", "default"],
    *,
    indices: tuple[int, ...] = (),
) -> dict[str, Any]:
    """Return a copy of `spec` with the answer to `slot` written into it."""
    swept: dict[str, float] | None = None
    # An accepted estimate is written like a given value; the stored
    # answer keeps the status, so reports can say which inputs were estimated.
    if status in ("committed", "estimated"):
        raw = value
    elif status == "unknown":
        if not slot.allow_unknown:
            raise InvalidInput(f"Slot {slot.id} needs an answer; offer examples or a range.")
        raw = slot.unknown_value
        if slot.unknown_range is not None:
            swept = {"min": slot.unknown_range[0], "max": slot.unknown_range[1]}
    else:
        if slot.default is None:
            raise InvalidInput(f"Slot {slot.id} has no default; ask the user.")
        raw = slot.default
    new = copy.deepcopy(spec)  # never mutate the caller's spec
    if status == "unknown" and slot.unknown_means_absent:
        # The field stays empty: its absence is the honest unknown (protocol.py).
        set_value(new, slot.ir_path, _check(slot, None), indices)
        return new
    if slot.answer_type == "list":
        if indices:
            raise InvalidInput(f"Slot {slot.id} is answered for all items at once (no indices).")
        _set_column(new, slot, raw)
    else:
        # An unknown number is the whole interval to sweep, not one value.
        stored = swept if swept is not None else _shaped(slot, raw)
        set_value(new, slot.ir_path, _check(slot, stored), indices)
    return new
