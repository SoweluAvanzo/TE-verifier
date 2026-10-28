## =============================================================================
## te_platform/cli.py — the `te-platform` administration command
## =============================================================================
## GUIDE STEP   4.2 (keys create), 5.4 (db check, keys stored in the
##              database, keys revoke), 9.0 (users create), 11.1 (lit ingest)
## PURPOSE      Administration tasks run by YOU on the server (or in a
##              container: `docker compose run --rm mcp te-platform ...`),
##              never by users or by the agent:
##                te-platform keys create --owner NAME [--kind api_key|service]
##                te-platform keys revoke --key-hash HASH
##                te-platform users create --email ADDRESS
##                te-platform lit ingest PAPER.pdf --bib ENTRY.bib
##                    --licence "CC-BY-4.0" [--full-text-allowed]
##                te-platform db check
## USED BY      You. Declared in pyproject.toml [project.scripts] as te-platform.
## DEPENDS ON   argparse (standard library), security/api_keys.py; from 5.4
##              db/session.py and db/repo.py (AuthRepository); from 11.1
##              literature/ingest.py.
## WHY          Keys and the literature collection are managed by a curator
##              through deliberate commands (architecture D15), not through a
##              public endpoint that could be abused. argparse instead of a
##              third-party CLI library: no extra dependency, and the existing
##              `te-verify` command uses it too.
## ACTIVATE     4.2: uncomment the file (main, the parser, _keys_create).
##              Every later sub-command is commented twice under a
##              "## Guide X.Y" line: its imports at the top, its function,
##              and its lines in _build_parser. Toggle all three again at
##              that step. At 5.4, also DELETE the phase-4 lines of
##              _keys_create (see the TO-DO, step 9).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run each "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. The command and option
## names below are used in the guide and in .env.example: keep them exactly.
## Activate security/api_keys.py first.
##
## Guide 4.2
## [ ] 1. Declare the command: copy `te-platform = "te_platform.cli:main"`
##        from the [project.scripts] section of pyproject_additions.toml
##        into ../pyproject.toml, then `uv sync --all-extras`.
## [ ] 2. Imports at the top: `argparse`, `sys`, and
##          | from te_platform.security import api_keys
##        (the module: the code calls api_keys.generate_api_key(), and
##        api_keys.generate_access_code() from 9.0, with no import change).
## [ ] 3. `_keys_create(args: argparse.Namespace) -> int`: call
##        api_keys.generate_api_key(); then the PHASE-4 lines: the
##        principal id (prefix "service:" when --kind is service, see
##        mcp_server/auth.py) and the line to add to TE_API_KEY_HASHES:
##          | principal_id = (f"service:{args.owner}"
##          |                 if args.kind == "service" else args.owner)
##        Last, print the plain key once and return 0. Never print or log
##        the plain key anywhere else.
## [ ] 4. `_build_parser() -> argparse.ArgumentParser` (prog "te-platform"):
##        sub-parsers with dest="group" and then dest="action", both
##        required. Group "keys", action "create" with --owner (required)
##        and --kind (choices api_key/service, default api_key);
##        create.set_defaults(func=_keys_create).
## [ ] 5. `main(argv: list[str] | None = None) -> int` with a docstring:
##        parse, then `return int(args.func(args))`; at the bottom the
##        usual `if __name__ == "__main__": sys.exit(main())`.
## [ ] 6. Check: `uv run mypy te_platform`, then
##          | uv run te-platform keys create --owner test
##        prints a `"<hash>": "test"` line and a "te_..." key.
##
## Guide 5.4 (needs db/session.py and db/repo.py AuthRepository)
## [ ] 7. Imports at the top, in the first-party group before the
##        api_keys import: AuthRepository (te_platform.db.repo) and
##        session_scope (te_platform.db.session).
## [ ] 8. `_db_check(_args) -> int`: in a session_scope(), run
##          | db.connection().exec_driver_sql("SELECT 1")
##        then print "database: ok". The argument is named `_args`:
##        argparse passes it, the command does not use it. Parser: group
##        "db", action "check".
## [ ] 9. In _keys_create, store the hash instead:
##          | with session_scope() as db:
##          |     AuthRepository(db).create_api_key(
##          |         owner=args.owner, kind=args.kind, key_hash=key_hash)
##        and DELETE the phase-4 lines (the block under "## Phase 4.2
##        only", from `principal_id = ...` to the TE_API_KEY_HASHES print):
##        from 5.4 the MCP server reads keys from the api_keys table, so
##        that advice would be wrong.
## [ ] 10. `_keys_revoke(args) -> int`: revoke_api_key(args.key_hash),
##        print "revoked" or "no such key", return 0 or 1. Parser: action
##        "revoke" under "keys", with --key-hash (required).
## [ ] 11. Check: `uv run te-platform db check` with the database running;
##        create a key, revoke it by its hash: a request to the MCP server
##        with that key then gets 401.
##
## Guide 9.0
## [ ] 12. `_users_create(args) -> int`: api_keys.generate_access_code(),
##        then AuthRepository(db).create_user(email=..., access_code_hash=
##        ...); print the user id and the code once. Parser: group
##        "users", action "create", --email (required).
##
## Guide 11.1
## [ ] 13. Imports at the top: `import pathlib` (between argparse and sys)
##        and, as the LAST import, the relative import
##          | from .literature.ingest import ingest_pdf
##        (the SOLUTION's `##` note says why it is relative).
## [ ] 14. `_lit_ingest(args) -> int`: call
##          | ingest_pdf(pathlib.Path(args.pdf), pathlib.Path(args.bib),
##          |            args.licence, full_text_allowed=args.full_text_allowed)
##        then print the work id. Parser: group "lit", action "ingest":
##        positional `pdf`, --bib, --licence (both required),
##        --full-text-allowed (action="store_true").
## [ ] 15. Check after each group: `uv run mypy te_platform` and run the
##        new command once.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import argparse

