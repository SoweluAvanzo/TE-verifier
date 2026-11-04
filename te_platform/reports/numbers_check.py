## =============================================================================
## te_platform/reports/numbers_check.py — no invented numbers in the narrative
## =============================================================================
## GUIDE STEP   10.2
## PURPOSE      The agent writes the narrative sections of a report (executive
##              summary, plain-language explanation). This file checks that
##              every number in that text also appears in the verification /
##              simulation results the report is based on:
##              - collect_numbers(results) -> every number found in the data;
##              - extract_numbers(text)    -> every number written in the text;
##              - check_narrative(...)     -> a list of problems (empty = OK);
##              - ensure_supported(...)    -> raises InvalidInput if there is one.
## USED BY      reports/render.py (ensure_supported: refuses to render),
##              tools/report_render_pdf.py (returns the problems to the agent
##              as a VALIDATION_ERROR so it can rewrite the text).
## DEPENDS ON   Python standard library (re, math) and errors.py (InvalidInput).
##              Pure functions: no I/O.
## WHY          Architecture P1: "the LLM never computes a verdict or a
##              number". A report is something people rely on; a plausible
##              but invented figure is the most dangerous kind of error, and
##              this check catches it mechanically.
## LIMITS       It checks numbers, not meaning: "FM3 fails" vs "FM3 passes"
##              is not caught here (the verdict table, filled from data, sits
##              next to the narrative for that reason). Small integers used as
##              ordinary words ("two failure modes", "FM1".."FM6", years in
##              citations) are allowed through ALWAYS_ALLOWED / the regex.
## ACTIVATE     Uncomment; activate the hypothesis property tests in
##              test_platform_reports.py at the same time (they are the
##              specification of the parsing rules).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" at the end. Lines starting with "|" are
## short illustrations, not the full code. Keep the public names
## collect_numbers, extract_numbers, check_narrative, ensure_supported and
## ALWAYS_ALLOWED exactly: render.py, tools/report_render_pdf.py and the
## tests use them.
##
## Guide 10.2
## [ ] 1. Imports at the top: math, re, Iterable (collections.abc), Any,
##        and InvalidInput (errors.py).
## [ ] 2. `ALWAYS_ALLOWED: frozenset[float]` holding 0.0 to 6.0 and 100.0.
## [ ] 3. `collect_numbers(obj: Any) -> set[float]`: an inner `walk` that
##        recurses into dicts (values) and lists/tuples; skips bool FIRST
##        (True == 1 in Python); adds every finite int/float, plus x * 100
##        when 0 <= |x| <= 1 (so 0.27 allows "27%"); and for strings adds
##        extract_numbers(text).
## [ ] 4. The regex `_NUMBER`. Build it piece by piece from the table in the
##        SOLUTION's `##` note; it starts with the look-behind that skips
##        "FM3" and "v1.2":
##          | (?<![\w.])[-\u2212]?(?:\d{1,3}(?:,\d{3})+|\d+)...
##        and `_YEAR_IN_PARENS` for "(1990)" style citation years.
## [ ] 5. `extract_numbers(text: str) -> list[float]`: replace years in
##        parentheses with a space, then for each _NUMBER match remove the
##        commas, turn the Unicode minus "\u2212" into "-", and float() it
##        (skip ValueError).
## [ ] 6. `_decimals_written(value: float) -> int`: the number of decimals in
##        repr(value) (0 when there is no "." or there is an "e").
## [ ] 7. `_matches(written, allowed, rel_tol) -> bool`: True if some allowed
##        number is math.isclose with rel_tol, OR within half a unit of the
##        last written decimal (0.27 matches 0.2731).
## [ ] 8. `check_narrative(narrative_sections, allowed, rel_tol=0.02) ->
##        list[str]`: pool = allowed plus ALWAYS_ALLOWED; one message per
##        unmatched number, naming the section and the number:
##          | f"section {section!r}: the number {n:g} "
##          | "does not appear in the results"
## [ ] 9. `ensure_supported(narrative_sections, *results) -> None`: the
##        union of collect_numbers over all results; if check_narrative
##        reports problems, raise InvalidInput with them joined by "; ".
##        (One call for the renderer; the agent's tool uses check_narrative,
##        to send the list back.)
## [ ] 10. Check: activate section 2 (the hypothesis property tests) of
##        tests/platform_tests/test_platform_reports.py, then
##          | uv run pytest tests/platform_tests/test_platform_reports.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import math
import re
from collections.abc import Iterable
from typing import Any

from te_platform.errors import InvalidInput

