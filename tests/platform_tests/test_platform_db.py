## =============================================================================
## tests/platform_tests/test_platform_db.py — tests for te_platform/db/
## =============================================================================
## GUIDE STEP   5.3 (connection, roles, rollback), 5.4 (repository), 5.5,
##              6.2, 8.5, 9.0, 10.3 (activate each test with the code it tests)
## PURPOSE      Proves the database layer's promises:
##              1. ROLES (guide 5.1): the application's role reads and writes
##                 rows but cannot create or drop tables;
##              2. TRANSACTIONS: a failed `with session_scope()` block leaves
##                 nothing behind;
##              3. OWNERSHIP: for EVERY Repository method, a second principal
##                 cannot read or change the first principal's data (it gets
##                 NotFound, exactly as for an id that does not exist);
##              4. APPEND-ONLY: spec versions number 1, 2, 3..., a correction
##                 adds a row and wins, a verification is stored once.
## DEPENDS ON   A real PostgreSQL with the schema migrated (the Compose
##              `postgres` and `migrate` services, or a throw-away container).
##              These are INTEGRATION tests: an in-memory SQLite would not
##              support JSONB, tsvector or the role permissions, so it would
##              test something else. The tests never delete rows; every test
##              creates its own sessions, users and keys (random ids), so they
##              can run again on the same database.
## HOW TO RUN   docker compose up -d postgres migrate postgres-port
##              (postgres is only on the internal network; `postgres-port`,
##              the debug forwarder of compose.override.yml, publishes it on
##              127.0.0.1:5432; naming it starts it despite its `debug`
##              profile), then
##              TE_DATABASE_URL=postgresql+psycopg://te_app:<password>@127.0.0.1:5432/te \
##                uv run pytest tests/platform_tests/test_platform_db.py
##              The marker `db` lets CI run them in a separate job.
## WHY 5.3      The database exists from guide 5.1 and session.py from 5.2,
##              but the tables only after the first migration (5.3): that is
##              the first step where these tests can run.
## ACTIVATE     Section 1 with guide 5.3, then each labelled block with its
##              guide step.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your tests between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Activate each test
## together with the code it tests (header, ACTIVATE).
## These are integration tests on a real PostgreSQL (header, DEPENDS ON).
##
## Guide 5.3 (the tables exist; session.py active)
## [ ] 1. Imports: uuid4, pytest, ProgrammingError and text (sqlalchemy),
##        `models as m` and session_scope.
## [ ] 2. Mark the whole file as database tests:
##          | pytestmark = pytest.mark.db
##        and register the marker in pyproject.toml (the `markers` line in
##        te_platform/pyproject_additions.toml).
## [ ] 3. test_connection_works: `SELECT 1` through session_scope gives 1.
## [ ] 4. test_app_role_cannot_create_or_drop_tables: as the app role,
##        CREATE TABLE and DROP TABLE users both raise ProgrammingError
##        (permission denied / must be owner).
## [ ] 5. test_failed_block_rolls_back: add and flush a User, raise
##        RuntimeError in the same block; a new block cannot find the user.
## [ ] 6. Check (header, HOW TO RUN):
##          | docker compose up -d postgres migrate postgres-port
##          | TE_DATABASE_URL=... uv run pytest \
##          |     tests/platform_tests/test_platform_db.py
##
## Guide 5.4 (repository)
## [ ] 7. Imports: AuthRepository and Repository, NotFound, Principal.
##        Constants ALICE and MALLORY (users).
## [ ] 8. Fixture `alice_session() -> str`: as ALICE, create_session() and
##        add_spec_version(sid, {"meta": {"name": "t"}}, "spec:abc",
##        author="user"); return the id.
## [ ] 9. SESSION_METHODS: (name, lambda r, sid: ...) pairs, one per
##        Repository method that takes a session id (four at 5.4; the
##        labelled blocks below add the later ones), and, AFTER all those
##        blocks, test_other_principal_is_denied parametrised over it: each
##        call made as MALLORY on Alice's session raises NotFound.
## [ ] 10. test_spec_versions_increase, test_latest_answer_wins,
##         test_new_session_has_no_spec_facts, and the API-key tests
##         (unknown key -> None; created key -> its principal; revoked key
##         -> None).
## [ ] 11. Check: the step 6 command.
##
## Guide 5.5, 6.2, 8.5, 9.0, 10.3 (one labelled block each)
## [ ] 12. 5.5: a verification is stored once; an audit row records the
##         principal. 6.2: record_job joins SESSION_METHODS; jobs are
##         private; the first final status wins. 8.5: the message methods
##         join SESSION_METHODS; tokens_used sums the usage rows. 9.0: a
##         disabled user cannot log in. 10.3: reports are private.
## [ ] 13. Check: the step 6 command after each block.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from te_platform.db import models as m
from te_platform.db.session import session_scope

