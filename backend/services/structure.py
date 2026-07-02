"""
StructureService — business logic for publisher structure versioning.

Responsibilities
----------------
- CRUD (create, list, get)
- Lifecycle transitions: make_live, pause
- Cloning (any version from any publisher+game)
- CSV import / export (lossless round-trip matching the existing funnel format)
- Publisher stats aggregation for the left panel

CSV format (simplified, user-friendly):
    Description,Goal,Payout
    Install,install,0.00
    Reach Level 5,reached_level_5,0.10

Old full format (still accepted for backward compatibility):
    goal,expected_percent,time_minutes,payout
    install,100,0,5.00

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
    # Description / display label (stored per step)
    "description":     "description",
    "label":           "description",
    "name":            "description",
    "displayname":     "description",
    # Goal / event name (required)
    "goal":            "goal",
    "goalname":        "goal",
    "goalevent":       "goal",    # "Goal Event" column header
    "event":           "goal",
    "eventname":       "goal",
    # Expected completion rate (optional, defaults to 100)
    "expectedpercent": "expected_percent",
    "expected":        "expected_percent",
    "expected%":       "expected_percent",  # "Expected %" column header
    "pct":             "expected_percent",
    "percent":         "expected_percent",
    # Time in minutes (optional, defaults to 0)
    "timeminutes":     "time_minutes",
    "timemin":         "time_minutes",      # "Time (min)" → strips () → "timemin"
    "time(min)":       "time_minutes",      # direct match with parens
    "time":            "time_minutes",
    "minutes":         "time_minutes",
    "min":             "time_minutes",
    # Payout amount (required)
    "payout":          "payout",
    "payout($)":       "payout",            # "Payout ($)" column header
    "payoutusd":       "payout",
    "bid":             "payout",
    "reward":          "payout",
    "rewardusd":       "payout",
    "amount":          "payout",
}


def _norm_header(raw: str) -> str:
    """Normalise a CSV header to a canonical key for alias lookup."""
    # Strip whitespace, lowercase, collapse spaces/underscores/hyphens
    s = raw.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return _HEADER_ALIASES.get(s, s)


def _parse_reward_csv(text: str) -> list[dict]:
    """
    Parse a reward-structure CSV and return a list of RewardStep dicts.

    Canonical format (all 5 columns, exact round-trip):
        Description,Goal Event,Expected %,Time (min),Payout ($)
        Install,install,100,0,0.00
        Reach Level 5,reached_level_5,98.33,4,0.10

    Legacy format (backward-compatible):
        Description,Goal,Payout
        Install,install,0.00

    Oldest legacy (backward-compatible):
        goal,expected_percent,time_minutes,payout
        install,100,0,5.00

    Required columns (order-independent, aliases accepted):
        Goal Event  (or Goal / event / goal_name)
        Payout ($)  (or Payout / bid / reward / amount)

    Optional columns (default if absent):
        Description     → auto-generated from Goal Event if missing
        Expected %      → defaults to 100
        Time (min)      → defaults to 0

    Per-row validation:
        Goal Event      — required, non-empty
        Expected %      — must be 0–100
        Time (min)      — must be >= 0
        Payout ($)      — must be >= 0

    Raises ValueError on fatal parse errors.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        raise ValueError("CSV is empty")

    header = [_norm_header(h) for h in lines[0].split(",")]

    required = {"goal", "payout"}
    missing  = required - set(header)
    if missing:
        readable = {"goal": "Goal Event", "payout": "Payout ($)"}
        raise ValueError(
            f"Missing required column(s): {', '.join(readable.get(c, c) for c in sorted(missing))}. "
            f"Required: Goal Event, Payout ($)"
        )

    goal_i = header.index("goal")
    pay_i  = header.index("payout")
    pct_i  = header.index("expected_percent") if "expected_percent" in header else None
    time_i = header.index("time_minutes")     if "time_minutes"     in header else None
    desc_i = header.index("description")      if "description"      in header else None

    steps: list[dict] = []
    row_errors: list[str] = []

    for line_no, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cols = line.split(",")

        goal = cols[goal_i].strip() if goal_i < len(cols) else ""
        if not goal:
            row_errors.append(f"Row {line_no}: Goal Event is required")
            continue

        raw_pct  = cols[pct_i].strip()  if pct_i  is not None and pct_i  < len(cols) else ""
        raw_time = cols[time_i].strip() if time_i is not None and time_i < len(cols) else ""
        raw_pay  = cols[pay_i].strip()  if pay_i  < len(cols) else "0"
        raw_desc = cols[desc_i].strip() if desc_i is not None and desc_i < len(cols) else ""

        # Parse + validate Expected %
        try:
            pct = float(raw_pct) if raw_pct else 100.0
        except ValueError:
            row_errors.append(f"Row {line_no}: Expected % must be a number (got \"{raw_pct}\")")
            continue
        if pct < 0 or pct > 100:
            row_errors.append(f"Row {line_no}: Expected % must be 0–100 (got {pct})")
            continue

        # Parse + validate Time (min)
        try:
            mins = float(raw_time) if raw_time else 0.0
        except ValueError:
            row_errors.append(f"Row {line_no}: Time (min) must be a number (got \"{raw_time}\")")
            continue
        if mins < 0:
            row_errors.append(f"Row {line_no}: Time (min) must be >= 0 (got {mins})")
            continue

        # Parse + validate Payout ($)
        try:
            pay = float(raw_pay) if raw_pay else 0.0
        except ValueError:
            row_errors.append(f"Row {line_no}: Payout ($) must be a number (got \"{raw_pay}\")")
            continue
        if pay < 0:
            row_errors.append(f"Row {line_no}: Payout ($) must be >= 0 (got {pay})")
            continue

        # Auto-generate description from goal event if not provided (backward compat)
        desc = raw_desc or goal.replace("_", " ").title()

        steps.append({
            "description":      desc,
            "goal":             goal,
            "expected_percent": pct,
            "time_minutes":     mins,
            "payout":           pay,
        })

    if row_errors:
        raise ValueError("; ".join(row_errors))

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
        Export a structure's reward_steps as a CSV string.

        Canonical format (all 5 columns, exact round-trip):
            Description,Goal Event,Expected %,Time (min),Payout ($)
            Install,install,100,0,0.00
            Reach Level 5,reached_level_5,98.33,4,0.10

        Decimal precision is preserved as stored.
        Description falls back to a title-cased form of Goal Event if blank.

        Returns None if the structure is not found.
        """
        record = self._repo.get_by_id(sid)
        if record is None:
            return None

        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["Description", "Goal Event", "Expected %", "Time (min)", "Payout ($)"])
        for step in record.get("reward_steps", []):
            goal   = step.get("goal", "")
            desc   = step.get("description", "") or goal.replace("_", " ").title()
            pct    = float(step.get("expected_percent", 100))
            mins   = float(step.get("time_minutes", 0))
            payout = float(step.get("payout", 0))
            # Preserve decimal precision: strip trailing zeros but keep at least 2dp for payout
            pct_s    = f"{pct:g}"
            mins_s   = f"{mins:g}"
            payout_s = f"{payout:.10g}"  # up to 10 sig figs, no trailing zeros
            writer.writerow([desc, goal, pct_s, mins_s, payout_s])
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
