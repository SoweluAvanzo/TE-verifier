## =============================================================================
## te_platform/db/repo.py — the repository layer: the ONLY code that queries the DB
## =============================================================================
## GUIDE STEP   5.4 (Repository with write_audit, AuthRepository), 5.5 (verifications),
##              6.2 (jobs), 7.5 (open decisive slots), 8.5 (messages),
##              9.0 (users), 10.3 (reports), 11.1-11.2 (LiteratureRepository)
## PURPOSE      Three classes:
##              - Repository(db, principal): everything a tool, the agent or
##                the web app reads or writes. EVERY method that touches
##                user-owned data filters by principal.id, so a caller can
##                never see another user's sessions, jobs, reports or messages.
##              - AuthRepository(db): the few lookups needed BEFORE anyone is
##                authenticated (find the principal of an API key or of an
##                access code) or by the operator (create keys and users). It
##                has no principal on purpose.
##              - LiteratureRepository(db): the curated literature collection,
##                which is the same for every user (no principal either).
##              Methods return plain dicts or the Pydantic models of
##              registry/context.py, never ORM objects, so callers never hold
##              objects tied to a closed database session.
## USED BY      registry/pipeline.py (audit rows, guide 5.5), mcp_server/app.py
##              (session facts), tools/verify_run.py (verification store),
##              mcp_server/auth.py, agent/login_api.py and cli.py
##              (AuthRepository), tools/elicit_*.py (sessions, answers, spec
##              versions), jobs/queue.py (job rows), jobs/report_task.py
##              (reports),
##              tools/report_render_pdf.py (verification + simulation for the
##              number check), agent/chat_api.py (sessions, messages),
##              agent/spec_api.py (spec versions), agent/user_reports_api.py
##              (report download), literature/ingest.py and literature/search.py
##              (LiteratureRepository), tests.
## DEPENDS ON   db/models.py, registry/context.py (Principal, SessionFacts),
##              errors.py (NotFound), elicitation/ranking.py (which slots are
##              decisive, guide 7.5), literature/chunking.py (Chunk, 11.1).
## WHY          Guide §2.2 and 5.4: authorisation in exactly ONE place, so it
##              can be checked completely; there is deliberately no function
##              that queries USER-OWNED data without the owner filter. (The
##              exceptions hold no user-owned data: verifications, see the
##              comment above save_verification, and the literature
##              collection.) Append-only tables (models.py) have insert
##              functions only: P5 provenance.
## ACTIVATE     Method by method, at the guide step of its "## Guide X.Y"
##              label (methods of later steps are commented twice). For every
##              method, test_platform_db.py has a test where a SECOND
##              principal tries the same call and must be denied.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep class names, method
## names and arguments exactly as in the SOLUTION: tools, the pipeline, the
## agent and the CLI call them. Write each method with the guide step that
## needs it (header GUIDE STEP; in the SOLUTION, the "## Guide X.Y" labels).
##
## Guide 5.4 (first: db/models.py, db/session.py, errors.py and
## registry/context.py active, and the 5.3 migration applied)
## [ ] 1. Imports at the top: Any, uuid4; func and select from sqlalchemy;
##        Session from sqlalchemy.orm; `models as m` from te_platform.db;
##        NotFound; Principal and SessionFacts.
## [ ] 2. `class Repository` with `__init__(self, db: Session, principal:
##        Principal)` that stores them as self._db and self._p.
## [ ] 3. The ownership guard `_own_session(session_id)`: self._db.get the
##        DesignSession; if it is None OR its owner_id is not self._p.id,
##        raise NotFound("Session not found."). Every session method below
##        calls it first.
## [ ] 4. `create_session(protocol_version="", policy_version="") -> str`:
##        a new uuid4().hex id, add a DesignSession owned by self._p.id.
## [ ] 5. `get_session_facts(session_id, open_decisive_slots=None)`: build
##        a SessionFacts from small queries (see its docstring): the latest
##        spec version, a verification with that spec's hash. Until guide
##        7.5 the open decisive slots are the list passed in, or []; the
##        job and report counts stay 0 until guides 6.2 and 10.3 add them.
## [ ] 6. `add_spec_version(session_id, spec, spec_hash, author) -> int`:
##        next version = (highest existing version or 0) + 1, then insert:
##          | select(func.max(m.SpecVersion.version)).where(...)
## [ ] 6b. `lock_session(session_id)`: SELECT the session row
##        `.with_for_update()` (NotFound when it is not the caller's), held
##        until the transaction ends. add_spec_version calls it first, and
##        so does every caller that reads the spec before writing a new
##        version (elicit_record_answer.py): the agent runs a reply's tool
##        calls in parallel, and two unlocked writers would both write
##        version N+1, each from the same old spec.
## [ ] 7. `record_answer(session_id, slot_id, value, status, user_quote,
##        spec_version, indices=None)`: insert only, with the value wrapped
##        as {"value": value} and indices as a list.
## [ ] 8. `get_answers(session_id)`: rows ordered by id, keep the LAST one
##        per (slot_id, tuple(indices)); return dicts with slot_id,
##        indices, value (unwrapped), status, user_quote, spec_version.
## [ ] 9. `class AuthRepository` with `__init__(self, db)` only (no
##        principal, on purpose). Methods: create_api_key(owner, kind,
##        key_hash, scopes="") -> key id; find_principal_by_key_hash
##        (None when missing or revoked; scopes from the space-separated
##        string):
##          | scopes=frozenset(row.scopes.split())
##        revoke_api_key(key_hash) -> bool (flag the row, never delete it).
## [ ] 9b. In Repository: `write_audit(tool_id, input_hash, outcome,
##        latency_ms, *, override_reason, correlation_id)`: insert an
##        AuditEntry with principal_id=self._p.id (the pipeline calls it
##        from guide 5.5).
## [ ] 10. Check: activate the guide 5.4 tests of
##         tests/platform_tests/test_platform_db.py (each Repository method
##         is called as a second principal and must raise NotFound), then
##          | uv run pytest tests/platform_tests/test_platform_db.py -q
##          | uv run mypy te_platform
##
## Guide 5.5 (verifications)
## [ ] 11. `save_verification(verification_ref, spec_hash, result)`: insert
##         only if no row has that ref (no owner filter: read the `##`
##         comment above it). `get_verification(ref)` returns the result
##         dict or None.
## [ ] 12. (written at 5.4, step 9b, so the audit table and its method
##         arrive together; the pipeline starts calling it now.)
## [ ] 13. Check: the commands of step 10 with the guide 5.5 tests, and
##         the guide 5.5 "Done when" (a repeated verify.run.v1 comes from
##         the store).
##
## Guide 6.2 (jobs; first: the Job table of db/models.py)
## [ ] 14. In get_session_facts, count this session's finished simulations
##         of the current verification and its queued jobs (the
##         "## Guide 6.2" block there).
## [ ] 15. The constant _FINAL_JOB_STATUSES (finished, failed, cancelled).
##         `record_job(job_id, kind, verification_ref, params,
##         session_id=None)`: check the session if given; if the job row
##         already exists, reset it to "queued" (see the docstring), else
##         insert it.
## [ ] 16. `_own_job(job_id)` (like _own_session, "Job not found."), then
##         get_job(job_id) -> dict (job_id, kind, status, verification_ref,
##         params, result); update_job(job_id, status, result=None), which
##         ignores rows already in a final status and sets finished_at with
##         the database clock:
##          | row.finished_at = func.now()
##         latest_finished_simulation(verification_ref) -> the result of
##         this owner's newest finished "monte_carlo" job, or None.
## [ ] 17. Check: the commands of step 10 with the guide 6.2 tests.
##
## Guide 7.5 (the elicitation ranking exists)
## [ ] 18. Import open_decisive_slots from te_platform.elicitation.ranking
##         as ranked_open_slots (labelled block at the top), and use it in
##         get_session_facts when open_decisive_slots is None (the
##         "## Guide 7.5" block there).
##
## Guide 8.5 (chat messages; first: the Message table)
## [ ] 19. append_message(session_id, role, content, usage=None) (insert
##         only); list_messages(session_id) -> [{role, content, usage}] in
##         id order; tokens_used(session_id) -> the sum of input_tokens and
##         output_tokens of the rows whose usage is not NULL.
## [ ] 19b. (conversation history extension) append_message returns the new
##         row's id (flush); delete_message(session_id, message_id) removes
##         one row of the caller's session; list_sessions(limit=50): the
##         caller's sessions that have user messages, latest activity
##         first, each with its first user message (one DISTINCT ON query).
## [ ] 20. get_pending_tool_calls(session_id) and
##         set_pending_tool_calls(session_id, pending): read or set
##         pending_tool_calls on the row _own_session returns.
##
## Guide 9.0 (login)
## [ ] 21. In AuthRepository: create_user(email, access_code_hash) -> user
##         id, and find_user_by_access_code_hash (None when unknown or
##         disabled).
##
## Guide 10.3 (reports; first: the Report table)
## [ ] 22. Import dataclass and datetime (labelled block at the top) and
##         write the frozen dataclass ReportRecord (report_id,
##         verification_ref, narrative, path, expires_at, session_id=None).
##         save_report(report: ReportRecord), which checks the session if
##         given; get_report(report_id) -> dict (report_id,
##         verification_ref, path, expires_at, narrative), with
##         NotFound("Report not found.") for a missing or foreign id. In
##         get_session_facts, count the reports of the current
##         verification (the "## Guide 10.3" block there).
##
## Guide 11.1-11.2 (literature; first: the Work and Chunk tables)
## [ ] 23. 11.1: import Chunk from te_platform.literature.chunking (labelled
##         block at the top) and write `class LiteratureRepository` with
##         `__init__(self, db)` (no principal: the collection is shared, see
##         its docstring), add_work(metadata, chunks) -> work id (flush the
##         work before adding its chunks: the comment there says why) and
##         count_works() -> int.
## [ ] 24. 11.2: search_passages(query, limit) -> list of dicts (citation
##         data, the chunk text, score), with the query as a bound
##         parameter, never pasted into SQL:
##          | tsq = func.websearch_to_tsquery("english", query)
##         ranked with func.ts_rank_cd(m.Chunk.tsv, tsq), filtered with
##         m.Chunk.tsv.op("@@")(tsq).
## [ ] 25. Check after each group: the matching tests of
##         test_platform_db.py / test_platform_literature.py and the
##         commands of step 10.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## Guide 11.1: LiteratureRepository.add_work takes a Sequence of chunks.
from collections.abc import Sequence