## Guide 5.4: the repository and the principals it filters by.
from te_platform.db.repo import AuthRepository, Repository
from te_platform.errors import NotFound
from te_platform.registry.context import Principal

## Guide 10.3: report records and their expiry times.
from datetime import UTC, datetime, timedelta
from te_platform.db.repo import ReportRecord

pytestmark = pytest.mark.db  # register the marker in pyproject's [tool.pytest.ini_options]


## --- 1. Connection, roles, transactions (guide 5.3) -----------------------------------
def test_connection_works() -> None:
    with session_scope() as db:
        assert db.scalar(text("SELECT 1")) == 1


def test_app_role_cannot_create_or_drop_tables() -> None:
    """Guide 5.1: the app role (TE_DATABASE_URL) has no DDL rights."""
    with pytest.raises(ProgrammingError, match="permission denied"), session_scope() as db:
        db.execute(text("CREATE TABLE should_fail (i int)"))
    with pytest.raises(ProgrammingError, match="must be owner"), session_scope() as db:
        db.execute(text("DROP TABLE users"))


def test_failed_block_rolls_back() -> None:
    uid = "rollback-" + uuid4().hex
    with pytest.raises(RuntimeError), session_scope() as db:
        db.add(m.User(id=uid, email=f"{uid}@example.org"))
        db.flush()  # the INSERT really reaches the database
        raise RuntimeError("boom")
    with session_scope() as db:
        assert db.get(m.User, uid) is None


## --- 2. Repository (guide 5.4) -----------------------------------------------------
## Guide 5.4: two users; Mallory tries to reach Alice's data.
ALICE = Principal(id="alice", kind="user")
MALLORY = Principal(id="mallory", kind="user")


## Guide 5.4: a fixture is a function pytest runs before a test to prepare
## something; a test receives it by naming it as a parameter.
@pytest.fixture
def alice_session() -> str:
    with session_scope() as db:
        repo = Repository(db, ALICE)
        sid = repo.create_session()
        repo.add_spec_version(sid, {"meta": {"name": "t"}}, "spec:abc", author="user")
    return sid


## Guide 5.4: one entry per Repository method that takes a session id.
## Parametrising over method names keeps "every method is covered" visible:
## adding a Repository method without adding it here is a review red flag.
SESSION_METHODS = [
    ("get_session_facts", lambda r, sid: r.get_session_facts(sid, open_decisive_slots=[])),
    ("add_spec_version", lambda r, sid: r.add_spec_version(sid, {}, "spec:x", "user")),
    (
        "record_answer",
        lambda r, sid: r.record_answer(sid, "participants.N", 10, "committed", "ten", 1),
    ),
    ("get_answers", lambda r, sid: r.get_answers(sid)),
]

## Guide 6.2: the job method that takes a session id.
SESSION_METHODS += [
    (
        "record_job",
        lambda r, sid: r.record_job(
            "job-" + uuid4().hex, "monte_carlo", "vref:x", {}, session_id=sid
        ),
    ),
]

## Guide 8.5: the chat-message methods.
SESSION_METHODS += [
    ("append_message", lambda r, sid: r.append_message(sid, "user", {"role": "user"})),
    ("list_messages", lambda r, sid: r.list_messages(sid)),
    ("tokens_used", lambda r, sid: r.tokens_used(sid)),
    ("get_pending_tool_calls", lambda r, sid: r.get_pending_tool_calls(sid)),
    ("set_pending_tool_calls", lambda r, sid: r.set_pending_tool_calls(sid, None)),
]

## Guide 10.3: the report method that takes a session id.
SESSION_METHODS += [
    (
        "save_report",
        lambda r, sid: r.save_report(
            ReportRecord(
                "rep-" + uuid4().hex, "vref:x", {}, "/tmp/x.pdf", datetime.now(UTC), session_id=sid
            )
        ),
    ),
]


