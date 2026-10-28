## =============================================================================
## te_platform/db/__init__.py — the persistence package (PostgreSQL)
## =============================================================================
## GUIDE STEP   5.2-5.5
## PURPOSE      Marks db/ as a package. Everything that touches the database
##              lives here, and nowhere else:
##
##                models.py   — the tables, as Python classes (SQLAlchemy ORM)
##                session.py  — how to connect (engine) and open a transaction
##                repo.py     — the ONLY functions that read/write rows; every
##                              one of them filters by the caller (Principal)
##                migrations/ — Alembic scripts that create/alter the tables
##
##              How the files relate (arrows = "uses"):
##
##                repo.py ──► models.py, session.py (via the caller)
##                migrations/env.py ──► models.py (Base.metadata)
##                session.py ──► config.py (database URL)
##
##              Callers outside: registry/pipeline.py (audit log, session
##              facts), mcp_server/ (session facts, API keys), agent/ (messages),
##              jobs/ (job rows), reports/ (report rows), literature/
##              (works/chunks, through LiteratureRepository), cli.py (create
##              API keys).
## WHY          Architecture D11 (PostgreSQL only) and guide §2.2 / 5.4
##              (authorisation in exactly one place: the repository layer).
## ACTIVATE     Nothing to uncomment here; keep the file (it makes the package).
## =============================================================================
