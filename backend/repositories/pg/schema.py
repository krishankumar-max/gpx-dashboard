"""
SQLAlchemy 2.0 ORM schema — PostgreSQL table definitions.

These ORM classes mirror the Pydantic domain models but are decoupled from
them deliberately.  The mapping layer in each PG repository converts between
ORM rows and Pydantic objects.

Tables
------
game_configs       — game configuration records
publishers         — publisher configuration records
partners           — partner portal user records
partner_assignments — game configs assigned to a partner (junction table)
sync_history       — audit log of sync runs
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


class GameConfigORM(Base):
    __tablename__ = "game_configs"

    id           = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    offer_id     = Column(String(50),  nullable=False, unique=True, index=True)
    offer_name   = Column(String(255), nullable=False, default="")
    game_type    = Column(String(20),  nullable=False, default="CPI")

    # JSON columns
    payable_goals   = Column(JSON, nullable=False, default=list)
    publisher_kpi   = Column(JSON, nullable=False, default=dict)
    client_kpi      = Column(JSON, nullable=False, default=dict)
    expected_funnel = Column(JSON, nullable=True)
    tracking_links  = Column(JSON, nullable=True, default=list)
    play_store      = Column(JSON, nullable=True)
    assets          = Column(JSON, nullable=True, default=list)

    # Scalar columns
    expected_margin = Column(Float,       nullable=True)
    campaign_status = Column(String(20),  nullable=True)  # draft|live|paused|ended
    platform        = Column(String(20),  nullable=True)  # android|ios|both

    # Notes
    notes        = Column(Text, nullable=True)   # internal — never sent to partners
    client_notes = Column(Text, nullable=True)   # partner-facing

    # Timestamps
    configured_at = Column(String(50), nullable=True)
    updated_at    = Column(String(50), nullable=True)

    # Relationships
    partner_assignments = relationship(
        "PartnerAssignmentORM", back_populates="game_config", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<GameConfig id={self.id!r} offer_id={self.offer_id!r}>"


class PublisherORM(Base):
    __tablename__ = "publishers"

    id           = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    publisher_id = Column(String(50),  nullable=False, unique=True, index=True)
    partner_name = Column(String(255), nullable=False, default="")
    game_name    = Column(String(255), nullable=False, default="")
    game_id      = Column(String(50),  nullable=False, default="")
    game_type    = Column(String(20),  nullable=False, default="")

    # JSON columns
    payable_goals   = Column(JSON, nullable=False, default=list)
    publisher_kpi   = Column(JSON, nullable=False, default=dict)
    client_kpi      = Column(JSON, nullable=False, default=dict)
    expected_funnel = Column(JSON, nullable=True)

    # Scalar columns
    expected_margin = Column(Float, nullable=False, default=0.0)

    def __repr__(self) -> str:
        return f"<Publisher id={self.id!r} publisher_id={self.publisher_id!r}>"


class PartnerORM(Base):
    __tablename__ = "partners"

    id           = Column(String(36),  primary_key=True, default=lambda: str(uuid.uuid4()))
    partner_name = Column(String(255), nullable=False, default="")
    company_name = Column(String(255), nullable=False, default="")
    email        = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False, default="")
    status       = Column(String(20),  nullable=False, default="active")

    # Timestamps
    last_login = Column(String(50), nullable=True)
    created_at = Column(String(50), nullable=True)

    # Relationships
    assignments = relationship(
        "PartnerAssignmentORM", back_populates="partner", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Partner id={self.id!r} email={self.email!r}>"


class PartnerAssignmentORM(Base):
    """Junction table: which game configs are assigned to which partner."""
    __tablename__ = "partner_assignments"

    id         = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    partner_id = Column(String(36), ForeignKey("partners.id",     ondelete="CASCADE"), nullable=False, index=True)
    config_id  = Column(String(36), ForeignKey("game_configs.id", ondelete="CASCADE"), nullable=False, index=True)

    partner     = relationship("PartnerORM",    back_populates="assignments")
    game_config = relationship("GameConfigORM", back_populates="partner_assignments")

    def __repr__(self) -> str:
        return f"<PartnerAssignment partner={self.partner_id!r} config={self.config_id!r}>"


class SyncHistoryORM(Base):
    """Audit log of every sync run (currently stored only in memory / logs)."""
    __tablename__ = "sync_history"

    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    started_at  = Column(String(50), nullable=False)
    finished_at = Column(String(50), nullable=True)
    status      = Column(String(20), nullable=False, default="running")  # running|success|failed
    date_from   = Column(String(10), nullable=True)
    date_to     = Column(String(10), nullable=True)
    rows_synced = Column(Integer,    nullable=True)
    error       = Column(Text,       nullable=True)

    def __repr__(self) -> str:
        return f"<SyncHistory id={self.id!r} status={self.status!r}>"
