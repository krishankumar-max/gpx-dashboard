"""
PublisherStructure domain model.

One record = one immutable version of a publisher's reward structure for a
specific game (offer).  The structural payload (reward_steps, tracking_link,
preview_url, iap_events) is set at creation and never modified.  Only
status and the two lifecycle timestamps (live_at, paused_at) may change.

Reward-step schema matches the existing funnel CSV format used throughout
the product:
    goal, expected_percent, time_minutes, payout

Status machine:
    pending  → live      (first activation)
    live     → paused    (manual pause or auto-pause on promotion)
    paused   → live      (re-activation — updates live_at)
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field, field_validator

from backend.models.base import AppBaseModel


# ── Sub-models ────────────────────────────────────────────────────────────────

class RewardStep(AppBaseModel):
    """
    One milestone in the reward structure.

    Matches the canonical funnel CSV columns:
        goal              — event / milestone name (e.g. "reached_level_5")
        expected_percent  — % of users expected to reach this milestone (0–100)
        time_minutes      — expected time in minutes to reach the milestone
        payout            — USD payout when this milestone is achieved
    """
    goal:             str   = ""
    expected_percent: float = 100.0
    time_minutes:     float = 0.0
    payout:           float = 0.0

    @field_validator("expected_percent", "time_minutes", "payout", mode="before")
    @classmethod
    def _coerce_float(cls, v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0


# ── Root model ────────────────────────────────────────────────────────────────

class PublisherStructure(AppBaseModel):
    """
    Complete publisher structure version record.

    Fields
    ------
    id             UUID primary key — generated on creation.
    publisher_id   Soft reference to publishers.publisher_id (string).
    offer_id       Soft reference to game_configs.offer_id (string).
    offer_name     Denormalized for display — not used as a key.
    version        Monotonically increasing integer scoped to
                   (publisher_id, offer_id).  Never reused.
    status         One of: live | pending | paused.
    reward_steps   Immutable list of RewardStep dicts.
    tracking_link  Immutable after creation (user can clone + edit).
    preview_url    Immutable after creation.
    iap_events     Immutable list of IAP event name strings.
    created_at     Set once at creation.
    live_at        Updated each time the structure is promoted to live.
    paused_at      Updated each time the structure is paused.
    created_by     Optional — populated from auth context when available.
    """

    id:            str = Field(default_factory=lambda: str(uuid.uuid4()))
    publisher_id:  str = ""
    offer_id:      str = ""
    offer_name:    str = ""
    version:       int = 1
    status:        str = "pending"        # live | pending | paused

    # ── Structural payload (immutable after creation) ─────────────────────────
    reward_steps:  list[RewardStep] = Field(default_factory=list)
    tracking_link: str = ""
    preview_url:   str = ""
    iap_events:    list[str]        = Field(default_factory=list)

    # ── Lifecycle timestamps ───────────────────────────────────────────────────
    created_at: str | None = None   # set once at creation
    live_at:    str | None = None   # most recent promotion to live
    paused_at:  str | None = None   # most recent pause
    created_by: str | None = None   # optional, from auth context

    @field_validator("reward_steps", mode="before")
    @classmethod
    def _coerce_steps(cls, v: Any) -> list:
        return v if isinstance(v, list) else []

    @field_validator("iap_events", mode="before")
    @classmethod
    def _coerce_iap(cls, v: Any) -> list:
        if isinstance(v, list):
            return [str(x) for x in v if x]
        return []

    def to_dict(self) -> dict:
        return self.model_dump(mode="python")


# ── Create schema ─────────────────────────────────────────────────────────────

class PublisherStructureCreate(AppBaseModel):
    """Fields accepted when creating a new structure record (POST)."""
    publisher_id:  str
    offer_id:      str
    offer_name:    str       = ""
    reward_steps:  list[Any] = Field(default_factory=list)
    tracking_link: str       = ""
    preview_url:   str       = ""
    iap_events:    list[str] = Field(default_factory=list)
    created_by:    str | None = None
