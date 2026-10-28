"""Reports: the agent's review before a report can be downloaded.

Revision ID: 9a1c2e7b5d40
Revises: 4177b7e3cf13
Create Date: 2026-10-25 10:30:00

A report is rendered as a draft; tool report.publish.v1 records the
agent's review (what it checked) and the time, and only then does the
download link work (agent/user_reports_api.py).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a1c2e7b5d40"
down_revision: str | Sequence[str] | None = "4177b7e3cf13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the review columns (NULL = draft)."""
    op.add_column("reports", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("review", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove the review columns."""
    op.drop_column("reports", "review")
    op.drop_column("reports", "reviewed_at")
