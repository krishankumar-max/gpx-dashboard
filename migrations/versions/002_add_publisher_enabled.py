"""add publishers.enabled column

Revision ID: 002
Revises: 001
Create Date: 2026-06-29

Adds an `enabled` boolean column to the publishers table.
When False, the partner is excluded from every sync run.
Existing rows default to True so no data is affected.

To apply:
    alembic upgrade head

To roll back:
    alembic downgrade -1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "publishers",
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),   # existing rows default to enabled
        ),
    )


def downgrade() -> None:
    op.drop_column("publishers", "enabled")
