## =============================================================================
## te_platform/db/models.py — the database tables, as Python classes
## =============================================================================
## GUIDE STEP   5.2 (identity, sessions, specs, verifications, audit),
##              6.2 (jobs), 8.5 (messages), 10.3 (reports),
##              11.1 (works, chunks), 11.2 (the chunks search column),
##              11.3 (optional embedding column, described in comments only)
## PURPOSE      Each class below is one table (architecture §3.8). SQLAlchemy's
##              ORM ("object-relational mapper") turns rows into Python
##              objects and back. Alembic (migrations/) reads these classes to
##              generate the SQL that creates the tables.
## USED BY      db/repo.py (the ONLY code that queries them),
##              migrations/env.py (Base.metadata), tests.
## DEPENDS ON   sqlalchemy >= 2.0 (typed style: Mapped[...] + mapped_column).
## WHY          D11: relational tables for things that need transactions and
##              ownership (sessions, jobs, audit), JSONB columns for documents
##              whose shape is owned by Pydantic models elsewhere (specs,
##              verifier results), full-text search for literature, all in one
##              database. P5 (provenance): spec_versions, answers,
##              verifications, messages and audit_log are APPEND-ONLY: rows
##              are inserted, never updated or deleted by the application
##              (repo.py simply has no function for it). History is evidence.
## TIME         Every timestamp column is `timestamp with time zone` (the
##              DateTime(timezone=True) entry of Base.type_annotation_map), and
##              the application sets times with the DATABASE's clock
##              (func.now()), so all times come from one clock and carry their
##              time zone.
## ACTIVATE     Each table is activated at the guide step that needs it (the
##              "## Phase X.Y" labels below; tables of later steps are commented
##              twice). After each change: `alembic revision --autogenerate`,
##              REVIEW the generated script, `alembic upgrade head`
##              (migrations/README.md).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep class, table and
## column names exactly as in the SOLUTION: repo.py and the migrations use
## them. Write one table at a time, as phases need it.
##
## Guide 5.2 (first: the `db` extra installed and the postgres service
## running, guide 5.1)
## [ ] 1. Imports at the top: datetime, Any and ClassVar; from sqlalchemy:
##        DateTime, ForeignKey, String, Text, false, func, text; JSONB from
##        sqlalchemy.dialects.postgresql; DeclarativeBase, Mapped and
##        mapped_column from sqlalchemy.orm.
## [ ] 2. `class Base(DeclarativeBase)` whose type_annotation_map stores
##        dict[str, Any] / list[Any] fields as JSONB and datetime fields as
##        timestamps WITH time zone (header TIME):
##          | type_annotation_map: ClassVar[dict[Any, Any]] = {
##          |     dict[str, Any]: JSONB, list[Any]: JSONB,
##          |     datetime: DateTime(timezone=True)}
## [ ] 3. Helper `_created_at() -> Mapped[datetime]` returning
##        mapped_column(server_default=func.now()) (the database's clock).
## [ ] 4. `User` ("users"): id (String(64), primary key), email (unique),
##        access_code_hash (nullable, unique), disabled, created_at. Give
##        booleans a database default as well:
##          | mapped_column(default=False, server_default=false())
## [ ] 5. `ApiKey` ("api_keys"): id, owner_id (indexed, NOT a foreign key:
##        keys belong to programs, not users), kind, key_hash (unique,
##        indexed), scopes (String(256), default ""), revoked, created_at.
## [ ] 6. `DesignSession` ("sessions"): id, owner_id (indexed),
##        protocol_version, policy_version, pending_tool_calls (nullable
##        JSONB, the only mutable column), created_at.
## [ ] 7. The append-only tables. `SpecVersion` ("spec_versions"): the pair
##        (session_id -> sessions.id, version) is the primary key, plus
##        spec, spec_hash (String(80), indexed), author, created_at.
##        `Answer` ("answers"): autoincrement id, session_id (foreign key,
##        indexed), slot_id, indices (JSONB, server default '[]'), value,
##        status, user_quote, spec_version, created_at. `Verification`
##        ("verifications"): verification_ref IS the primary key, spec_hash
##        (indexed), result, created_at.
## [ ] 8. `AuditEntry` ("audit_log"): autoincrement id, principal_id
##        (indexed), tool_id, input_hash, outcome, latency_ms,
##        override_reason (nullable Text), correlation_id (indexed),
##        created_at.
## [ ] 9. Check: `uv run mypy te_platform`; the migration is generated and
##        applied at guide 5.3 (migrations/README.md).
##
## Later tables (same pattern; after each one: autogenerate a migration,
## REVIEW it, upgrade, as in migrations/README.md)
## [ ] 10. Guide 6.2: `Job` ("jobs"): id String(80) (the RQ job id),
##         owner_id (indexed), session_id (nullable, indexed), kind,
##         verification_ref (indexed), params, status (default "queued"),
##         result (nullable), created_at, finished_at (nullable).
## [ ] 11. Guide 8.5: `Message` ("messages"): autoincrement id, session_id
##         (foreign key, indexed), role, content typed Mapped[Any] with an
##         explicit JSONB (it can be a dict or a list), usage (nullable),
##         created_at.
## [ ] 12. Guide 10.3: `Report` ("reports"): id, owner_id (indexed),
##         session_id (nullable), verification_ref, narrative, path (Text),
##         expires_at, created_at.
## [ ] 13. Guide 11.1: `Work` ("works"): id, citation_key (unique), title,
##         authors, year, venue, doi (nullable), licence,
##         full_text_allowed, created_at. `Chunk` ("chunks"): autoincrement
##         id, work_id (foreign key to works.id, indexed), section (default
##         ""), page, text.
## [ ] 14. Guide 11.2: import TSVECTOR (sqlalchemy.dialects.postgresql.types)
##         and Computed, Index (sqlalchemy.schema), then add to
##         Chunk the generated search column
##          | tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(
##          |     "to_tsvector('english', text)", persisted=True))
##         and a GIN index "ix_chunks_tsv" on tsv in __table_args__. In the
##         migration check that Computed and postgresql_using="gin" appear
##         (migrations/README.md step 4).
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, ForeignKey, String, Text, false, func, text
from sqlalchemy.dialects.postgresql import JSONB

