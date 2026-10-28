## =============================================================================
## te_platform/db/migrations/env.py — how Alembic connects and what it compares
## =============================================================================
## GUIDE STEP   5.3 (12.2 adds the rollback check: skip_if_newer)
## PURPOSE      Alembic runs this file for every command (upgrade, downgrade,
##              revision --autogenerate). It must answer two questions:
##              1. WHERE is the database?  -> Settings.migration_database_url
##                 (the te_migrator role, which owns the schema);
##              2. WHAT should exist?      -> Base.metadata from db/models.py
##                 (autogenerate diffs it against the real database).
##              Alembic's other standard files (script.py.mako, versions/)
##              are shipped next to it, so `alembic init` is never needed
##              (see README.md in this folder).
## USED BY      the `alembic` command only (the `migrate` Compose service, which
##              gets the URL as the secret file te_migration_database_url;
##              CI and your shell, with TE_MIGRATION_DATABASE_URL).
## DEPENDS ON   alembic, sqlalchemy, te_platform.config, te_platform.db.models.
## WHY          The URL comes from the environment, never from alembic.ini, so
##              no password is committed (guide §2.2). Migrations use a
##              different role from the application (guide 5.1, D11).
## ACTIVATE     Review and uncomment (guide 5.3), together with
##              ../alembic.ini.template copied to ../alembic.ini.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code.
##
## Guide 5.3 (first: config.py and db/models.py active; copy
## ../alembic.ini.template to ../alembic.ini at the same time)
## [ ] 1. Imports at the top: fileConfig (logging.config), context
##        (alembic), create_engine and pool (sqlalchemy), get_settings, and
##        Base from te_platform.db.models. (No blank line before the
##        te_platform imports: this folder is not a package, so ruff counts
##        te_platform as a third-party library here and sorts it as one.)
## [ ] 2. Module level: `config = context.config`; if
##        config.config_file_name is not None, call fileConfig on it.
## [ ] 3. `target_metadata = Base.metadata` (what autogenerate compares).
## [ ] 4. `_url() -> str`: if Settings.migration_database_url is None,
##        raise RuntimeError asking for the migration URL (secret file
##        te_migration_database_url, or TE_MIGRATION_DATABASE_URL outside
##        Compose); else return its .get_secret_value(). Never fall back to
##        the app URL.
## [ ] 5. `run_migrations_offline()`: context.configure(url=_url(),
##        target_metadata=..., literal_binds=True, compare_type=True), then
##          | with context.begin_transaction():
##          |     context.run_migrations()
## [ ] 6. `run_migrations_online()`: create_engine(_url(),
##        poolclass=pool.NullPool), open a connection, context.configure
##        with connection=..., target_metadata and compare_type=True, then
##        the same transaction block as step 5.
## [ ] 7. At the bottom: run the offline function if
##        context.is_offline_mode(), else the online one.
## [ ] 8. Check: migrations/README.md steps 3-6 (autogenerate, review by
##        hand, upgrade head, downgrade -1, upgrade head), e.g.
##          | uv run alembic -c te_platform/db/alembic.ini upgrade head
##        and in Compose `docker compose run migrate` (guide 5.3).
##
## Guide 12.2 (rollbacks: production runs `migrate` with
## `-x skip_if_newer=true`, compose.prod.yml)
## [ ] 9. Two more imports: MigrationContext (alembic.migration) and
##        ScriptDirectory (alembic.script).
## [ ] 10. `_database_is_newer() -> bool`: False unless the x-argument
##        skip_if_newer is "true"; otherwise collect the revisions this
##        image knows, read the database's current revisions on a SEPARATE
##        short-lived connection (the SOLUTION says why), and report
##        (config.print_stdout) any that is not among them:
##          | known = {r.revision for r in
##          |          ScriptDirectory.from_config(config).walk_revisions()}
## [ ] 11. At the start of run_migrations_online(): return when
##        _database_is_newer().
## [ ] 12. Check: the rollback drill of docs/operations.md §2 (deploy a
##        release with a new migration, roll back: `migrate` prints the
##        newer revision and exits 0; without the flag it fails with
##        "Can't locate revision").
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

from logging.config import fileConfig

from alembic import context

## Guide 12.2: read the database's revision and this image's revisions.
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool
from te_platform.config import get_settings
from te_platform.db.models import Base

## `context.config` is the parsed alembic.ini. If it has logging sections,
## set up Python logging from them (Alembic prints what it does).
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

## The tables the code expects. Every table class must be IMPORTED (it is,
## through `models`) or autogenerate would think it should be dropped.
target_metadata = Base.metadata


def _url() -> str:
    """Return the migration role's database URL (Settings.migration_database_url)."""
    s = get_settings()
    # Migrations must run as the schema owner. Falling back to the app URL
    # would fail anyway (te_app has no DDL rights), so fail clearly instead.
    if s.migration_database_url is None:
        raise RuntimeError(
            "Set the te_migrator role's URL to run migrations: the secret file "
            "te_migration_database_url (Compose) or TE_MIGRATION_DATABASE_URL."
        )
    return s.migration_database_url.get_secret_value()


## Guide 12.2: rollbacks. After a rollback to an older image, the database
## already holds migrations that this image does not have, and `upgrade
## head` stops with "Can't locate revision": the `migrate` service would
## fail, and the services that wait for it would never start. Production
## passes `-x skip_if_newer=true` (compose.prod.yml): then this reports the
## newer revision and nothing runs. The older code works on the newer schema
## because migrations only add (docs/operations.md §1). Without the flag
## (development, CI, your shell) the error stays: there a newer database
## usually means you checked out an older branch.
## It reads the revision on its OWN connection, closed before migrating:
## a read on the migration connection would start a transaction there
## (SQLAlchemy 2 "autobegin"), Alembic would then run inside it without
## committing, and closing the connection would silently roll every
## migration back (found by the rollback drill).
def _database_is_newer() -> bool:
    """Return True if skip_if_newer is set and the database is newer than this image."""
    if context.get_x_argument(as_dictionary=True).get("skip_if_newer") != "true":
        return False
    known = {rev.revision for rev in ScriptDirectory.from_config(config).walk_revisions()}
    with create_engine(_url(), poolclass=pool.NullPool).connect() as connection:
        current = MigrationContext.configure(connection).get_current_heads()
    unknown = [rev for rev in current if rev not in known]
    if unknown:
        config.print_stdout(
            "Database revision %s is newer than this image (rollback): nothing to do.",
            ", ".join(unknown),
        )
    return bool(unknown)


def run_migrations_offline() -> None:
    """Print the SQL instead of running it ("offline" mode).

    `alembic upgrade head --sql` uses it: useful for reviewing exactly what
    a migration will do to production.
    """
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply the migrations (normal mode).

    NullPool: a migration is a one-off process, so no connection pool.
    compare_type=True: autogenerate also notices changed column TYPES.
    """
    ##     Guide 12.2: after a rollback, stop here (see _database_is_newer).
    if _database_is_newer():
        return
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
