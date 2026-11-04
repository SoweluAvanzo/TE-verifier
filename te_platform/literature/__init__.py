## =============================================================================
## te_platform/literature/__init__.py — the curated literature collection
## =============================================================================
## GUIDE STEP   11.1-11.3
## PURPOSE      Marks literature/ as a package. It holds the peer-reviewed
##              papers the agent may cite:
##
##                ingest.py   — add one paper (PDF + BibTeX) to the database;
##                              run by the curator through `te-platform lit ingest`
##                chunking.py — split a paper's text into short passages
##                search.py   — find passages for a question (PostgreSQL
##                              full-text search), used by tool lit.search.v1
##
##              How the files relate (arrows = "uses"):
##
##                ingest.py ──► chunking.py, db/repo.py (LiteratureRepository)
##                search.py ──► db/repo.py (LiteratureRepository)
##
##              Callers outside: cli.py (ingest), tools/lit_search.py (search).
## WHY          Architecture D15: curated ingestion (no uploads from end
##              users), short passages only on the public endpoint
##              (copyright), keyword search first, embeddings only if the
##              evaluation shows they are needed.
## ACTIVATE     Nothing to uncomment here; keep the file (it makes the package).
## =============================================================================