## Phase 11.2: the type of the generated search column of `chunks`.
from sqlalchemy.dialects.postgresql.types import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

## Phase 11.2: the generated search column and its index.
from sqlalchemy.schema import Computed, Index


## --- Base class -----------------------------------------------------------------
## Every table class inherits from Base. Base.metadata collects all tables;
## Alembic compares it with the real database to write migrations.
## `type_annotation_map` tells SQLAlchemy which column type to use for a
## Python annotation: dict[str, Any] and list[Any] are stored as PostgreSQL
## JSONB (binary JSON: indexable, validated on insert), and every datetime
## as `timestamp with time zone` (header TIME). ClassVar: it is a setting of
## the class, not a column.
class Base(DeclarativeBase):
    """Common base of every table class (it owns Base.metadata)."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        datetime: DateTime(timezone=True),
    }


## A reusable column definition: "created_at defaults to the database's
## current time". server_default=func.now() lets PostgreSQL set it, so the
## clock of the database (one clock) is used, not each container's clock.
def _created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


## --- Identity (phase 5.2) -------------------------------------------------------
class User(Base):
    """A person who may log in to the chat (guide 9.0).

    Programs using API keys are NOT users; they appear only as
    api_keys.owner_id.
    """

    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # Login (guide 9.0): SHA-256 hash of the user's personal access code,
    # like API keys; the plain code is shown once by `te-platform users create`.
    access_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # server_default: the DATABASE fills the default too, so rows inserted
    # outside the application (psql, a migration, a repair script) are valid.
    disabled: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = _created_at()


class ApiKey(Base):
    """One API key; only its SHA-256 HASH is stored (guide 4.2).

    A stolen database therefore does not reveal usable keys. The plain key
    is shown once by `te-platform keys create` and never again.
    """

    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # The principal id the key authenticates as (e.g. "partner-lab", or
    # "agent" for our service). NOT a foreign key to users: API keys belong
    # to programs, which are not chat users (found when checking that
    # `te-platform keys create --owner partner-lab` must work without a
    # matching users row).
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    # "api_key" for external programs, "service" for our own agent service;
    # becomes Principal.kind (registry/context.py).
    kind: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Space-separated scopes ("verify sim"); empty = all tools (pipeline step 1).
    scopes: Mapped[str] = mapped_column(String(256), default="", server_default="")
    revoked: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = _created_at()


## --- Sessions and specs (phase 5.2) -----------------------------------------------
class DesignSession(Base):
    """One design conversation.

    Named DesignSession, not Session, so it is never confused with
    SQLAlchemy's database Session. The session STATE is not stored:
    registry/state.py derives it.
    """

    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)  # Principal.id
    protocol_version: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(32))
    # Tool calls the agent is waiting to run until the user confirms them
    # (expensive tools, agent/loop.py, guide 8.5). NULL when nothing is
    # pending. This is the only mutable column of the session: the
    # confirmation is a short-lived conversational state, not part of the
    # design history.
    pending_tool_calls: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created_at()


class SpecVersion(Base):
    """APPEND-ONLY: one row per change to a session's spec.

    Every change (answer recorded, form saved, YAML uploaded) adds a row
    with the next version number.
    """

    __tablename__ = "spec_versions"
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    spec: Mapped[dict[str, Any]]
    spec_hash: Mapped[str] = mapped_column(String(80), index=True)
    author: Mapped[str] = mapped_column(String(16))  # "user" | "agent" | "form"
    created_at: Mapped[datetime] = _created_at()


class Answer(Base):
    """APPEND-ONLY: one answer to one protocol slot, with the user's own words.

    Keeping the words is provenance (P5). A correction is a NEW row; the
    latest row per slot wins.
    """

    __tablename__ = "answers"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    slot_id: Mapped[str] = mapped_column(String(128))
    # Which token (or other list element) a per-token slot is about, e.g. [1]
    # for the second token; [] for slots that are not per-token.
    indices: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # {"value": ...}: the wrapper keeps the JSONB column a mapping even when
    # the answer itself is a number or a string.
    value: Mapped[dict[str, Any]]
    # "committed" | "estimated" | "unknown" | "default"
    status: Mapped[str] = mapped_column(String(16))
    user_quote: Mapped[str] = mapped_column(Text, default="")
    spec_version: Mapped[int]
    created_at: Mapped[datetime] = _created_at()


class Verification(Base):
    """APPEND-ONLY and content-addressed: the primary key IS the verification_ref.

    The ref is computed by hashing.py. The same spec verified by the same
    verifier with the same config always gives the same row, so it is
    stored once and reused (D5).
    """

    __tablename__ = "verifications"
    verification_ref: Mapped[str] = mapped_column(String(80), primary_key=True)
    spec_hash: Mapped[str] = mapped_column(String(80), index=True)
    # JSONB stores numbers as exact decimals: a float without a fractional
    # part (e.g. 5.457e31) comes back as a Python int. The values are equal,
    # only the types may differ; compare numbers by value, not by type.
    result: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = _created_at()


## --- Audit log (phase 5.2, written from guide 5.5) -------------------------------------
class AuditEntry(Base):
    """APPEND-ONLY: one row per tool call (pipeline step 8).

    It stores a HASH of the input, not the input itself: enough to detect
    repeats and match reports, without copying user data into a second
    place.
    """

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    principal_id: Mapped[str] = mapped_column(String(64), index=True)
    tool_id: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(32))  # "ok" or an ErrorCode value
    latency_ms: Mapped[int]
    override_reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = _created_at()


## --- Jobs ---------------------------------------------------------------------------------
## Phase 6.2: the jobs table (simulation results are stored per user). NOT
## append-only: the status moves queued -> finished | failed | cancelled
## once, when the job ends (jobs/queue.py settle_job); RQ, not this table,
## knows whether a job is running right now.
class Job(Base):
    """One background job (a simulation or a report rendering)."""

    ## Phase 6.2: the columns of the jobs table.
    __tablename__ = "jobs"
    # 80, not 64: content-based job ids are "job-" + 64 hex characters
    # (jobs/queue.py), like spec_hash / verification_ref.
    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # same id as the RQ job
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # "monte_carlo" | "trajectory" | "experiment" | "report"
    kind: Mapped[str] = mapped_column(String(16))
    verification_ref: Mapped[str] = mapped_column(String(80), index=True)
    params: Mapped[dict[str, Any]]
    status: Mapped[str] = mapped_column(String(16), default="queued")
    result: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None]


## --- Chat transcript ---------------------------------------------------------------------
## Phase 8.5: the messages table (the SSE endpoint stores the transcript).
## APPEND-ONLY. `content` keeps the provider's full content blocks (text,
## tool calls, thinking blocks), because the Anthropic API requires earlier
## assistant content to be sent back unchanged on the next turn
## (agent/loop.py).
class Message(Base):
    """One message of the chat, or one token-usage record."""

    ## Phase 8.5: the columns of the messages table.
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant" | "usage"
    # The full provider message ({"role": ..., "content": [...]}) for chat
    # rows; {} for "usage" rows. `Any` + explicit JSONB because the value can
    # be a dict or a list, which the annotation map cannot express.
    content: Mapped[Any] = mapped_column(JSONB)
    usage: Mapped[dict[str, Any] | None]  # token counts, for budgets and cost
    created_at: Mapped[datetime] = _created_at()


## --- Reports ------------------------------------------------------------------------------
## Phase 10.3: the reports table (the report tool and the download endpoint).
class Report(Base):
    """One rendered PDF report and the narrative it was rendered from."""

    ## Phase 10.3: the columns of the reports table.
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64))
    verification_ref: Mapped[str] = mapped_column(String(80))
    narrative: Mapped[dict[str, Any]]  # the agent's labelled text sections
    path: Mapped[str] = mapped_column(Text)  # file under Settings.report_storage_dir
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = _created_at()
    # The agent's review (tool report.publish.v1): the download link works
    # only once the agent has read the rendered report and confirmed it is
    # correct. None = still a draft.
    reviewed_at: Mapped[datetime | None]
    review: Mapped[str | None] = mapped_column(Text)


## --- Literature ---------------------------------------------------------------------------
## Phase 11.1: the curated collection: one row per paper.
class Work(Base):
    """One paper of the curated collection."""

    ## Phase 11.1: the columns of the works table.
    __tablename__ = "works"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    citation_key: Mapped[str] = mapped_column(String(128), unique=True)
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None]
    venue: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(256))
    licence: Mapped[str] = mapped_column(String(64))
    # False = only metadata and abstract may be stored/served (architecture §3.7).
    full_text_allowed: Mapped[bool]
    created_at: Mapped[datetime] = _created_at()


## Phase 11.1: the passages of each paper, the unit of search results.
class Chunk(Base):
    """A short passage of a work."""

    ## Phase 11.1: the columns of the chunks table.
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    section: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[int | None]
    text: Mapped[str] = mapped_column(Text)

    ## Phase 11.2: a GENERATED column. PostgreSQL computes it from `text`
    ## on every insert or update, so it can never be out of date.
    ## to_tsvector('english', ...) reduces words to stems ("tokens" ->
    ## "token") and drops stop words; persisted=True stores it (needed to
    ## index it). The GIN index makes "which rows contain these words?"
    ## fast instead of a scan of every chunk.
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )
    __table_args__ = (Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),)

    ## Phase 11.3 (only if keyword search is not good enough): an embedding
    ## column from pgvector, e.g.
    ##   from pgvector.sqlalchemy import Vector
    ##   embedding: Mapped[Any | None] = mapped_column(Vector(384))
