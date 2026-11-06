"""A session must be able to reach verification, whatever shape the model's arguments have."""

from pathlib import Path
from uuid import uuid4

import anyio
import pytest
import yaml

from te_platform.db.repo import Repository
from te_platform.db.session import session_scope
from te_platform.elicitation.answers import apply_answer
from te_platform.elicitation.protocol import current_protocol
from te_platform.registry.context import CallContext, Principal
from te_platform.registry.policy import load_policy
from te_platform.registry.state import compute_state, tools_for_state
from te_platform.tools.spec_save import SpecSaveInput, handle

EXAMPLE = Path(__file__).parents[2] / "examples" / "time_bank.yaml"
ALICE = Principal(id=f"spec-save-{uuid4().hex[:8]}", kind="user")


def _slot(slot_id: str):
    slot = current_protocol().slot(slot_id)
    assert slot is not None
    return slot


def test_a_list_sent_as_json_text_is_a_list() -> None:
    spec = apply_answer({}, _slot("tokens.ids"), '["CUE"]', "committed")
    assert spec["tokens"][0]["id"] == "CUE"


def test_a_single_value_for_a_list_slot_is_a_list_of_one() -> None:
    spec = apply_answer({}, _slot("tokens.ids"), "CUE", "committed")
    assert spec["tokens"][0]["id"] == "CUE"


def test_a_list_slot_with_indices_says_what_to_do() -> None:
    with pytest.raises(Exception, match="leave indices out"):
        apply_answer({}, _slot("tokens.ids"), "CUE", "committed", indices=(0,))


def test_an_object_sent_as_json_text_is_an_object() -> None:
    as_data = {"family": "bounded_range", "bounds": {"min": 10, "max": 100}}
    slot = _slot("participants.growth_g")
    import json  # noqa: PLC0415

    try:
        direct = apply_answer({}, slot, as_data, "committed")
    except Exception as exc:  # the shape itself may be refused, but alike for both forms
        with pytest.raises(type(exc)):
            apply_answer({}, slot, json.dumps(as_data), "committed")
    else:
        assert apply_answer({}, slot, json.dumps(as_data), "committed") == direct


def test_text_that_only_looks_like_json_stays_text() -> None:
    spec = apply_answer({}, _slot("meta.name"), "[draft] Maker Space", "committed")
    assert spec["meta"]["name"] == "[draft] Maker Space"


def _context(session_id: str) -> CallContext:
    with session_scope() as db:
        facts = Repository(db, ALICE).get_session_facts(session_id)
    return CallContext(principal=ALICE, tool_id="spec.save.v1", tool_input={}, session=facts)


@pytest.fixture
def session_id() -> str:
    with session_scope() as db:
        return Repository(db, ALICE).create_session()


@pytest.mark.db
def test_saving_a_complete_spec_unlocks_verification(session_id: str) -> None:
    policy = load_policy(Path(__file__).parents[2] / "policy" / "tool_policy.yaml")
    before = _context(session_id)
    assert "verify.run.v1" not in tools_for_state(compute_state(before, policy), policy)

    spec = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    out = anyio.run(handle, SpecSaveInput(session_id=session_id, spec=spec), before)
    assert out.saved and out.spec_version == 1 and out.spec_hash
    # "verified" when this very spec was verified before: results are shared by content.
    assert out.state in {"spec_ready", "verified"} and out.open_decisive_slots == []

    after = _context(session_id)
    assert "verify.run.v1" in tools_for_state(compute_state(after, policy), policy)
    assert after.session.current_spec_hash == out.spec_hash


@pytest.mark.db
def test_an_invalid_spec_is_not_stored_and_says_why(session_id: str) -> None:
    out = anyio.run(
        handle, SpecSaveInput(session_id=session_id, spec={"meta": {}}), _context(session_id)
    )
    assert not out.saved and out.errors and out.spec_version is None
    assert out.state == "eliciting"
    assert _context(session_id).session.current_spec is None


@pytest.mark.db
def test_another_users_session_cannot_be_written(session_id: str) -> None:
    other = Principal(id="someone-else", kind="user")
    ctx = _context(session_id).model_copy(update={"principal": other})
    spec = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    with pytest.raises(Exception, match=r"(?i)not found|session"):
        anyio.run(handle, SpecSaveInput(session_id=session_id, spec=spec), ctx)
