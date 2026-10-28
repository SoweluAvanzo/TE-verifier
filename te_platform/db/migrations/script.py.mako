## =============================================================================
## te_platform/db/migrations/script.py.mako — template for new migration files
## =============================================================================
## GUIDE STEP   5.3
## PURPOSE      `alembic revision --autogenerate -m "..."` fills this template
##              to create each new file in versions/. It is Alembic's standard
##              template (from Alembic 1.20) with one change: a period after
##              ${message}, because the docstring rules of te_platform/
##              ruff.toml want the first line to end with one. It is
##              shipped here because `alembic init` refuses to write into a
##              folder that already exists, and this folder holds env.py.
##              The post-write hooks of alembic.ini (ruff) then bring each
##              generated file up to the project's lint and format rules.
## SYNTAX       This is a Mako template, not Python: `${...}` are placeholders
##              Alembic fills in; lines starting with `##` (like these) are
##              Mako comments and do not appear in generated files.
## ACTIVATE     Nothing to uncomment: a template only takes effect when you run
##              `alembic revision`, which is a deliberate act. Review every
##              generated migration by hand before applying it (guide 5.3).
## =============================================================================
"""${message}.

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