## Guide 10.3: the report record and its expiry time.
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Text, func, select
from sqlalchemy.orm import Session

from te_platform.db import models as m

## Guide 7.5: the decisive slots still open (renamed: the method has a
## parameter called open_decisive_slots).
from te_platform.elicitation.ranking import open_decisive_slots as ranked_open_slots
from te_platform.errors import NotFound

## Guide 11.1: the passages of a paper (a pure dataclass, no database code).
from te_platform.literature.chunking import Chunk
from te_platform.registry.context import Principal, SessionFacts

## Phase 6.2: a job in one of these states has ended; its row no longer changes.
_FINAL_JOB_STATUSES = frozenset({"finished", "failed", "cancelled"})


## Guide 10.3: what save_report stores about one rendered report (one
## argument instead of six: the fields have names at the call site).
@dataclass(frozen=True)
class ReportRecord:
    """The record of one rendered report."""

    ## Guide 10.3: the fields of a report record.
    report_id: str
    verification_ref: str
    narrative: dict[str, str]  # the agent's labelled text sections
    path: str  # the PDF under Settings.report_storage_dir
    expires_at: datetime  # with its time zone (models.py, header TIME)
    session_id: str | None = None


class Repository:
    """All reads and writes on behalf of ONE authenticated caller.

    Create one per unit of work:
        with session_scope() as db:
            repo = Repository(db, ctx.principal)
    """

    def __init__(self, db: Session, principal: Principal) -> None:
        self._db = db
        self._p = principal

    # ---- ownership guard ------------------------------------------------------
    def _own_session(self, session_id: str) -> m.DesignSession:
        """Return the session if it belongs to the caller, else raise NotFound.

        "Not yours" and "doesn't exist" look identical on purpose
        (errors.py): nobody can probe which session ids exist.
        """
        row = self._db.get(m.DesignSession, session_id)
        if row is None or row.owner_id != self._p.id:
            raise NotFound("Session not found.")
        return row

    def lock_session(self, session_id: str) -> None:
        """Lock the caller's session row until this transaction ends (one writer at a time).

        The agent runs a reply's tool calls in parallel: two answers recorded
        at once would both read spec version N and both write N+1 (a
        duplicate key), and each would apply its answer to the same old
        spec, losing the other. SELECT ... FOR UPDATE makes the second
        writer wait until the first has committed; it then reads the new
        version (PostgreSQL's READ COMMITTED reads what is committed when
        each statement starts). Call it BEFORE reading what you will change.
        """
        row = self._db.scalar(
            select(m.DesignSession).where(m.DesignSession.id == session_id).with_for_update()
        )
        if row is None or row.owner_id != self._p.id:
            raise NotFound("Session not found.")

    # ---- sessions -----------------------------------------------------------------
    def create_session(self, protocol_version: str = "", policy_version: str = "") -> str:
        """Create a session owned by the caller and return its id."""
        sid = uuid4().hex
        self._db.add(
            m.DesignSession(
                id=sid,
                owner_id=self._p.id,
                protocol_version=protocol_version,
                policy_version=policy_version,
            )
        )
        return sid

    def get_session_facts(
        self, session_id: str, open_decisive_slots: list[str] | None = None
    ) -> SessionFacts:
        """Collect the stored facts registry/state.py derives the state from.

        Each field is answered by one small query:
        - current spec: the row with the highest version number;
        - verification of the current spec: a verification row whose
          spec_hash equals the current spec's hash (content addressing:
          no link table needed);
        - open decisive slots: computed by te_platform.elicitation (which
          decisive questions APPLY depends on the archetype and the routing
          rules, and which are open on the answers so far); the parameter
          lets callers and tests pass a fixed list instead;
        - simulations / reports: rows for the current verification_ref;
        - running jobs: queued jobs of this session (a job row stays
          "queued" until it ends, jobs/queue.py settle_job).
        """
        self._own_session(session_id)
        spec_row = self._db.scalars(
            select(m.SpecVersion)
            .where(m.SpecVersion.session_id == session_id)
            .order_by(m.SpecVersion.version.desc())
            .limit(1),
        ).first()
        current_hash = spec_row.spec_hash if spec_row else None

        vref = None
        if current_hash:
            vref = self._db.scalars(
                select(m.Verification.verification_ref)
                .where(m.Verification.spec_hash == current_hash)
                .order_by(m.Verification.created_at.desc())
                .limit(1),
            ).first()

        if open_decisive_slots is None:
            # Until the elicitation protocol exists (guide 7.5), no slot is
            # known to be decisive.
            open_decisive_slots = []
            ## Guide 7.5: ask the elicitation ranking (which decisive slots
            ## apply to this spec and are still unanswered).
            open_decisive_slots = ranked_open_slots(
                spec_row.spec if spec_row else {}, self.get_answers(session_id)
            )

        sims = reports = running = 0
        ## Guide 6.2: simulations and running jobs, from the jobs table.
        if vref:
            sims = int(
                self._db.scalar(
                    select(func.count())
                    .select_from(m.Job)
                    .where(
                        m.Job.session_id == session_id,
                        m.Job.verification_ref == vref,
                        m.Job.kind.in_(["monte_carlo", "trajectory"]),
                        m.Job.status == "finished",
                    )
                )
                or 0
            )
        running = int(
            self._db.scalar(
                select(func.count())
                .select_from(m.Job)
                .where(m.Job.session_id == session_id, m.Job.status == "queued")
            )
            or 0
        )
        ## Guide 10.3: reports of the current verification, from the reports table.
        if vref:
            reports = int(
                self._db.scalar(
                    select(func.count())
                    .select_from(m.Report)
                    .where(m.Report.session_id == session_id, m.Report.verification_ref == vref)
                )
                or 0
            )

        return SessionFacts(
            session_id=session_id,
            owner_id=self._p.id,
            current_spec_hash=current_hash,
            current_spec=spec_row.spec if spec_row else None,
            verification_ref=vref,
            verified_spec_hash=current_hash if vref else None,
            open_decisive_slots=sorted(open_decisive_slots),
            finished_simulation_for_current_ref=sims > 0,
            report_for_current_ref=reports > 0,
            running_jobs=running,
        )

    # ---- spec versions and answers (append-only) ---------------------------------
    def add_spec_version(
        self, session_id: str, spec: dict[str, Any], spec_hash: str, author: str
    ) -> int:
        """Append the next version of the session's spec and return its number."""
        # The lock makes the version number unique under concurrent writers
        # (lock_session); a caller that READS the spec first locks earlier.
        self.lock_session(session_id)
        last = self._db.scalar(
            select(func.max(m.SpecVersion.version)).where(m.SpecVersion.session_id == session_id)
        )
        version = (last or 0) + 1
        self._db.add(
            m.SpecVersion(
                session_id=session_id,
                version=version,
                spec=spec,
                spec_hash=spec_hash,
                author=author,
            )
        )
        return version

    def spec_from_form_unseen(self, session_id: str) -> dict[str, Any] | None:
        """Return the current spec if the form stored it after the last message, else None.

        The form saves the design into the session (agent/spec_api.py); the
        model learns of it only through a note (agent/notes.py), once.
        """
        self._own_session(session_id)
        latest = self._db.scalars(
            select(m.SpecVersion)
            .where(m.SpecVersion.session_id == session_id)
            .order_by(m.SpecVersion.version.desc())
            .limit(1)
        ).first()
        if latest is None or latest.author != "form":
            return None
        last_message = self._db.scalar(
            select(func.max(m.Message.created_at)).where(m.Message.session_id == session_id)
        )
        if last_message is not None and last_message >= latest.created_at:
            return None
        return dict(latest.spec)

    def record_answer(  # noqa: PLR0913, PLR0917  one argument per stored column
        self,
        session_id: str,
        slot_id: str,
        value: Any,
        status: str,
        user_quote: str,
        spec_version: int,
        indices: list[int] | None = None,
    ) -> None:
        """Append one answer (a correction is a new row, never an update)."""
        self._own_session(session_id)
        self._db.add(
            m.Answer(
                session_id=session_id,
                slot_id=slot_id,
                indices=list(indices or []),
                value={"value": value},
                status=status,
                user_quote=user_quote,
                spec_version=spec_version,
            )
        )

    def get_answers(self, session_id: str) -> list[dict[str, Any]]:
        """Return the LATEST answer per (slot, indices); a correction is a newer row.

        Per-token slots are answered once per token, hence the indices in
        the key.
        """
        self._own_session(session_id)
        rows = self._db.scalars(
            select(m.Answer).where(m.Answer.session_id == session_id).order_by(m.Answer.id)
        )
        latest: dict[tuple[str, tuple[int, ...]], dict[str, Any]] = {}
        for r in rows:
            latest[(r.slot_id, tuple(r.indices))] = {
                "slot_id": r.slot_id,
                "indices": list(r.indices),
                "value": r.value.get("value"),
                "status": r.status,
                "user_quote": r.user_quote,
                "spec_version": r.spec_version,
            }
        return list(latest.values())

    # ---- verifications (content-addressed, shared) --------------------------------
    ## Guide 5.5: store a verification result once (insert only, never update).
    ## No owner filter here, deliberately: a verification row contains only
    ## the verifier's output for a spec that the caller ALREADY HOLDS (the
    ## ref is a hash of that spec), so reading it reveals nothing new.
    ## Sharing it lets identical specs reuse one computation. What IS
    ## per-user is the provenance (who verified what, when): that lives in
    ## audit_log, which records the principal on every call.
    def save_verification(
        self, verification_ref: str, spec_hash: str, result: dict[str, Any]
    ) -> None:
        """Store a verification result unless one with this ref exists."""
        if self._db.get(m.Verification, verification_ref) is None:
            self._db.add(
                m.Verification(
                    verification_ref=verification_ref, spec_hash=spec_hash, result=result
                )
            )

    ## Guide 5.5: read a stored verification (no owner filter, see above).
    ## JSONB may return a whole-valued float as an int (models.py,
    ## Verification): equal values, possibly different types.
    def get_verification(self, verification_ref: str) -> dict[str, Any] | None:
        """Return the stored result for this ref, or None."""
        row = self._db.get(m.Verification, verification_ref)
        return row.result if row else None

    # ---- audit (append-only) ---------------------------------------------------------
    # One audit row per tool call (registry/pipeline.py step 8, from guide
    # 5.5). The last two arguments are keyword-only: two adjacent optional
    # strings are easy to swap by mistake.
    def write_audit(  # noqa: PLR0913  one argument per stored column
        self,
        tool_id: str,
        input_hash: str,
        outcome: str,
        latency_ms: int,
        *,
        override_reason: str | None,
        correlation_id: str,
    ) -> None:
        """Append one audit row for a tool call made by the caller."""
        self._db.add(
            m.AuditEntry(
                principal_id=self._p.id,
                tool_id=tool_id,
                input_hash=input_hash,
                outcome=outcome,
                latency_ms=latency_ms,
                override_reason=override_reason,
                correlation_id=correlation_id,
            )
        )

    # ---- jobs ------------------------------------------------------------------------
    ## Guide 6.2: insert a job row, or reset an existing one to "queued".
    ## jobs/queue.py writes the row BEFORE the job is queued. A seeded job's
    ## id is deterministic (jobs/queue.py), so the same request made again
    ## after the old job failed, was cancelled or expired from Redis reuses
    ## the id: the row is then reset instead of inserted twice (which would
    ## violate the primary key). Found by running the tests against a real
    ## database.
    def record_job(
        self,
        job_id: str,
        kind: str,
        verification_ref: str,
        params: dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        """Record a job of the caller as queued (insert, or reset a reused id)."""
        if session_id is not None:
            self._own_session(session_id)
        row = self._db.get(m.Job, job_id)
        if row is not None:
            if row.owner_id != self._p.id:  # cannot happen: ids include the owner
                raise NotFound("Job not found.")
            row.status, row.result, row.finished_at = "queued", None, None
            row.params, row.session_id = params, session_id
            return
        self._db.add(
            m.Job(
                id=job_id,
                owner_id=self._p.id,
                session_id=session_id,
                kind=kind,
                verification_ref=verification_ref,
                params=params,
                status="queued",
            )
        )

    ## Guide 6.2: the ownership guard for jobs (like _own_session).
    def _own_job(self, job_id: str) -> m.Job:
        """Return the job row if it belongs to the caller, else raise NotFound."""
        row = self._db.get(m.Job, job_id)
        if row is None or row.owner_id != self._p.id:
            raise NotFound("Job not found.")
        return row

    ## Guide 6.2: the newest finished Monte Carlo run of a verification, used
    ## by the report tool and renderer (tools/report_render_pdf.py,
    ## jobs/tasks.py) for the number check.
    def latest_finished_simulation(self, verification_ref: str) -> dict[str, Any] | None:
        """Return the result of the caller's newest finished Monte Carlo run, or None."""
        row = self._db.scalars(
            select(m.Job)
            .where(
                m.Job.owner_id == self._p.id,
                m.Job.verification_ref == verification_ref,
                m.Job.kind == "monte_carlo",
                m.Job.status == "finished",
            )
            .order_by(m.Job.finished_at.desc())
            .limit(1),
        ).first()
        return row.result if row else None

    ## Experiments (tool sim.experiment.v1) on this verification, oldest
    ## first: the report prints each with its charts. Owner-filtered like
    ## latest_finished_simulation; the result carries its own job id.
    def finished_experiments(self, verification_ref: str) -> list[dict[str, Any]]:
        """Return the caller's finished experiments on this verification."""
        rows = self._db.scalars(
            select(m.Job)
            .where(
                m.Job.owner_id == self._p.id,
                m.Job.verification_ref == verification_ref,
                m.Job.kind == "experiment",
                m.Job.status == "finished",
            )
            .order_by(m.Job.finished_at),
        ).all()
        return [{**r.result, "job_id": r.id} for r in rows if r.result]

    ## Guide 6.2: read one job row.
    def get_job(self, job_id: str) -> dict[str, Any]:
        """Return the caller's job row as a dict (NotFound for anyone else)."""
        r = self._own_job(job_id)
        return {
            "job_id": r.id,
            "kind": r.kind,
            "status": r.status,
            "verification_ref": r.verification_ref,
            "params": r.params,
            "result": r.result,
        }

    ## Guide 6.2: record how a job ended. Called through jobs/queue.py
    ## settle_job, which acts with the job owner's principal, so the
    ## ownership check still applies. A job can be reported as ended twice
    ## (e.g. cancelled by the user just as a worker finishes it): the FIRST
    ## report wins, so a row never flips between final states. finished_at
    ## uses the database clock, like created_at (models.py, header TIME).
    def update_job(self, job_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        """Record the end of a job; a row already in a final status is left alone."""
        r = self._own_job(job_id)
        if r.status in _FINAL_JOB_STATUSES:
            return
        r.status = status
        if result is not None:
            r.result = result
        if status in _FINAL_JOB_STATUSES:
            r.finished_at = func.now()

    # ---- chat messages (append-only) ---------------------------------------------
    ## Guide 8.5: store one chat message, or one token-usage record (role
    ## "usage", content {}).
    def append_message(
        self, session_id: str, role: str, content: Any, usage: dict[str, Any] | None = None
    ) -> int:
        """Append one message (or one token-usage record); return its id."""
        self._own_session(session_id)
        row = m.Message(session_id=session_id, role=role, content=content, usage=usage)
        self._db.add(row)
        self._db.flush()  # assigns row.id
        return row.id

    ## Conversation history: undo a turn that failed before any answer (see
    ## agent/chat_api.py): its user message must not reach the model later.
    def delete_message(self, session_id: str, message_id: int) -> None:
        """Delete one message of the caller's session (nothing if it is not there)."""
        self._own_session(session_id)
        row = self._db.get(m.Message, message_id)
        if row is not None and row.session_id == session_id:
            self._db.delete(row)

    ## Conversation history: the caller's conversations for the chat sidebar.
    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the caller's sessions that have messages, most recent activity first.

        Each entry: id, created_at, updated_at (the last message) and
        first_user_message (the stored provider message, for the title).
        """
        last = (
            select(m.Message.session_id, func.max(m.Message.created_at).label("updated_at"))
            .join(m.DesignSession, m.DesignSession.id == m.Message.session_id)
            .where(m.DesignSession.owner_id == self._p.id, m.Message.role == "user")
            .group_by(m.Message.session_id)
            .order_by(func.max(m.Message.created_at).desc())
            .limit(limit)
            .subquery()
        )
        rows = self._db.execute(
            select(m.DesignSession, last.c.updated_at)
            .join(last, last.c.session_id == m.DesignSession.id)
            .order_by(last.c.updated_at.desc())
        ).all()
        ids = [s.id for s, _ in rows]
        # The first user message of each (PostgreSQL DISTINCT ON): one query.
        firsts = {
            msg.session_id: {"role": msg.role, "content": msg.content}
            for msg in self._db.scalars(
                select(m.Message)
                .where(m.Message.session_id.in_(ids), m.Message.role == "user")
                .distinct(m.Message.session_id)
                .order_by(m.Message.session_id, m.Message.id)
            )
        }
        return [
            {
                "id": s.id,
                "created_at": s.created_at,
                "updated_at": updated,
                "first_user_message": firsts.get(s.id),
            }
            for s, updated in rows
        ]

    ## Guide 8.5: read the transcript.
    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Return the session's messages in the order they were stored."""
        self._own_session(session_id)
        rows = self._db.scalars(
            select(m.Message).where(m.Message.session_id == session_id).order_by(m.Message.id)
        )
        return [{"role": r.role, "content": r.content, "usage": r.usage} for r in rows]

    ## Guide 8.5: the session's token budget. Each usage row holds the tokens
    ## of ONE model request (agent/loop.py), so the sum is the session total.
    def tokens_used(self, session_id: str) -> int:
        """Return the LLM tokens spent in this session so far."""
        self._own_session(session_id)
        total = 0
        for usage in self._db.scalars(
            select(m.Message.usage).where(
                m.Message.session_id == session_id, m.Message.usage.is_not(None)
            )
        ):
            if usage is not None:
                total += int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        return total

    ## Guide 8.5: pending confirmations (agent/loop.py).
    def get_pending_tool_calls(self, session_id: str) -> dict[str, Any] | None:
        """Return the tool calls waiting for the user's confirmation, if any."""
        return self._own_session(session_id).pending_tool_calls

    ## Guide 8.5: set or clear the pending confirmations.
    def set_pending_tool_calls(self, session_id: str, pending: dict[str, Any] | None) -> None:
        """Store (or clear, with None) the tool calls waiting for confirmation."""
        self._own_session(session_id).pending_tool_calls = pending

    # ---- reports -------------------------------------------------------------------
    ## Guide 10.3: store a rendered report (jobs/report_task.py).
    def save_report(self, report: ReportRecord) -> None:
        """Store the record of a rendered report owned by the caller."""
        if report.session_id is not None:
            self._own_session(report.session_id)
        self._db.add(
            m.Report(
                id=report.report_id,
                owner_id=self._p.id,
                session_id=report.session_id,
                verification_ref=report.verification_ref,
                narrative=report.narrative,
                path=report.path,
                expires_at=report.expires_at,
            )
        )

    ## Guide 10.3: read a report (the download endpoint).
    def get_report(self, report_id: str) -> dict[str, Any]:
        """Return the caller's report record (NotFound for anyone else)."""
        r = self._db.get(m.Report, report_id)
        if r is None or r.owner_id != self._p.id:
            raise NotFound("Report not found.")
        return {
            "report_id": r.id,
            "verification_ref": r.verification_ref,
            "path": r.path,
            "expires_at": r.expires_at,
            "narrative": r.narrative,
            "reviewed_at": r.reviewed_at,
        }

    ## Report review (tool report.publish.v1): mark the caller's report as
    ## checked by the agent; from then on its download link works.
    def publish_report(self, report_id: str, review: str) -> dict[str, Any]:
        """Record the review of the caller's report and return the record."""
        r = self._db.get(m.Report, report_id)
        if r is None or r.owner_id != self._p.id:
            raise NotFound("Report not found.")
        r.review = review
        r.reviewed_at = datetime.now(UTC)
        self._db.flush()
        return self.get_report(report_id)


class AuthRepository:
    """Lookups that happen BEFORE a principal exists.

    Keep this class tiny: every method here bypasses the ownership rule, so
    each one needs a reason.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def find_principal_by_key_hash(self, key_hash: str) -> Principal | None:
        """Return the principal of an API key, or None if unknown or revoked.

        Used by mcp_server/auth.py for every request. The caller hashes the
        presented key; we look up the hash (indexed, unique). Revoked keys
        behave exactly like unknown keys.
        """
        row = self._db.scalars(select(m.ApiKey).where(m.ApiKey.key_hash == key_hash)).first()
        if row is None or row.revoked:
            return None
        return Principal.model_validate(
            {"id": row.owner_id, "kind": row.kind, "scopes": frozenset(row.scopes.split())}
        )

    def create_api_key(self, owner: str, kind: str, key_hash: str, scopes: str = "") -> str:
        """Store a new key's hash and return the key's id (not the key itself).

        Used by `te-platform keys create` (cli.py), the only place that
        ever sees the plain key.
        """
        kid = uuid4().hex
        self._db.add(m.ApiKey(id=kid, owner_id=owner, kind=kind, key_hash=key_hash, scopes=scopes))
        return kid

    def revoke_api_key(self, key_hash: str) -> bool:
        """Flag a key as revoked; return False if no such key exists.

        Used by `te-platform keys revoke` (cli.py). The row is kept, so the
        audit log still shows who used the key before.
        """
        row = self._db.scalars(select(m.ApiKey).where(m.ApiKey.key_hash == key_hash)).first()
        if row is None:
            return False
        row.revoked = True
        return True

    ## Guide 9.0: a person who may log in to the chat (cli.py users create).
    def create_user(self, email: str, access_code_hash: str) -> str:
        """Create a user who logs in with this access code hash; return the user id."""
        uid = uuid4().hex
        self._db.add(m.User(id=uid, email=email, access_code_hash=access_code_hash))
        return uid

    ## Guide 9.0: the login lookup. The user typed their access code; we
    ## compare HASHES (the plain code is never stored). Disabled users
    ## cannot log in.
    def find_user_by_access_code_hash(self, code_hash: str) -> Principal | None:
        """Return the principal of the user with this access code hash, or None."""
        user = self._db.scalars(select(m.User).where(m.User.access_code_hash == code_hash)).first()
        if user is None or user.disabled:
            return None
        return Principal(id=user.id, kind="user")


## Guide 11.1: the curated literature collection. There is no principal, on
## purpose: the collection is curated by the operator (`te-platform lit
## ingest`) and is the SAME for every user, so there is no per-user data to
## filter. Its queries still live here, so db/repo.py stays the only code
## that queries the database.
class LiteratureRepository:
    """Reads and writes of the shared literature collection (guide 11.1-11.2)."""

    ## Guide 11.1: the constructor.
    def __init__(self, db: Session) -> None:
        self._db = db

    ## Guide 11.1: store one paper (a `works` row) and its passages.
    ## `metadata` holds the Work columns except id and created_at
    ## (citation_key, title, authors, year, venue, doi, licence,
    ## full_text_allowed).
    def add_work(self, metadata: dict[str, Any], chunks: Sequence[Chunk]) -> str:
        """Store one paper and its passages; return the new work id."""
        work_id = uuid4().hex
        self._db.add(m.Work(id=work_id, **metadata))
        # flush() sends the INSERT for the work NOW. Without it, SQLAlchemy
        # may send the chunk INSERTs first (the models declare a foreign key
        # but no relationship(), so it does not know the order matters), and
        # PostgreSQL rejects chunks whose work does not exist yet. Found by
        # running the ingestion against a real database.
        self._db.flush()
        self._db.add_all(
            m.Chunk(work_id=work_id, section=c.section, page=c.page, text=c.text) for c in chunks
        )
        return work_id

    ## Guide 11.1: the size of the collection (the recall test skips when empty).
    def count_works(self) -> int:
        """Return how many papers the collection holds."""
        return int(self._db.scalar(select(func.count()).select_from(m.Work)) or 0)

    ## Guide 11.2: full-text search (literature/search.py). The query is a
    ## bound parameter, never pasted into SQL text, so it cannot inject SQL.
    ## websearch_to_tsquery understands "quoted phrases", OR and -excluded
    ## words, and never raises on odd input; ts_rank_cd ranks passages where
    ## the words appear close together higher.
    ## All the words must match (websearch_to_tsquery joins them with AND),
    ## so a longer query often finds nothing. Then the search is repeated
    ## with ANY of the words (the same lexemes joined with OR), ranked so
    ## that passages matching more of them come first.
    def search_passages(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Return the best-matching passages with their paper's citation data."""
        rows = self._passages(func.websearch_to_tsquery("english", query), limit)
        if rows:
            return rows
        words = func.cast(func.plainto_tsquery("english", query), Text)
        return self._passages(func.to_tsquery("english", func.replace(words, "&", "|")), limit)

    def _passages(self, tsq: Any, limit: int) -> list[dict[str, Any]]:
        rank = func.ts_rank_cd(m.Chunk.tsv, tsq)
        stmt = (
            select(m.Chunk.text, m.Work, rank.label("score"))
            .join(m.Work, m.Work.id == m.Chunk.work_id)
            .where(m.Chunk.tsv.op("@@")(tsq))  # "@@" = "matches the query"
            .order_by(rank.desc())
            .limit(limit)
        )
        return [
            {
                "citation_key": w.citation_key,
                "title": w.title,
                "authors": w.authors,
                "year": w.year,
                "venue": w.venue,
                "doi": w.doi,
                "text": text,
                "score": float(score),
            }
            for text, w, score in self._db.execute(stmt).all()
        ]