## Guide 11.1: Path objects for `lit ingest`.
import pathlib
import sys

## Guide 5.4: the database commands.
from te_platform.db.repo import AuthRepository
from te_platform.db.session import session_scope
from te_platform.security import api_keys

## Guide 11.1: relative import ("." = the te_platform package), so that it
## sorts AFTER the absolute imports above: ruff's import sorting then
## accepts every step's set of active lines without reordering them.
from .literature.ingest import ingest_pdf


## --- keys create ---------------------------------------------------------------
def _keys_create(args: argparse.Namespace) -> int:
    plain, key_hash = api_keys.generate_api_key()
    ## Guide 5.4: store the hash in the api_keys table (the kind is a column
    ## there, so the owner needs no prefix).
    with session_scope() as db:
        AuthRepository(db).create_api_key(owner=args.owner, kind=args.kind, key_hash=key_hash)
    print("API key (shown ONCE, only its hash is kept; give it to the client now):")
    print(f"  {plain}")
    return 0


## --- db check --------------------------------------------------------------------
## Guide 5.4: connect and run `SELECT 1`. Useful right after deploying
## (guide 12.2). argparse passes the parsed arguments; this command uses none.
def _db_check(_args: argparse.Namespace) -> int:
    with session_scope() as db:
        db.connection().exec_driver_sql("SELECT 1")
    print("database: ok")
    return 0


## --- keys revoke -----------------------------------------------------------------
## Guide 5.4: marks the key as revoked in the api_keys table; the MCP server
## refuses it from the next request on.
def _keys_revoke(args: argparse.Namespace) -> int:
    with session_scope() as db:
        found = AuthRepository(db).revoke_api_key(args.key_hash)
    print("revoked" if found else "no such key")
    return 0 if found else 1


## --- users create ------------------------------------------------------------------
## Guide 9.0: a person who may log in to the chat. Their access code is
## printed ONCE; send it to them through a trusted channel (not in the same
## e-mail as the address of the site, if you can avoid it).
def _users_create(args: argparse.Namespace) -> int:
    plain, code_hash = api_keys.generate_access_code()
    with session_scope() as db:
        uid = AuthRepository(db).create_user(email=args.email, access_code_hash=code_hash)
    print(f"User {args.email} created (id {uid}).")
    print(f"Access code (shown ONCE, only its hash is stored):\n  {plain}")
    return 0


## --- lit ingest ----------------------------------------------------------------------
## Guide 11.1: add one paper to the collection. argparse hands over plain
## strings; ingest_pdf() expects Path objects (found by running the command:
## the type checker cannot see it, because argparse results are untyped).
def _lit_ingest(args: argparse.Namespace) -> int:
    work_id = ingest_pdf(
        pathlib.Path(args.pdf),
        pathlib.Path(args.bib),
        args.licence,
        full_text_allowed=args.full_text_allowed,
    )
    print(f"Ingested as work {work_id}. Review the extracted chunks before relying on them.")
    return 0


## --- Parser ------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="te-platform",
        description="Administration of the agent platform.",
    )
    sub = parser.add_subparsers(dest="group", required=True)
    keys = sub.add_parser("keys", help="API keys").add_subparsers(dest="action", required=True)
    create = keys.add_parser("create", help="create a key (printed once)")
    create.add_argument("--owner", required=True, help="who the key is for, e.g. 'partner-lab'")
    create.add_argument(
        "--kind",
        choices=["api_key", "service"],
        default="api_key",
        help="'service' only for our own agent service",
    )
    create.set_defaults(func=_keys_create)
    ## Guide 5.4: te-platform db check
    db = sub.add_parser("db", help="database").add_subparsers(dest="action", required=True)
    db.add_parser("check", help="test the connection").set_defaults(func=_db_check)
    ## Guide 5.4: te-platform keys revoke --key-hash HASH
    revoke = keys.add_parser("revoke", help="revoke a key by its hash")
    revoke.add_argument(
        "--key-hash", required=True, help="the SHA-256 hash printed when it was created"
    )
    revoke.set_defaults(func=_keys_revoke)
    ## Guide 9.0: te-platform users create --email ADDRESS
    users = sub.add_parser("users", help="people who may log in").add_subparsers(
        dest="action", required=True
    )
    ucreate = users.add_parser("create", help="create a user; prints their access code once")
    ucreate.add_argument("--email", required=True)
    ucreate.set_defaults(func=_users_create)
    ## Guide 11.1: te-platform lit ingest PAPER.pdf --bib ENTRY.bib --licence ...
    lit = sub.add_parser("lit", help="literature collection").add_subparsers(
        dest="action", required=True
    )
    ingest = lit.add_parser("ingest", help="add one paper")
    ingest.add_argument("pdf", help="the paper's PDF file")
    ingest.add_argument("--bib", required=True, help="BibTeX file with this paper's entry")
    ingest.add_argument(
        "--licence", required=True, help="e.g. 'CC-BY-4.0' or 'all rights reserved'"
    )
    ingest.add_argument(
        "--full-text-allowed",
        action="store_true",
        help="only if the licence allows storing and quoting the full text",
    )
    ingest.set_defaults(func=_lit_ingest)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one administration command; return its exit code (0 = success)."""
    args = _build_parser().parse_args(argv)
    return int(args.func(args))  # each sub-command returns its exit code


if __name__ == "__main__":
    sys.exit(main())
