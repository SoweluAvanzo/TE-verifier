---- =============================================================================
---- deploy/postgres/init-roles.sql — create the two database roles (least privilege)
---- =============================================================================
---- GUIDE STEP   5.1
---- PURPOSE      Creates:
----              - te_migrator: OWNS the schema; used only by the one-shot
----                `migrate` service (Alembic) to create and alter tables;
----              - te_app: used by web, agent, mcp and worker; may only
----                read and write ROWS (SELECT/INSERT/UPDATE/DELETE), never
----                create, alter or drop tables (no DDL).
---- USED BY      deploy/postgres/10-init-roles.sh, which the postgres image
----              runs ONCE, when the data volume is empty (first start), and
----              which passes the passwords. compose.yml mounts this file at
----              /docker-init/init-roles.sql (outside initdb.d on purpose).
---- DEPENDS ON   psql variables :te_app_password and :te_migrator_password,
----              set by that wrapper from the secret files
----              /run/secrets/db_app_password and db_migrator_password.
----              Passwords are never written in this file.
---- WHY          Guide §2.2 least privilege: a bug or injection in the
----              application can at worst change rows it already may change;
----              it can never drop or alter a table. Architecture §6 ("data"
----              layer of defence in depth).
---- ACTIVATE     Remove one level of commenting (the `-- ` prefix) from the
----              statements, keep the `---- ` explanations. Test: connect as
----              te_app and check `CREATE TABLE x (i int);` is refused.
----              Note: init scripts run only on an EMPTY volume; on an existing
----              database, run the statements manually as the superuser.
---- =============================================================================

---- -----------------------------------------------------------------------------
---- TO-DO LIST: build this file yourself, step by step
---- -----------------------------------------------------------------------------
---- Write your SQL between this list and the SOLUTION marker below. Do the
---- steps in order. Lines starting with "|" are short illustrations, not the
---- full file. Keep the role names te_migrator and te_app, the schema name
---- te and the variable names exactly: 10-init-roles.sh, .env.example and
---- the database URLs (secrets/te_*database_url) use them.
----
---- Guide 5.1
---- [ ] 1. First line: the psql command that stops at the first error
----        (\set ON_ERROR_STOP on).
---- [ ] 2. Create the two LOGIN roles te_migrator and te_app; the password
----        comes from a psql variable, never written here:
----          | CREATE ROLE te_app LOGIN PASSWORD :'te_app_password';
---- [ ] 3. Create schema `te` owned by te_migrator (AUTHORIZATION), revoke
----        ALL on it from PUBLIC, and revoke CREATE on schema public from
----        PUBLIC.
---- [ ] 4. Grant USAGE (not CREATE) on schema te to te_app.
---- [ ] 5. Two ALTER DEFAULT PRIVILEGES FOR ROLE te_migrator IN SCHEMA te:
----        SELECT, INSERT, UPDATE, DELETE on TABLES, and USAGE, SELECT on
----        SEQUENCES, both to te_app (future tables get the rights).
---- [ ] 6. Set search_path = te for both roles (ALTER ROLE ... SET).
---- [ ] 7. The optional REVOKE UPDATE, DELETE on the append-only tables is
----        written commented twice: it belongs in a migration (5.3), not here.
---- [ ] 8. Check: with the postgres service up on an EMPTY volume, connect
----        with psql as te_app and as te_migrator; as te_app,
----        `CREATE TABLE x (i int);` must be refused.
----
---- Stuck, or want to compare? The SOLUTION below is the complete reference
---- code. Uncomment it only if you decide to use it as it is.

---- =============================================================================
---- SOLUTION: complete reference code (commented out on purpose)
---- =============================================================================

---- Stop at the first error instead of continuing with a half-configured database.
\set ON_ERROR_STOP on

---- 1. The roles. LOGIN = may connect. Passwords come from psql variables
----    (:'name' inserts the variable as a quoted SQL string literal).
CREATE ROLE te_migrator LOGIN PASSWORD :'te_migrator_password';
CREATE ROLE te_app LOGIN PASSWORD :'te_app_password';

---- 2. A dedicated schema owned by the migrator. Nobody else may create
----    objects in it; PUBLIC (= every role) loses its default rights.
CREATE SCHEMA te AUTHORIZATION te_migrator;
REVOKE ALL ON SCHEMA te FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

---- 3. The app may USE the schema (see its objects) but not CREATE in it.
GRANT USAGE ON SCHEMA te TO te_app;

---- 4. Default privileges: for every table and sequence the migrator creates
----    LATER (each migration), te_app automatically gets row-level rights.
----    Without this, every migration would need its own GRANT statement.
----    Sequences need USAGE/SELECT so auto-increment ids work on INSERT.
ALTER DEFAULT PRIVILEGES FOR ROLE te_migrator IN SCHEMA te
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO te_app;
ALTER DEFAULT PRIVILEGES FOR ROLE te_migrator IN SCHEMA te
    GRANT USAGE, SELECT ON SEQUENCES TO te_app;

---- 5. Both roles look in schema `te` first, so table names need no prefix.
ALTER ROLE te_migrator SET search_path = te;
ALTER ROLE te_app SET search_path = te;

---- Optional hardening (append-only tables, architecture §3.8): the
---- application never updates or deletes these rows, so the database can
---- enforce it too. Run AFTER the tables exist (in a migration, not here):
-- REVOKE UPDATE, DELETE ON spec_versions, answers, verifications, messages, audit_log FROM te_app;
