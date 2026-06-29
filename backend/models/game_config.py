"""
GameConfig domain model.

Mirrors the schema stored in data/config/game_configs.json.
New optional fields for the Partner Portal (campaign_status, platform,
tracking_links, play_store, assets, client_notes) are included here
so the model is forward-compatible — JSON files without these fields
simply get None / empty defaults.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field, field_validator

from backend.models.base import AppBaseModel


# ── Sub-models ────────────────────────────────────────────────────────────────

class KpiThresholds(AppBaseModel):
    """Publisher / client KPI bands — both are lists of threshold dicts."""
    retention: list[Any] = Field(default_factory=list)
    roas:      list[Any] = Field(default_factory=list)


class PayableGoal(AppBaseModel):
    """One payable milestone: a goal name and the configured bid in USD."""
    name: str   = ""
    bid:  float = 0.0


class TrackingLink(AppBaseModel):
    """A named tracking URL.  Dynamic — any label is valid."""
    label: str = ""
    url:   str = ""


class PlayStore(AppBaseModel):
    """App store metadata displayed in the Partner Portal."""
    package_name:   str = ""
    play_store_url: str = ""
    app_store_url:  str = ""
    icon_url:       str = ""


class CampaignAsset(AppBaseModel):
    """One campaign asset (icon, banner, screenshot, logo)."""
    type: str = ""   # icon | banner | screenshot | logo
    url:  str = ""


# ── Root model ────────────────────────────────────────────────────────────────

class GameConfig(AppBaseModel):
    """
    Complete game configuration record.

    Fields marked 'Partner Portal' are new; they default to empty/None
    so existing JSON records that lack them are fully backward-compatible.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    id:         str = Field(default_factory=lambda: str(uuid.uuid4()))
    offer_id:   str = ""
    offer_name: str = ""

    # ── Campaign ──────────────────────────────────────────────────────────────
    game_type:       str              = "CPI"
    payable_goals:   list[PayableGoal] = Field(default_factory=list)
    publisher_kpi:   KpiThresholds    = Field(default_factory=KpiThresholds)
    client_kpi:      KpiThresholds    = Field(default_factory=KpiThresholds)
    expected_funnel: list[Any]        = Field(default_factory=list)
    expected_margin: float | None     = None

    # ── Notes (split into internal vs client-facing) ──────────────────────────
    notes:        str | None = None   # internal — never shown to partners
    client_notes: str | None = None   # Partner Portal — visible to partners

    # ── Partner Portal extensions (all optional, default empty) ───────────────
    campaign_status: str | None              = None  # draft|live|paused|ended
    platform:        str | None              = None  # android|ios|both
    tracking_links:  list[TrackingLink]      = Field(default_factory=list)
    play_store:      PlayStore | None        = None
    assets:          list[CampaignAsset]     = Field(default_factory=list)

    # ── Timestamps ────────────────────────────────────────────────────────────
    configured_at: str | None = None
    updated_at:    str | None = None

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("payable_goals", mode="before")
    @classmethod
    def _coerce_payable_goals(cls, v: Any) -> list:
        return v if isinstance(v, list) else []

    @field_validator("expected_funnel", mode="before")
    @classmethod
    def _coerce_funnel(cls, v: Any) -> list:
        return v if isinstance(v, list) else []

    @field_validator("tracking_links", mode="before")
    @classmethod
    def _coerce_tracking_links(cls, v: Any) -> list:
        return v if isinstance(v, list) else []

    @field_validator("assets", mode="before")
    @classmethod
    def _coerce_assets(cls, v: Any) -> list:
        return v if isinstance(v, list) else []

    @field_validator("publisher_kpi", "client_kpi", mode="before")
    @classmethod
    def _coerce_kpi(cls, v: Any) -> dict:
        if isinstance(v, dict):
            return v
        return {"retention": [], "roas": []}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """
        Serialise to a plain dict suitable for JSON storage.
        model_dump() with mode="python" keeps nested Pydantic objects as dicts.
        """
        return self.model_dump(mode="python")


# ── Lightweight create / update schemas ──────────────────────────────────────

class GameConfigCreate(AppBaseModel):
    """Fields accepted when creating a new game config (POST)."""
    offer_id:        str
    offer_name:      str               = ""
    game_type:       str               = "CPI"
    payable_goals:   list[Any]         = Field(default_factory=list)
    publisher_kpi:   dict[str, Any]    = Field(default_factory=dict)
    client_kpi:      dict[str, Any]    = Field(default_factory=dict)
    expected_funnel: list[Any]         = Field(default_factory=list)
    expected_margin: float | None      = None
    notes:           str | None        = None
    client_notes:    str | None        = None
    campaign_status: str | None        = None
    platform:        str | None        = None
    tracking_links:  list[Any]         = Field(default_factory=list)
    play_store:      dict[str, Any] | None = None
    assets:          list[Any]         = Field(default_factory=list)


class GameConfigUpdate(GameConfigCreate):
    """Fields accepted when updating an existing game config (PUT).
    offer_id is not required for updates."""
    offer_id: str = ""
