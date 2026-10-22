"""Add webhook delivery timestamp.

Revision ID: 9b2c6e4f1a70
Revises: 4d0a3b25f51d
"""

import sqlalchemy as sa

from alembic import op

revision: str = "9b2c6e4f1a70"
down_revision: str | None = "4d0a3b25f51d"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("webhook_delivered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payments", "webhook_delivered_at")