## --- Which numbers are always fine ------------------------------------------------
## Counting words and identifiers that are not "results": failure mode numbers
## 1..6, and 0/100 (as in "0%" / "100%" phrasing). Extend with care: every
## entry is a number the check will never question.
ALWAYS_ALLOWED: frozenset[float] = frozenset({0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 100.0})


## --- Collecting numbers from the results -------------------------------------------
def collect_numbers(obj: Any) -> set[float]:
    """Walk any nested structure of dicts/lists and collect every number.

    bool is excluded on purpose: in Python True == 1, and we do not want
    every `true` flag in the data to "allow" the number 1.
    Percentages are also added multiplied by 100: the data says 0.27,
    the narrative may correctly say 27%.
    """
    found: set[float] = set()

    def walk(x: Any) -> None:
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)) and math.isfinite(x):
            found.add(float(x))
            if 0 <= abs(x) <= 1:
                found.add(float(x) * 100.0)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            # Numbers inside strings of the data (e.g. a formal condition
            # "N >= 2Kd + 1 = 41") are legitimate sources too.
            found.update(extract_numbers(x))

    walk(obj)
    return found


## --- Extracting numbers from text -----------------------------------------------------
## The regular expression, piece by piece:
##   (?<![\w.])        not preceded by a letter/digit/dot: skip "FM3", "v1.2"
##                     and the middle of longer tokens
##   [-\u2212]?        optional minus sign, ASCII "-" or the Unicode minus
##                     sign U+2212, written as the escape \u2212 (it looks
##                     exactly like "-", so the code never contains it raw)
##   \d{1,3}(?:,\d{3})+  thousands with commas: 1,000 or 12,345,678
##   |\d+              or plain digits
##   (?:\.\d+)?        optional decimals: 0.27
##   (?:[eE][-+]?\d+)? optional exponent: 1e6, 2.5E-3
## Symbols around a number (%, ≥, ≤, ~) don't change its value, so they are
## simply not part of the match.
_NUMBER = re.compile(r"(?<![\w.])[-\u2212]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
## Years in citations ("Ostrom (1990)") are not results; skip 4-digit
## integers between 1900 and 2100 that are directly inside parentheses.
_YEAR_IN_PARENS = re.compile(r"\((?:19|20)\d{2}[a-z]?\)")


def extract_numbers(text: str) -> list[float]:
    """Return every number written in `text`, in order (see the regex above)."""
    cleaned = _YEAR_IN_PARENS.sub(" ", text)
    out: list[float] = []
    for match in _NUMBER.finditer(cleaned):
        token = match.group(0).replace(",", "").replace("\u2212", "-")
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


## --- Matching, with rounding -----------------------------------------------------------
def _decimals_written(value: float) -> int:
    """Return how many decimals a written number has (for the rounding tolerance).

    Computed from repr(), which is enough for the short numbers people write.
    """
    s = repr(value)
    return len(s.split(".")[1]) if "." in s and "e" not in s else 0


def _matches(written: float, allowed: Iterable[float], rel_tol: float) -> bool:
    """Return True if `written` is (a rounded form of) some allowed number.

    Two tolerances, and either suffices:
    - relative: |a-b| <= rel_tol * max(|a|,|b|), e.g. 2 % for "about";
    - rounding: the writer rounded to the decimals shown, so 0.27 matches
      0.2731 (|diff| <= half a unit of the last written decimal).
    """
    half_unit = 0.5 * 10 ** (-_decimals_written(written))
    for a in allowed:
        if math.isclose(written, a, rel_tol=rel_tol) or abs(written - a) <= half_unit:
            return True
    return False


def check_narrative(
    narrative_sections: dict[str, str], allowed: set[float], rel_tol: float = 0.02
) -> list[str]:
    """Return one human-readable problem per number not supported by the data.

    The messages name the section and the number, so the agent can fix the
    exact sentence (tools/report_render_pdf.py sends them back to it).
    """
    pool = set(allowed) | set(ALWAYS_ALLOWED)
    problems: list[str] = []
    for section, text in narrative_sections.items():
        problems.extend(
            f"section {section!r}: the number {n:g} does not appear in the results"
            for n in extract_numbers(text)
            if not _matches(n, pool, rel_tol)
        )
    return problems


def ensure_supported(narrative_sections: dict[str, str], *results: Any) -> None:
    """Raise InvalidInput if the narrative has a number found in none of `results`."""
    allowed: set[float] = set()
    for r in results:
        allowed |= collect_numbers(r)
    problems = check_narrative(narrative_sections, allowed)
    if problems:
        raise InvalidInput(
            "Narrative contains numbers not found in the results: " + "; ".join(problems)
        )
