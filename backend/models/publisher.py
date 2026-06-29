"""
Publisher domain model.

Mirrors the schema stored in data/config/publishers.json.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field, field_validator

from backend.models.base import AppBaseModel


class KpiThresholds(AppBaseModel):
    retention: list[Any] = Field(default_factory=list)
    roas:      list[Any] = Field(default_factory=list)


class Publisher(AppBaseModel):
    """Complete publisher configuration record."""

    # ── Identity ──────────────────────────────────────────────────────────────
    id:           str = Field(default_factory=lambda: str(uuid.uuid4()))
    publisher_id: str = ""
    partner_name: str = ""

    # ── Sync flag ─────────────────────────────────────────────────────────────
    # When False this partner is excluded from every sync run.
    # Defaults to True so existing records remain active after migration.
    enabled: bool = True

    # ── Game info ─────────────────────────────────────────────────────────────
    game_name: str = ""
    game_id:   str = ""
    game_type: str = ""

    # ── Monetization ─────────────────────────────────────────────────────────
    payable_goals: list[Any] = Field(default_factory=list)

    # ── KPIs ──────────────────────────────────────────────────────────────────
    publisher_kpi: KpiThresholds = Field(default_factory=KpiThresholds)
    client_kpi:    KpiThresholds = Field(default_factory=KpiThresholds)

    # ── Funnel + performance ──────────────────────────────────────────────────
    expected_funnel: list[Any] = Field(default_factory=list)
    expected_margin: float     = 0.0

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("payable_goals", "expected_funnel", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list:
        return v if isinstance(v, list) else []

    @field_validator("publisher_kpi", "client_kpi", mode="before")
    @classmethod
    def _coerce_kpi(cls, v: Any) -> dict:
        return v if isinstance(v, dict) else {"retention": [], "roas": []}

    @field_validator("expected_margin", mode="before")
    @classmethod
    def _coerce_margin(cls, v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    def to_dict(self) -> dict:
        return self.model_dump(mode="python")


# ── Create / update schemas ───────────────────────────────────────────────────

class PublisherCreate(AppBaseModel):
    publisher_id:    str
    partner_name:    str
    enabled:         bool           = True
    game_name:       str            = ""
    game_id:         str            = ""
    game_type:       str            = ""
    payable_goals:   list[Any]      = Field(default_factory=list)
    publisher_kpi:   dict[str, Any] = Field(default_factory=dict)
    client_kpi:      dict[str, Any] = Field(default_factory=dict)
    expected_funnel: list[Any]      = Field(default_factory=list)
    expected_margin: float          = 0.0


class PublisherUpdate(PublisherCreate):
    publisher_id: str  = ""
    partner_name: str  = ""
    enabled:      bool = True