## Guide 5.4: every method above, called by Mallory on Alice's session.
@pytest.mark.parametrize(("name", "call"), SESSION_METHODS, ids=[n for n, _ in SESSION_METHODS])
def test_other_principal_is_denied(alice_session: str, name: str, call) -> None:
    with pytest.raises(NotFound), session_scope() as db:
        call(Repository(db, MALLORY), alice_session)


## Guide 5.4: append-only spec versions.
def test_spec_versions_increase(alice_session: str) -> None:
    with session_scope() as db:
        repo = Repository(db, ALICE)
        assert repo.add_spec_version(alice_session, {}, "spec:2", "agent") == 2
        assert repo.add_spec_version(alice_session, {}, "spec:3", "form") == 3


## Guide 5.4: a correction is a new row, and the newest row wins.
def test_latest_answer_wins(alice_session: str) -> None:
    with session_scope() as db:
        repo = Repository(db, ALICE)
        repo.record_answer(alice_session, "participants.N", 10, "committed", "about ten", 1)
        repo.record_answer(alice_session, "participants.N", 50, "committed", "no, fifty", 2)
        answers = {a["slot_id"]: a for a in repo.get_answers(alice_session)}
    assert answers["participants.N"]["value"] == 50
    assert answers["participants.N"]["user_quote"] == "no, fifty"


## Guide 5.4: the facts of a session with one spec version and nothing else.
def test_new_session_has_no_spec_facts(alice_session: str) -> None:
    with session_scope() as db:
        facts = Repository(db, ALICE).get_session_facts(alice_session)
    assert facts.owner_id == "alice"
    assert facts.current_spec_hash == "spec:abc"
    assert facts.current_spec == {"meta": {"name": "t"}}
    assert facts.verification_ref is None
    assert facts.running_jobs == 0


## Guide 5.4: an unknown key authenticates nobody.
def test_unknown_key_gives_no_principal() -> None:
    with session_scope() as db:
        assert AuthRepository(db).find_principal_by_key_hash("0" * 64) is None


## Guide 5.4: a key authenticates its owner until it is revoked.
def test_created_key_works_until_revoked() -> None:
    key_hash = uuid4().hex + uuid4().hex  # 64 hex characters, unique
    with session_scope() as db:
        AuthRepository(db).create_api_key("partner-lab", "api_key", key_hash, "verify sim")
    with session_scope() as db:
        p = AuthRepository(db).find_principal_by_key_hash(key_hash)
    assert p == Principal(id="partner-lab", kind="api_key", scopes=frozenset({"verify", "sim"}))
    with session_scope() as db:
        assert AuthRepository(db).revoke_api_key(key_hash) is True
    with session_scope() as db:
        assert AuthRepository(db).find_principal_by_key_hash(key_hash) is None
        assert AuthRepository(db).revoke_api_key("f" * 64) is False


## --- 3. Verifications and audit (guide 5.5) -------------------------------------------
## Guide 5.5: content-addressed: stored once, the first result is kept.
def test_verification_is_stored_once() -> None:
    ref = "vref:" + uuid4().hex
    with session_scope() as db:
        Repository(db, ALICE).save_verification(ref, "spec:abc", {"n": 1})
    with session_scope() as db:
        Repository(db, MALLORY).save_verification(ref, "spec:abc", {"n": 2})
    with session_scope() as db:
        assert Repository(db, MALLORY).get_verification(ref) == {"n": 1}
        assert Repository(db, ALICE).get_verification("vref:missing") is None


## Guide 5.5: the session facts see the verification of the current spec.
def test_facts_see_the_verification_of_the_current_spec(alice_session: str) -> None:
    ref = "vref:" + uuid4().hex
    with session_scope() as db:
        Repository(db, ALICE).save_verification(ref, "spec:abc", {})
    with session_scope() as db:
        facts = Repository(db, ALICE).get_session_facts(alice_session)
    assert facts.verification_ref == ref
    assert facts.verified_spec_hash == "spec:abc"


## Guide 5.5: every audit row names who made the call.
def test_audit_row_records_the_principal() -> None:
    cid = uuid4().hex
    with session_scope() as db:
        Repository(db, ALICE).write_audit(
            "verify.run.v1", "in:x", "ok", 12, override_reason=None, correlation_id=cid
        )
    with session_scope() as db:
        rows = db.query(m.AuditEntry).filter_by(correlation_id=cid).all()
    assert [(r.principal_id, r.tool_id, r.outcome) for r in rows] == [
        ("alice", "verify.run.v1", "ok")
    ]


