"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-29

Creates the initial PostgreSQL schema for:
  - game_configs
  - publishers
  - partners
  - partner_assignments
  - sync_history

This migration corresponds to the ORM definitions in
backend/repositories/pg/schema.py.  It was generated from that schema
and is the baseline before alembic autogenerate takes over.

To apply:
    alembic upgrade head

To roll back:
    alembic downgrade -1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── game_configs ──────────────────────────────────────────────────────────
    op.create_table(
        "game_configs",
        sa.Column("id",              sa.String(36),  primary_key=True, nullable=False),
        sa.Column("offer_id",        sa.String(50),  nullable=False),
        sa.Column("offer_name",      sa.String(255), nullable=False, server_default=""),
        sa.Column("game_type",       sa.String(20),  nullable=False, server_default="CPI"),
        sa.Column("payable_goals",   sa.JSON(),      nullable=False),
        sa.Column("publisher_kpi",   sa.JSON(),      nullable=False),
        sa.Column("client_kpi",      sa.JSON(),      nullable=False),
        sa.Column("expected_funnel", sa.JSON(),      nullable=True),
        sa.Column("tracking_links",  sa.JSON(),      nullable=True),
        sa.Column("play_store",      sa.JSON(),      nullable=True),
        sa.Column("assets",          sa.JSON(),      nullable=True),
        sa.Column("expected_margin", sa.Float(),     nullable=True),
        sa.Column("campaign_status", sa.String(20),  nullable=True),
        sa.Column("platform",        sa.String(20),  nullable=True),
        sa.Column("notes",           sa.Text(),      nullable=True),
        sa.Column("client_notes",    sa.Text(),      nullable=True),
        sa.Column("configured_at",   sa.String(50),  nullable=True),
        sa.Column("updated_at",      sa.String(50),  nullable=True),
    )
    op.create_index("ix_game_configs_offer_id", "game_configs", ["offer_id"], unique=True)

    # ── publishers ────────────────────────────────────────────────────────────
    op.create_table(
        "publishers",
        sa.Column("id",              sa.String(36),  primary_key=True, nullable=False),
        sa.Column("publisher_id",    sa.String(50),  nullable=False),
        sa.Column("partner_name",    sa.String(255), nullable=False, server_default=""),
        sa.Column("game_name",       sa.String(255), nullable=False, server_default=""),
        sa.Column("game_id",         sa.String(50),  nullable=False, server_default=""),
        sa.Column("game_type",       sa.String(20),  nullable=False, server_default=""),
        sa.Column("payable_goals",   sa.JSON(),      nullable=False),
        sa.Column("publisher_kpi",   sa.JSON(),      nullable=False),
        sa.Column("client_kpi",      sa.JSON(),      nullable=False),
        sa.Column("expected_funnel", sa.JSON(),      nullable=True),
        sa.Column("expected_margin", sa.Float(),     nullable=False, server_default="0"),
    )
    op.create_index("ix_publishers_publisher_id", "publishers", ["publisher_id"], unique=True)

    # ── partners ──────────────────────────────────────────────────────────────
    op.create_table(
        "partners",
        sa.Column("id",            sa.String(36),  primary_key=True, nullable=False),
        sa.Column("partner_name",  sa.String(255), nullable=False, server_default=""),
        sa.Column("company_name",  sa.String(255), nullable=False, server_default=""),
        sa.Column("email",         sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False, server_default=""),
        sa.Column("status",        sa.String(20),  nullable=False, server_default="active"),
        sa.Column("last_login",    sa.String(50),  nullable=True),
        sa.Column("created_at",    sa.String(50),  nullable=True),
    )
    op.create_index("ix_partners_email", "partners", ["email"], unique=True)

    # ── partner_assignments ───────────────────────────────────────────────────
    op.create_table(
        "partner_assignments",
        sa.Column("id",         sa.String(36), primary_key=True, nullable=False),
        sa.Column("partner_id", sa.String(36), sa.ForeignKey("partners.id",     ondelete="CASCADE"), nullable=False),
        sa.Column("config_id",  sa.String(36), sa.ForeignKey("game_configs.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_partner_assignments_partner_id", "partner_assignments", ["partner_id"])
    op.create_index("ix_partner_assignments_config_id",  "partner_assignments", ["config_id"])

    # ── sync_history ──────────────────────────────────────────────────────────
    op.create_table(
        "sync_history",
        sa.Column("id",          sa.String(36), primary_key=True, nullable=False),
        sa.Column("started_at",  sa.String(50), nullable=False),
        sa.Column("finished_at", sa.String(50), nullable=True),
        sa.Column("status",      sa.String(20), nullable=False, server_default="running"),
        sa.Column("date_from",   sa.String(10), nullable=True),
        sa.Column("date_to",     sa.String(10), nullable=True),
        sa.Column("rows_synced", sa.Integer(),  nullable=True),
        sa.Column("error",       sa.Text(),     nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_history")
    op.drop_index("ix_partner_assignments_config_id",  table_name="partner_assignments")
    op.drop_index("ix_partner_assignments_partner_id", table_name="partner_assignments")
    op.drop_table("partner_assignments")
    op.drop_index("ix_partners_email",             table_name="partners")
    op.drop_table("partners")
    op.drop_index("ix_publishers_publisher_id",    table_name="publishers")
    op.drop_table("publishers")
    op.drop_index("ix_game_configs_offer_id",      table_name="game_configs")
    op.drop_table("game_configs")
