## =============================================================================
## tests/platform_tests/test_platform_hashing.py — property tests for te_platform/hashing.py
## =============================================================================
## GUIDE STEP   1.2 (activate together with hashing.py)
## PURPOSE      These tests ARE the specification of hashing.py:
##              - equal data gives equal bytes/hashes, whatever the key order;
##              - any change of a value changes the hash;
##              - NaN is rejected (it would make hashes unstable);
##              - verification_ref cannot collide by shifting text between parts.
## DEPENDS ON   te_platform/hashing.py, hypothesis (dev dependency, see
##              te_platform/pyproject_additions.toml). Hypothesis GENERATES
##              hundreds of random inputs per test and, when one fails, shrinks
##              it to the smallest failing example.
## WHY          Architecture D5: content addressing is only sound if these
##              properties hold for ALL inputs, not just a few hand-picked ones.
## ACTIVATE     Uncomment with hashing.py; install the dev extra first.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
##
## Guide 1.2
## [ ] 1. Imports: `math`, `random`, `pytest`, `given` and `strategies as
##        st` from hypothesis, and `hashing` from te_platform.
## [ ] 2. Two module-level strategies (recipes hypothesis uses to build
##        random data): `json_scalars` (none, booleans, integers, text,
##        floats without NaN/infinity) and `json_data`, made with
##        st.recursive from json_scalars, nesting lists and dicts.
## [ ] 3. test_hash_is_independent_of_key_order: @given a non-empty dict of
##        text -> json_data; shuffle its items with random.shuffle, rebuild
##        a dict, and assert both dicts have the same spec_hash.
## [ ] 4. test_hash_changes_when_any_value_changes: @given a dict of
##        text -> integers; add 1 to the first key's value; the spec_hash
##        must differ.
## [ ] 5. test_canonical_json_is_deterministic: @given(json_data), two
##        canonical_json calls give equal bytes.
## [ ] 6. test_nan_is_rejected: canonical_json({"x": math.nan}) raises
##        ValueError.
## [ ] 7. test_verification_ref_parts_cannot_be_shifted: the refs of
##        ("ab", "c", "d") and ("a", "bc", "d") differ.
## [ ] 8. test_prefixes_identify_the_kind_of_hash:
##          | assert hashing.spec_hash({}).startswith("spec:")
##        and likewise "cfg:" for config_hash(None), "vref:" for
##        verification_ref("a", "b", "c").
## [ ] 9. Check (install the dev extra first, header ACTIVATE):
##          | uv run pytest tests/platform_tests/test_platform_hashing.py -q
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import math
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from te_platform import hashing


## A strategy describes how hypothesis builds random values. Here: JSON-like
## nested data (what specs are made of). Floats exclude NaN/infinity, which
## canonical_json rejects on purpose (tested separately below).
json_scalars = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.text()
    | st.floats(allow_nan=False, allow_infinity=False)
)
json_data = st.recursive(
    json_scalars,
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(), children, max_size=5)
    ),
    max_leaves=30,
)


@given(st.dictionaries(st.text(), json_data, min_size=1, max_size=8))
def test_hash_is_independent_of_key_order(d):
    items = list(d.items())
    random.shuffle(items)
    assert hashing.spec_hash(dict(items)) == hashing.spec_hash(d)


@given(st.dictionaries(st.text(), st.integers(), min_size=1, max_size=8))
def test_hash_changes_when_any_value_changes(d):
    key = next(iter(d))
    changed = {**d, key: d[key] + 1}
    assert hashing.spec_hash(changed) != hashing.spec_hash(d)


@given(json_data)
def test_canonical_json_is_deterministic(x):
    assert hashing.canonical_json(x) == hashing.canonical_json(x)


def test_nan_is_rejected():
    with pytest.raises(ValueError):
        hashing.canonical_json({"x": math.nan})


def test_verification_ref_parts_cannot_be_shifted():
    # Without the separator, ("ab","c") and ("a","bc") would hash the same text.
    assert hashing.verification_ref("ab", "c", "d") != hashing.verification_ref("a", "bc", "d")


def test_prefixes_identify_the_kind_of_hash():
    # Prefixes make a hash's meaning visible in logs and the database.
    assert hashing.spec_hash({}).startswith("spec:")
    assert hashing.config_hash(None).startswith("cfg:")
    assert hashing.verification_ref("a", "b", "c").startswith("vref:")
