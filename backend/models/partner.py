"""
Partner domain model.

Partners are client-facing portal users who can log in at /partner/login
and view only their assigned campaigns.  Stored in data/config/partners.json.

NOTE: The current clients.json has a simpler schema (client_name, games, bid,
kpi, notes).  This model targets the full Partner Portal schema defined in
the architecture plan.  A migration script will upgrade existing records.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field, field_validator

from backend.models.base import AppBaseModel


class Partner(AppBaseModel):
    """Complete partner (portal user) record."""

    # ── Identity ──────────────────────────────────────────────────────────────
    id:           str = Field(default_factory=lambda: str(uuid.uuid4()))
    partner_name: str = ""
    company_name: str = ""
    email:        str = ""

    # ── Auth ──────────────────────────────────────────────────────────────────
    password_hash: str  = ""
    status:        str  = "active"   # active | disabled

    # ── Campaign assignments (list of game_config IDs) ────────────────────────
    assigned_game_config_ids: list[str] = Field(default_factory=list)

    # ── Audit ─────────────────────────────────────────────────────────────────
    last_login: str | None = None
    created_at: str | None = None

    # ── Legacy fields (clients.json backward compat) ─────────────────────────
    # Kept so old records round-trip without data loss (extra="allow" handles
    # truly unknown fields; these are explicitly modelled for clarity).
    client_name: str | None = None   # alias for partner_name in old schema
    games:       str | None = None   # old free-text game list
    bid:         float | None = None
    kpi:         str | None = None
    notes:       str | None = None

    @field_validator("assigned_game_config_ids", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list:
        return v if isinstance(v, list) else []

    def to_dict(self) -> dict:
        return self.model_dump(mode="python")


# ── Create / update schemas ───────────────────────────────────────────────────

class PartnerCreate(AppBaseModel):
    partner_name:             str       = ""
    company_name:             str       = ""
    email:                    str       = ""
    password_hash:            str       = ""
    status:                   str       = "active"
    assigned_game_config_ids: list[str] = Field(default_factory=list)


class PartnerUpdate(PartnerCreate):
    pass
