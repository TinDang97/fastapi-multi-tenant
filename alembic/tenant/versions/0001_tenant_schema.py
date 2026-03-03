"""initial tenant schema

Revision ID: 0001
Revises:
Create Date: 2026-03-02 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
    )
    op.create_table(
        "memberships",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("tenant_slug", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "tenant_slug"),
    )


def downgrade() -> None:
    op.drop_table("memberships")
    op.drop_table("users")
