## =============================================================================
## te_platform/elicitation/paths.py — the dotted IR-path notation, in one place
## =============================================================================
## GUIDE STEP   7.1
## PURPOSE      Every slot of the protocol says where its answer goes in the
##              TE-IR with a dotted path, e.g. "participants.count_N" or
##              "tokens[].offer_variety_K". "[]" marks a list: the path then
##              means "that field of ONE element", and the caller says which
##              element with `indices` (one index per "[]", in order). This
##              file is the only code that understands the notation:
##                field_type(path)      what the schema expects there (the
##                                      field's type annotation), or None if
##                                      the path names no TE-IR field;
##                validation_type(path) the same with the field's constraints
##                                      (e.g. a rating between 1 and 5), for
##                                      checking a value;
##                index_combos(spec, p) every index tuple that exists in a
##                                      spec dict for p (e.g. [(0,), (1,)]
##                                      for "tokens[]..." with two tokens);
##                has_value / get_value read one value of a spec dict;
##                set_value             write one value (into a dict the
##                                      caller owns: answers.py copies first).
##              A part after a dict-typed field (e.g. "topology_params" is a
##              dict[str, NumberRange]) is a KEY of that dict:
##              "participants.topology_params.average_degree".
## USED BY      coverage.py (field_type: every ir_path exists), routing.py
##              (index_combos/get_value: rules read the spec), answers.py
##              (field_type/set_value), ranking.py (index_combos/has_value).
## DEPENDS ON   schema.TokenEconomy, pydantic. Pure: no I/O.
## WHY          Spec dicts are plain JSON (a partial spec is not yet a valid
##              TokenEconomy), so they are walked as dicts; the schema is
##              walked as Pydantic models. Keeping both walks here means one
##              notation, one implementation, one set of tests.
## ACTIVATE     Uncomment with guide 7.1; tests in
##              tests/platform_tests/test_platform_elicitation.py (7.1).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the public names exactly:
## the other elicitation files use them.
##
## Guide 7.1
## [ ] 1. Imports at the top: `types`, `typing`, `Annotated`, `Any`,
##        pydantic's BaseModel and FieldInfo (pydantic.fields), TokenEconomy
##        (schema), InvalidInput (te_platform.errors).
## [ ] 2. `strip_optional(annotation)` (public: answers.py uses it):
##        `X | None` -> X (only when exactly one type is left), anything
##        else unchanged.
##          | if typing.get_origin(a) in (typing.Union, types.UnionType):
## [ ] 3. `_resolve(path)`: start at TokenEconomy and walk the parts.
##        After a dict field, the part is a key: continue with the dict's
##        value type. Otherwise the current type must be a BaseModel with
##        that field (None if not); a part ending in "[]" must be a list
##        field and continues with the element type. Return (annotation,
##        FieldInfo of the last field, or None after a key or element).
##        Then `field_type(path)` (the annotation, Optional kept) and
##        `validation_type(path)` (Annotated[annotation, info]: the
##        FieldInfo carries constraints such as ge=1, le=5).
## [ ] 4. `index_combos(spec, path)`: [()] for a path without "[]";
##        otherwise walk the spec up to the last "[]" part and return one
##        tuple of indices per existing list element ([] if a list is
##        missing).
## [ ] 5. `get_value(spec, path, indices=())`: the value at path, None if
##        anything on the way is missing (a "[]" part takes the next index).
##        `has_value(...)`: get_value(...) is not None.
## [ ] 6. `set_value(doc, path, value, indices=())`: create missing dicts
##        on the way; a "[]" part must find its element already in the list
##        (InvalidInput otherwise: elements are created by "list" slots,
##        answers.py, never by accident); the last part receives value.
## [ ] 7. Check: activate the 7.1 tests (paths section) of
##        tests/platform_tests/test_platform_elicitation.py, then
##          | uv run pytest tests/platform_tests/test_platform_elicitation.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import types
import typing
from typing import Annotated, Any

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from schema import TokenEconomy

from te_platform.errors import InvalidInput


def strip_optional(annotation: Any) -> Any:
    """Turn `X | None` into X; leave every other annotation unchanged."""
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        inner = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(inner) == 1:
            return inner[0]
    return annotation


