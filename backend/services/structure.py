"""
StructureService — business logic for publisher structure versioning.

Responsibilities
----------------
- CRUD (create, list, get)
- Lifecycle transitions: make_live, pause
- Cloning (any version from any publisher+game)
- CSV import / export (lossless round-trip matching the existing funnel format)
- Publisher stats aggregation for the left panel

CSV format (matches the existing expected_funnel CSV used throughout the product):
    goal,expected_percent,time_minutes,payout
    install,100,0,5.00
    reached_level_5,80,5,10.00

Status machine:
    pending → live     (make_live)
    live    → paused   (pause, or auto-pause when another version is promoted)
    paused  → live     (make_live — re-activation)

Only one live structure is allowed per (publisher_id, offer_id).
Promoting a structure automatically pauses the current live one.
Structural payload (reward_steps, tracking_link, preview_url, iap_events)
is immutable after creation.  Only status + timestamps may change.
"""
from __future__ import annotations

import csv
import io
import uuid

from backend.repositories.base import StructureRepository
from backend.utils import ist_now


# ── CSV header normalisation ───────────────────────────────────────────────────

_HEADER_ALIASES: dict[str, str] = {
    "goal":            "goal",
    "goalname":        "goal",
    "event":           "goal",
    "eventname":       "goal",
    "expectedpercent": "expected_percent",
    "expected":        "expected_percent",
    "pct":             "expected_percent",
    "percent":         "expected_percent",
    "timeminutes":     "time_minutes",
    "time":            "time_minutes",
    "minutes":         "time_minutes",
    "min":             "time_minutes",
    "payout":          "payout",
    "bid":             "payout",
    "reward":          "payout",
    "rewardusd":       "payout",
}


def _norm_header(raw: str) -> str:
    s = raw.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return _HEADER_ALIASES.get(s, s)


