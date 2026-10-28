#!/bin/bash
## =============================================================================
## deploy/postgres/10-init-roles.sh — run init-roles.sql with the passwords
## =============================================================================
## GUIDE STEP   5.1
## PURPOSE      The postgres image runs scripts in /docker-entrypoint-initdb.d/
##              once, on an empty data volume. A plain .sql file there cannot
##              read files or variables, but init-roles.sql needs the two
##              role passwords. This wrapper reads them from the secret files
##              that compose.yml mounts into this container only
##              (/run/secrets/db_app_password, /run/secrets/db_migrator_password)
##              and hands them to psql as variables (--set), which the SQL
##              file uses as :'te_app_password' and :'te_migrator_password'.
##              The passwords are never in the repository, in .env, or in any
##              container's environment.
## USED BY      compose.yml (postgres service): this script is mounted into
##              /docker-entrypoint-initdb.d/, and init-roles.sql is mounted
##              OUTSIDE that folder (/docker-init/), so the image does not
##              also try to run the .sql file on its own without variables.
## DEPENDS ON   POSTGRES_USER and POSTGRES_DB (standard variables of the
##              image, from .env) and the secret files db_app_password and
##              db_migrator_password (compose.yml, guide 5.1; readable by the
##              postgres user, uid 999: chmod 644 on the host).
## WHY          Guide §2.2: secrets never in code or in shared configuration;
##              least privilege: only this container sees these passwords.
## ACTIVATE     Remove one level of `#` from the code below. The first line,
##              `#!/bin/bash`, is the "shebang" (it tells the system which
##              program runs the script); it must stay the very first line, and
##              it is itself a shell comment, so it is inert until then. The
##              file is executable (chmod +x), which makes the postgres image
##              run it as a program rather than source it.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your script between this list and the SOLUTION marker below. Keep
## `#!/bin/bash` as line 1 and the file executable (chmod +x). The variable
## names must match init-roles.sql (:'te_app_password',
## :'te_migrator_password'); the file names must match compose.yml's
## postgres `secrets:`.
##
## Guide 5.1
## [ ] 1. `set -euo pipefail` (the SOLUTION's `##` lines explain each flag).
## [ ] 2. Read the two passwords from their secret files into shell
##        variables, as plain assignments (so a missing file stops the
##        script):
##          | app_password=$(< /run/secrets/db_app_password)
## [ ] 3. One psql call as "$POSTGRES_USER" on "$POSTGRES_DB" with
##        --set ON_ERROR_STOP=1, one --set per password, and --file
##        /docker-init/init-roles.sql (where compose.yml mounts it):
##          | --set te_app_password="$app_password" \
##          | --set te_migrator_password="$migrator_password" \
## [ ] 4. Check: remove the pgdata volume (init scripts run only on an empty
##        volume), `docker compose up postgres`, and look for the two CREATE
##        ROLE lines in `docker compose logs postgres`; then the psql checks
##        of init-roles.sql.
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## -e: stop at the first failing command; -u: using an unset variable is an
## error (a missing password must not create a role with an empty one);
## -o pipefail: a failure inside a pipe is not hidden.
set -euo pipefail

## The two role passwords, from the secret files compose.yml mounts into
## this container only. `$(< file)` reads a file without starting another
## program and drops the trailing newline. Plain assignments on purpose: a
## failing `$(...)` in an assignment stops the script (-e), while inside
## psql's arguments it would pass an empty password unnoticed.
app_password=$(< /run/secrets/db_app_password)
migrator_password=$(< /run/secrets/db_migrator_password)

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     --set ON_ERROR_STOP=1 \
     --set te_app_password="$app_password" \
     --set te_migrator_password="$migrator_password" \
     --file /docker-init/init-roles.sql
