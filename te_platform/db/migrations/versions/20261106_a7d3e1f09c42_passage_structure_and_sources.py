"""Passage structure (position, locator, formal) and source tiers (tier, systems, source_url).

Revision ID: a7d3e1f09c42
Revises: 8d41c7e9b2a3
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7d3e1f09c42"
down_revision = "8d41c7e9b2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the columns."""
    op.add_column(
        "works", sa.Column("tier", sa.Integer(), server_default="0", nullable=False), schema="te"
    )
    op.add_column(
        "works",
        sa.Column(
            "systems",
            postgresql.ARRAY(sa.String(32)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        schema="te",
    )
    op.add_column("works", sa.Column("source_url", sa.Text(), nullable=True), schema="te")
    op.add_column(
        "chunks",
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        schema="te",
    )
    op.add_column(
        "chunks", sa.Column("locator", sa.Text(), server_default="", nullable=False), schema="te"
    )
    op.add_column(
        "chunks",
        sa.Column("formal", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="te",
    )
    op.create_index("ix_chunks_work_position", "chunks", ["work_id", "position"], schema="te")


def downgrade() -> None:
    """Drop the columns."""
    op.drop_index("ix_chunks_work_position", table_name="chunks", schema="te")
    op.drop_column("chunks", "formal", schema="te")
    op.drop_column("chunks", "locator", schema="te")
    op.drop_column("chunks", "position", schema="te")
    op.drop_column("works", "source_url", schema="te")
    op.drop_column("works", "systems", schema="te")
    op.drop_column("works", "tier", schema="te")