## --- 4. Later tables ---------------------------------------------------------------------
## Guide 6.2: get_job / update_job follow the same rule as sessions.
def test_jobs_are_private() -> None:
    job_id = "job-" + uuid4().hex
    with session_scope() as db:
        Repository(db, ALICE).record_job(job_id, "monte_carlo", "vref:x", {"seed": 1})
    with pytest.raises(NotFound), session_scope() as db:
        Repository(db, MALLORY).get_job(job_id)
    with pytest.raises(NotFound), session_scope() as db:
        Repository(db, MALLORY).update_job(job_id, "failed")
    with session_scope() as db:
        assert Repository(db, ALICE).get_job(job_id)["status"] == "queued"


## Guide 6.2: a job reported as ended twice keeps its first outcome.
def test_first_final_status_wins() -> None:
    job_id = "job-" + uuid4().hex
    with session_scope() as db:
        Repository(db, ALICE).record_job(job_id, "monte_carlo", "vref:x", {})
    with session_scope() as db:
        Repository(db, ALICE).update_job(job_id, "cancelled")
    with session_scope() as db:
        Repository(db, ALICE).update_job(job_id, "finished", {"kind": "monte_carlo"})
    with session_scope() as db:
        row = Repository(db, ALICE).get_job(job_id)
        finished_at = db.get(m.Job, job_id).finished_at
    assert (row["status"], row["result"]) == ("cancelled", None)
    assert finished_at is not None and finished_at.tzinfo is not None


## Guide 6.2: the session facts count finished simulations and open jobs.
def test_facts_count_simulations_and_running_jobs(alice_session: str) -> None:
    ref = "vref:" + uuid4().hex
    with session_scope() as db:
        repo = Repository(db, ALICE)
        repo.save_verification(ref, "spec:abc", {})
        repo.record_job("job-a" + uuid4().hex, "monte_carlo", ref, {}, session_id=alice_session)
        repo.record_job("job-b" + uuid4().hex, "trajectory", ref, {}, session_id=alice_session)
    with session_scope() as db:
        facts = Repository(db, ALICE).get_session_facts(alice_session)
    assert (facts.running_jobs, facts.finished_simulation_for_current_ref) == (2, False)


## Guide 8.5: the token budget sums the usage rows only.
def test_tokens_used_sums_usage_rows(alice_session: str) -> None:
    with session_scope() as db:
        repo = Repository(db, ALICE)
        repo.append_message(alice_session, "user", {"role": "user", "content": "hi"})
        for used_in, used_out in ((10, 5), (7, 1)):
            repo.append_message(
                alice_session, "usage", {}, {"input_tokens": used_in, "output_tokens": used_out}
            )
    with session_scope() as db:
        repo = Repository(db, ALICE)
        assert repo.tokens_used(alice_session) == 23
        assert [msg["role"] for msg in repo.list_messages(alice_session)] == [
            "user",
            "usage",
            "usage",
        ]


## Guide 9.0: a disabled user cannot log in.
def test_disabled_user_cannot_log_in() -> None:
    code_hash = uuid4().hex + uuid4().hex
    with session_scope() as db:
        uid = AuthRepository(db).create_user(f"{uuid4().hex}@example.org", code_hash)
    with session_scope() as db:
        assert AuthRepository(db).find_user_by_access_code_hash(code_hash) == Principal(
            id=uid, kind="user"
        )
        db.get(m.User, uid).disabled = True
    with session_scope() as db:
        assert AuthRepository(db).find_user_by_access_code_hash(code_hash) is None


## Guide 10.3: get_report follows the same rule as sessions.
def test_reports_are_private() -> None:
    report_id = "rep-" + uuid4().hex
    expires = datetime.now(UTC) + timedelta(hours=1)
    with session_scope() as db:
        Repository(db, ALICE).save_report(
            ReportRecord(report_id, "vref:x", {"summary": "s"}, "/tmp/r.pdf", expires)
        )
    with pytest.raises(NotFound), session_scope() as db:
        Repository(db, MALLORY).get_report(report_id)
    with session_scope() as db:
        assert Repository(db, ALICE).get_report(report_id)["expires_at"] == expires