def _parse_reward_csv(text: str) -> list[dict]:
    """
    Parse a reward-structure CSV and return a list of RewardStep dicts.

    Required columns (order-independent, aliases accepted):
        goal, expected_percent, time_minutes, payout

    Raises ValueError on fatal parse errors.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        raise ValueError("CSV is empty")

    header = [_norm_header(h) for h in lines[0].split(",")]
    required = {"goal", "expected_percent", "time_minutes", "payout"}
    missing = required - set(header)
    if missing:
        raise ValueError(
            f"Missing required column(s): {', '.join(sorted(missing))}. "
            f"Required: goal, expected_percent, time_minutes, payout"
        )

    goal_i = header.index("goal")
    pct_i  = header.index("expected_percent")
    time_i = header.index("time_minutes")
    pay_i  = header.index("payout")

    steps: list[dict] = []
    for line_no, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cols = line.split(",")
        try:
            goal = cols[goal_i].strip() if goal_i < len(cols) else ""
            if not goal:
                raise ValueError("goal cannot be empty")
            steps.append({
                "goal":             goal,
                "expected_percent": float(cols[pct_i].strip()  if pct_i  < len(cols) else 0),
                "time_minutes":     float(cols[time_i].strip() if time_i < len(cols) else 0),
                "payout":           float(cols[pay_i].strip()  if pay_i  < len(cols) else 0),
            })
        except (IndexError, ValueError) as exc:
            raise ValueError(f"Row {line_no}: {exc}") from exc

    if not steps:
        raise ValueError("CSV contains no data rows")

    return steps


# ── Service ────────────────────────────────────────────────────────────────────

class StructureService:
    """Business logic for publisher structure records."""

    def __init__(self, repo: StructureRepository) -> None:
        self._repo = repo

    # ── Queries ────────────────────────────────────────────────────────────────

    def list_all(self) -> list[dict]:
        """Return all structure records."""
        return self._repo.get_all_raw()

    def list_for_publisher(self, publisher_id: str) -> list[dict]:
        """Return all structures for a publisher, ordered by (offer_id, version)."""
        return [
            r for r in self._repo.get_all_raw()
            if r.get("publisher_id") == publisher_id
        ]

    def get_by_id(self, sid: str) -> dict | None:
        return self._repo.get_by_id(sid)

    def stats_by_publisher(self) -> dict[str, dict]:
        """
        Aggregate per-publisher stats for the left panel.

        Returns {publisher_id: {live_games, pending_structures,
                                 paused_structures, total_structures}}
        where live_games = count of distinct offer_ids with a live structure.
        """
        stats: dict[str, dict] = {}
        live_offers: dict[str, set] = {}

        for r in self._repo.get_all_raw():
            pid    = r.get("publisher_id", "")
            status = r.get("status", "")
            oid    = r.get("offer_id", "")

            if pid not in stats:
                stats[pid] = {
                    "live_games":          0,
                    "pending_structures":  0,
                    "paused_structures":   0,
                    "total_structures":    0,
                }
                live_offers[pid] = set()

            stats[pid]["total_structures"] += 1
            if status == "pending":
                stats[pid]["pending_structures"] += 1
            elif status == "paused":
                stats[pid]["paused_structures"] += 1
            elif status == "live":
                live_offers[pid].add(oid)

        for pid in stats:
            stats[pid]["live_games"] = len(live_offers[pid])

        return stats

    # ── Create ─────────────────────────────────────────────────────────────────

    def create(self, body: dict) -> dict:
        """
        Create a new structure version with status=pending.

        Version number is auto-incremented per (publisher_id, offer_id).
        """
        publisher_id = str(body.get("publisher_id", "")).strip()
        offer_id     = str(body.get("offer_id", "")).strip()
        if not publisher_id:
            raise ValueError("publisher_id is required")
        if not offer_id:
            raise ValueError("offer_id is required")

        version = self._repo.next_version(publisher_id, offer_id)
        record = {
            "id":            str(uuid.uuid4()),
            "publisher_id":  publisher_id,
            "offer_id":      offer_id,
            "offer_name":    str(body.get("offer_name", "") or "").strip(),
            "version":       version,
            "status":        "pending",
            "reward_steps":  body.get("reward_steps", [])
                             if isinstance(body.get("reward_steps"), list) else [],
            "tracking_link": str(body.get("tracking_link", "") or "").strip(),
            "preview_url":   str(body.get("preview_url", "") or "").strip(),
            "iap_events":    [str(e) for e in (body.get("iap_events") or []) if e],
            "created_at":    ist_now().isoformat(),
            "live_at":       None,
            "paused_at":     None,
            "created_by":    body.get("created_by"),
        }
        return self._repo.create(record)

    # ── Lifecycle transitions ──────────────────────────────────────────────────

    def make_live(self, sid: str) -> dict:
        """
        Promote a structure to Live.

        Steps:
          1. Load target — must exist.
          2. If already live, return immediately (idempotent).
          3. Pause the current live structure for the same (publisher_id, offer_id).
          4. Set target status=live, update live_at.

        Valid from status: pending OR paused (re-activation).
        Returns the newly live structure dict.
        Raises ValueError if structure not found.
        """
        target = self._repo.get_by_id(sid)
        if target is None:
            raise ValueError(f"Structure {sid!r} not found")
        if target.get("status") == "live":
            return target   # already live — idempotent

        now = ist_now().isoformat()

        # Auto-pause the currently live version (if any, and not itself)
        current_live = self._repo.get_live(target["publisher_id"], target["offer_id"])
        if current_live and current_live["id"] != sid:
            paused_copy = dict(current_live)
            paused_copy["status"]    = "paused"
            paused_copy["paused_at"] = now
            self._repo.update(current_live["id"], paused_copy)

        # Promote target
        updated = dict(target)
        updated["status"]  = "live"
        updated["live_at"] = now
        return self._repo.update(sid, updated)

    def delete(self, sid: str) -> bool:
        """
        Delete a structure.  Only allowed for pending or paused structures.

        Returns True on success.
        Raises ValueError if the structure is live (deletion of live records
        is forbidden to preserve history).
        Raises ValueError if the structure is not found.
        """
        record = self._repo.get_by_id(sid)
        if record is None:
            raise ValueError(f"Structure {sid!r} not found")
        if record.get("status") == "live":
            raise ValueError("Cannot delete a live structure — pause it first")
        return self._repo.delete(sid)

    def pause(self, sid: str) -> dict | None:
        """
        Pause a structure.  Sets status=paused, paused_at=now.

        Returns the updated record, or None if not found.
        Idempotent if already paused.
        """
        record = self._repo.get_by_id(sid)
        if record is None:
            return None
        if record.get("status") == "paused":
            return record   # already paused — idempotent

        updated = dict(record)
        updated["status"]    = "paused"
        updated["paused_at"] = ist_now().isoformat()
        return self._repo.update(sid, updated)

    # ── Clone ──────────────────────────────────────────────────────────────────

    def clone(self, body: dict) -> dict:
        """
        Clone any structure version to a target publisher+offer.

        Copies ALL structural fields:
            reward_steps, tracking_link, preview_url, iap_events
        (User may edit after cloning if required — per design spec.)

        body keys:
            source_id           — UUID of the source structure
            target_publisher_id — publisher_id for the clone
            target_offer_id     — offer_id for the clone
            target_offer_name   — display name (optional; falls back to source)
            created_by          — optional auth context

        Returns the created clone record (status=pending, new version).
        Raises ValueError if source not found or required fields missing.
        """
        source_id         = str(body.get("source_id", "")).strip()
        target_publisher  = str(body.get("target_publisher_id", "")).strip()
        target_offer      = str(body.get("target_offer_id", "")).strip()
        target_offer_name = str(body.get("target_offer_name", "")).strip()

        if not source_id:        raise ValueError("source_id is required")
        if not target_publisher: raise ValueError("target_publisher_id is required")
        if not target_offer:     raise ValueError("target_offer_id is required")

        source = self._repo.get_by_id(source_id)
        if source is None:
            raise ValueError(f"Source structure {source_id!r} not found")

        version = self._repo.next_version(target_publisher, target_offer)
        record = {
            "id":            str(uuid.uuid4()),
            "publisher_id":  target_publisher,
            "offer_id":      target_offer,
            "offer_name":    target_offer_name or source.get("offer_name", ""),
            "version":       version,
            "status":        "pending",
            # All structural fields copied from source
            "reward_steps":  source.get("reward_steps", []),
            "tracking_link": source.get("tracking_link", ""),
            "preview_url":   source.get("preview_url", ""),
            "iap_events":    source.get("iap_events", []),
            "created_at":    ist_now().isoformat(),
            "live_at":       None,
            "paused_at":     None,
            "created_by":    body.get("created_by"),
        }
        return self._repo.create(record)

    # ── CSV ────────────────────────────────────────────────────────────────────

    def to_csv(self, sid: str) -> str | None:
        """
        Export a structure's reward_steps as a lossless CSV string.

        Format (canonical — matches the funnel sample CSV):
            goal,expected_percent,time_minutes,payout
            install,100,0,5.00
            ...

        Returns None if the structure is not found.
        """
        record = self._repo.get_by_id(sid)
        if record is None:
            return None

        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["goal", "expected_percent", "time_minutes", "payout"])
        for step in record.get("reward_steps", []):
            writer.writerow([
                step.get("goal", ""),
                step.get("expected_percent", 0),
                step.get("time_minutes", 0),
                step.get("payout", 0),
            ])
        return output.getvalue()

    def from_csv(
        self,
        csv_text: str,
        publisher_id: str,
        offer_id: str,
        offer_name: str = "",
        tracking_link: str = "",
        preview_url: str = "",
        iap_events: list | None = None,
        created_by: str | None = None,
    ) -> dict:
        """
        Parse a reward-structure CSV and create a new pending structure version.

        Raises ValueError on parse errors.
        Returns the created structure record.
        """
        steps = _parse_reward_csv(csv_text)
        return self.create({
            "publisher_id":  publisher_id,
            "offer_id":      offer_id,
            "offer_name":    offer_name,
            "reward_steps":  steps,
            "tracking_link": tracking_link,
            "preview_url":   preview_url,
            "iap_events":    iap_events or [],
            "created_by":    created_by,
        })
