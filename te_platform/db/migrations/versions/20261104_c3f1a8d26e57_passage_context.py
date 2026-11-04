"""Literature: a context sentence and labels for every passage.

Revision ID: c3f1a8d26e57
Revises: 9a1c2e7b5d40
Create Date: 2026-11-04 11:00:00

`te-platform lit enrich` asks a model, once per passage, for one sentence
that places the passage in its paper ("From Collom 2012 on US time banks,
results: ...") and for labels: the failure modes and parameters it informs
and the kind of content (literature/enrich.py). The search index then
covers the section heading, that sentence and the passage, so a passage
that never names its subject (an article of a regulation, a table of
results) is still found by it. `enriched_by` records the model that wrote
the labels; NULL means not labelled yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3f1a8d26e57"
down_revision: str | Sequence[str] | None = "9a1c2e7b5d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMPTY = sa.text("'{}'::varchar[]")


def upgrade() -> None:
    """Add the context and label columns and index them for search."""
    op.add_column("chunks", sa.Column("context", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "chunks",
        sa.Column(
            "failure_modes",
            postgresql.ARRAY(sa.String(8)),
            nullable=False,
            server_default=_EMPTY,
        ),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "parameters",
            postgresql.ARRAY(sa.String(32)),
            nullable=False,
            server_default=_EMPTY,
        ),
    )
    op.add_column("chunks", sa.Column("kind", sa.String(32), nullable=True))
    op.add_column("chunks", sa.Column("enriched_by", sa.String(128), nullable=True))
    # A generated column's expression cannot be altered: drop and re-add it.
    op.drop_index("ix_chunks_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_column("chunks", "tsv")
    op.add_column(
        "chunks",
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', section || ' ' || context || ' ' || text)",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    op.create_index("ix_chunks_failure_modes", "chunks", ["failure_modes"], postgresql_using="gin")
    op.create_index("ix_chunks_parameters", "chunks", ["parameters"], postgresql_using="gin")


def downgrade() -> None:
    """Remove the labels and index the passage text alone again."""
    op.drop_index("ix_chunks_parameters", table_name="chunks", postgresql_using="gin")
    op.drop_index("ix_chunks_failure_modes", table_name="chunks", postgresql_using="gin")
    op.drop_index("ix_chunks_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_column("chunks", "tsv")
    op.add_column(
        "chunks",
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    for column in ("enriched_by", "kind", "parameters", "failure_modes", "context"):
        op.drop_column("chunks", column)