def _resolve(path: str) -> tuple[Any, FieldInfo | None] | None:
    """Walk the schema along `path`: (annotation, FieldInfo of the last field).

    The FieldInfo carries the field's constraints (e.g. 1 <= rating <= 5);
    it is None when the path ends in a dict key or a list element. Returns
    None when the path names no TE-IR field.
    """
    current: Any = TokenEconomy
    info: FieldInfo | None = None
    for part in path.split("."):
        model = strip_optional(current)
        if typing.get_origin(model) is dict:
            current = typing.get_args(model)[1]  # any key; continue with the value type
            info = None
            continue
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            return None
        info = model.model_fields.get(part.removesuffix("[]"))
        if info is None:
            return None
        current = info.annotation
        if part.endswith("[]"):
            inner = strip_optional(current)
            if typing.get_origin(inner) is not list:
                return None
            current = typing.get_args(inner)[0]  # one element of the list
            info = None
    return current, info


def field_type(path: str) -> Any | None:
    """Return the type annotation of the TE-IR field at `path`, or None.

    Example: "tokens[].offer_variety_K" -> NumberRange | None;
    "tokens[].function" -> list[TokenFunction]; "tokens.function" -> None
    (tokens is a list, so the path must say "tokens[]").
    """
    resolved = _resolve(path)
    return None if resolved is None else resolved[0]


def validation_type(path: str) -> Any | None:
    """Return what to validate a value at `path` against, constraints included.

    Annotated[int, Field(ge=1, le=5)] for an NFR rating: the annotation
    alone (int) would accept 9.
    """
    resolved = _resolve(path)
    if resolved is None:
        return None
    annotation, info = resolved
    return annotation if info is None else Annotated[annotation, info]


def index_combos(spec: dict[str, Any], path: str) -> list[tuple[int, ...]]:
    """Return every index tuple for which `spec` has the lists of `path`.

    "participants.count_N" -> [()]; "tokens[].offer_variety_K" with two
    tokens -> [(0,), (1,)]; with no `tokens` list yet -> [].
    """
    parts = path.split(".")
    last_list = max((n for n, p in enumerate(parts) if p.endswith("[]")), default=-1)
    combos: list[tuple[int, ...]] = []

    def walk(node: Any, n: int, acc: tuple[int, ...]) -> None:
        if n > last_list:
            combos.append(acc)
            return
        if not isinstance(node, dict):
            return
        part = parts[n]
        child = node.get(part.removesuffix("[]"))
        if not part.endswith("[]"):
            walk(child, n + 1, acc)
        elif isinstance(child, list):
            for i, element in enumerate(child):
                walk(element, n + 1, (*acc, i))

    walk(spec, 0, ())
    return combos


def get_value(spec: dict[str, Any], path: str, indices: tuple[int, ...] = ()) -> Any:
    """Return the value at `path` (None when anything on the way is missing)."""
    idx = list(indices)
    node: Any = spec
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part.removesuffix("[]"))
        if part.endswith("[]"):
            if not idx or not isinstance(node, list) or idx[0] >= len(node):
                return None
            node = node[idx.pop(0)]
    return node


def has_value(spec: dict[str, Any], path: str, indices: tuple[int, ...] = ()) -> bool:
    """Tell whether the spec holds a non-null value at `path`.

    A missing key, a missing list element or an explicit null all mean
    "no value yet".
    """
    return get_value(spec, path, indices) is not None


def set_value(doc: dict[str, Any], path: str, value: Any, indices: tuple[int, ...] = ()) -> None:
    """Set the value at `path` in `doc` (modified in place).

    Missing intermediate objects are created, so answers can arrive in any
    order; list elements are not: writing into the third token of a spec
    with two tokens is an error, not a silently created empty token.
    """
    parts = path.split(".")
    idx = list(indices)
    node: Any = doc
    for n, part in enumerate(parts):
        key = part.removesuffix("[]")
        last = n == len(parts) - 1
        if not part.endswith("[]"):
            if last:
                node[key] = value
            else:
                if not isinstance(node.get(key), dict):
                    node[key] = {}
                node = node[key]
            continue
        lst = node.get(key)
        if not idx:
            raise InvalidInput(f"Path {path} needs an index for '{key}[]'.")
        i = idx.pop(0)
        if not isinstance(lst, list) or i >= len(lst):
            raise InvalidInput(f"There is no element {i} in '{key}' yet; add it first.")
        if last:
            lst[i] = value
        else:
            node = lst[i]
