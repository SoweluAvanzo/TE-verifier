"""Literature: index each passage in its own language; mark vectors to refresh.

Revision ID: 8d41c7e9b2a3
Revises: 5e2b9d0c4a17
Create Date: 2026-11-04 18:00:00

1. `language` ("en", "it" or "fr") on works and passages, detected at
   ingestion (literature/ingest.py). The search index stems a passage's
   section and text with its language's rules ("monete" and "moneta" share a
   stem only under Italian rules) and its context sentence, always written in
   English, with the English rules.
2. `embedding_stale`: set when a passage gets new labels (its context, part
   of what is embedded, changed). The old vector stays in use until
   `te-platform lit embed` replaces it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8d41c7e9b2a3"
down_revision: str | Sequence[str] | None = "5e2b9d0c4a17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONFIG = (
    "CASE language WHEN 'it' THEN 'italian'::regconfig "
    "WHEN 'fr' THEN 'french'::regconfig ELSE 'english'::regconfig END"
)
NEW_TSV = f"to_tsvector({CONFIG}, section || ' ' || text) || to_tsvector('english', context)"
OLD_TSV = "to_tsvector('english', section || ' ' || context || ' ' || text)"


def _replace_tsv(expression: str) -> None:
    """Re-create the generated search column with a new expression."""
    op.drop_index("ix_chunks_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_column("chunks", "tsv")
    op.add_column(
        "chunks",
        sa.Column(
            "tsv", postgresql.TSVECTOR(), sa.Computed(expression, persisted=True), nullable=True
        ),
    )
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")


def upgrade() -> None:
    """Add the language and stale-vector columns; index by language."""
    op.add_column("works", sa.Column("language", sa.String(2), nullable=False, server_default="en"))
    op.add_column(
        "chunks", sa.Column("language", sa.String(2), nullable=False, server_default="en")
    )
    op.add_column(
        "chunks",
        sa.Column("embedding_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _replace_tsv(NEW_TSV)


def downgrade() -> None:
    """Index everything with the English rules again; drop the new columns."""
    _replace_tsv(OLD_TSV)
    op.drop_column("chunks", "embedding_stale")
    op.drop_column("chunks", "language")
    op.drop_column("works", "language")
