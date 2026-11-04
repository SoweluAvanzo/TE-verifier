"""Literature: an embedding (meaning vector) for every passage.

Revision ID: 5e2b9d0c4a17
Revises: c3f1a8d26e57
Create Date: 2026-11-04 12:00:00

`te-platform lit embed` stores, for each passage, a vector from a local
multilingual embedding model (literature/embed.py), as float32 bytes, with
the model's name: vectors of different models cannot be compared, so search
uses only those of the model it loads. Search combines keyword ranking with
the vectors' cosine similarity (literature/search.py), so a passage is found
by meaning and across languages, not only by its exact words. Kept as bytes
rather than a pgvector column: about 10,000 passages fit in memory, and the
database image and extensions stay as they are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e2b9d0c4a17"
down_revision: str | Sequence[str] | None = "c3f1a8d26e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the embedding columns."""
    op.add_column("chunks", sa.Column("embedding", sa.LargeBinary(), nullable=True))
    op.add_column("chunks", sa.Column("embedding_model", sa.String(128), nullable=True))
    op.create_index("ix_chunks_embedding_model", "chunks", ["embedding_model"])


def downgrade() -> None:
    """Remove the embedding columns."""
    op.drop_index("ix_chunks_embedding_model", table_name="chunks")
    op.drop_column("chunks", "embedding_model")
    op.drop_column("chunks", "embedding")
