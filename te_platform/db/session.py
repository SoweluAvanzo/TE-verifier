## =============================================================================
## te_platform/db/session.py — connecting to PostgreSQL and opening transactions
## =============================================================================
## GUIDE STEP   5.2
## PURPOSE      Two functions:
##              - get_engine(): the SQLAlchemy *engine*, i.e. the object that
##                knows the database address and keeps a *pool* of open
##                connections (opening a connection is slow; reusing is fast);
##              - session_scope(): a `with` block that gives you a Session (one
##                unit of work) and COMMITS it if the block ends normally, or
##                ROLLS IT BACK (undoes everything) if an exception is raised.
## USED BY      Every caller of db/repo.py: registry/pipeline.py,
##              mcp_server/app.py and auth.py, agent/, jobs/tasks.py,
##              literature/, cli.py, tests.
## DEPENDS ON   sqlalchemy (>= 2.0), psycopg 3 (the driver, selected by the
##              "postgresql+psycopg://" prefix of the URL), config.py.
## WHY          D11. A transaction per unit of work means a tool call either
##              stores everything (spec version + answer + audit row) or
##              nothing: no half-written sessions after a crash.
##              We use the SYNCHRONOUS SQLAlchemy API. Async code (FastAPI,
##              the MCP server) calls repository functions through
##              `anyio.to_thread.run_sync(...)`, which runs them in a worker
##              thread. This is acceptable because our queries are few and
##              short (milliseconds) next to the seconds spent in Z3 and the
##              LLM, and the sync API is simpler to learn, debug and test.
## ACTIVATE     Uncomment after the `db` extra is installed and the postgres
##              service runs (guide 5.1). Test (from guide 5.3, when the
##              tables exist): test_platform_db.py (connection works,
##              rollback on exception).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the names
## get_engine and session_scope exactly: many files import them.
##
## Guide 5.2 (first: config.py active, the `db` extra installed, the
## postgres service running, guide 5.1)
## [ ] 1. Imports at the top: Iterator (collections.abc), contextmanager
##        (contextlib), lru_cache (functools), Engine and create_engine
##        (sqlalchemy), Session and sessionmaker (sqlalchemy.orm), and
##        get_settings from te_platform.config.
## [ ] 2. `get_engine() -> Engine` with @lru_cache(maxsize=1) (one engine
##        per process): create_engine with the real URL
##          | settings.database_url.get_secret_value()
##        and pool_pre_ping=True, pool_size=settings.db_pool_size,
##        echo=settings.db_echo.
## [ ] 3. `_session_factory() -> sessionmaker[Session]`, also cached:
##        sessionmaker(bind=get_engine(), expire_on_commit=False).
## [ ] 4. `session_scope() -> Iterator[Session]` with @contextmanager:
##        create a Session, yield it, then commit; on any Exception roll
##        back and re-raise; in `finally` close it (back to the pool).
## [ ] 5. Check: `uv run mypy te_platform`. The database tests
##        (test_platform_db.py: connection works, rollback on exception)
##        run from guide 5.3 on, once the migration has created the tables.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from te_platform.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process's engine (one per process, created on first use).

    pool_pre_ping: before handing out a pooled connection, check it still
      works (the database may have restarted); avoids "connection closed"
      errors after maintenance.
    The URL is a SecretStr (config.py): .get_secret_value() reads the real
    string only here, so the password never appears in logs.
    """
    settings = get_settings()
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        # echo=True prints every SQL statement: handy while learning, far
        # too noisy (and potentially sensitive) in production.
        echo=settings.db_echo,
    )


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    """Return the factory that opens Sessions on the engine."""
    # expire_on_commit=False: objects keep their loaded values after commit,
    # so a repository can return data that is read after the `with` block.
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Open one unit of work: commit at the end, roll back on an exception.

    Usage:

        with session_scope() as db:
            repo = Repository(db, principal)
            repo.add_spec_version(...)
        # committed here, or rolled back if an exception escaped the block
    """
    db = _session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise  # re-raise: the pipeline turns it into a ToolError
    finally:
        db.close()  # return the connection to the pool
