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
    Index, Integer, JSON, String, Text, UniqueConstraint, func,
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
    enabled      = Column(Boolean,     nullable=False, default=True)  # False = skip this partner during sync
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


class PublisherStructureORM(Base):
    """
    One version of a publisher's reward structure for a specific game.

    Structural payload columns (reward_steps, tracking_link, preview_url,
    iap_events) are set at creation and never mutated.  Only status,
    live_at, and paused_at change over the lifetime of a record.
    """
    __tablename__ = "publisher_structures"

    id           = Column(String(36),   primary_key=True, default=lambda: str(uuid.uuid4()))
    publisher_id = Column(String(50),   nullable=False)
    offer_id     = Column(String(50),   nullable=False)
    offer_name   = Column(String(255),  nullable=False, default="")
    version      = Column(Integer,      nullable=False)
    status       = Column(String(20),   nullable=False, default="pending")  # live|pending|paused

    # Structural payload (immutable after creation)
    reward_steps  = Column(JSON,          nullable=False, default=list)
    tracking_link = Column(String(1000),  nullable=True,  default="")
    preview_url   = Column(String(1000),  nullable=True,  default="")
    iap_events    = Column(JSON,          nullable=False, default=list)

    # Lifecycle timestamps
    created_at = Column(String(50),  nullable=False)
    live_at    = Column(String(50),  nullable=True)
    paused_at  = Column(String(50),  nullable=True)
    created_by = Column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("publisher_id", "offer_id", "version", name="uq_ps_pub_offer_ver"),
        Index("ix_ps_publisher_offer", "publisher_id", "offer_id"),
        Index("ix_ps_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<PublisherStructure publisher={self.publisher_id!r} "
            f"offer={self.offer_id!r} v{self.version} {self.status!r}>"
        )
