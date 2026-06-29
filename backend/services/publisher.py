"""
PublisherService — business logic for publisher CRUD and map building.
"""
from __future__ import annotations

import uuid

from backend.repositories.base import PublisherRepository


def _safe_kpi(v, fallback: dict | None = None) -> dict:
    default = fallback if isinstance(fallback, dict) else {"retention": [], "roas": []}
    if not isinstance(v, dict):
        return default
    return {
        "retention": v.get("retention", []) if isinstance(v.get("retention"), list) else [],
        "roas":      v.get("roas", [])      if isinstance(v.get("roas"),      list) else [],
    }


class PublisherService:
    """Business logic for publisher configuration records."""

    def __init__(self, repo: PublisherRepository) -> None:
        self._repo = repo

    # ── Read ──────────────────────────────────────────────────────────────────

    def list(self) -> list[dict]:
        return self._repo.get_all_raw()

    def get_publisher_ids(self) -> set[str]:
        """Return the set of string publisher IDs for all configured publishers."""
        return {
            str(p["publisher_id"]).strip()
            for p in self._repo.get_all_raw()
            if p.get("publisher_id") and str(p.get("publisher_id", "")).strip()
        }

    def get_partner_names(self) -> dict[str, str]:
        """Return {publisher_id: partner_name} for all configured publishers."""
        result: dict[str, str] = {}
        for p in self._repo.get_all_raw():
            pid  = str(p.get("publisher_id", "")).strip()
            name = str(p.get("partner_name", "")).strip()
            if pid:
                result[pid] = name
        return result

    def get_map(self) -> dict[str, str]:
        """Return {publisher_id: partner_name} — used by /api/publishers/map."""
        return self.get_partner_names()

    # ── Write ─────────────────────────────────────────────────────────────────

    def create(self, body: dict) -> dict:
        """Validate and persist a new publisher record."""
        if not body.get("publisher_id"):
            raise ValueError("publisher_id is required")
        if not str(body.get("partner_name", "")).strip():
            raise ValueError("partner_name is required")

        record = {
            "id":              str(uuid.uuid4()),
            "publisher_id":    str(body.get("publisher_id", "")).strip(),
            "partner_name":    str(body.get("partner_name", "")).strip(),
            "game_name":       str(body.get("game_name",   "")).strip(),
            "game_id":         str(body.get("game_id",     "")).strip(),
            "game_type":       str(body.get("game_type",   "")).strip(),
            "payable_goals":   body.get("payable_goals", []) if isinstance(body.get("payable_goals"), list) else [],
            "publisher_kpi":   _safe_kpi(body.get("publisher_kpi")),
            "client_kpi":      _safe_kpi(body.get("client_kpi")),
            "expected_funnel": body.get("expected_funnel", []) if isinstance(body.get("expected_funnel"), list) else [],
            "expected_margin": float(body.get("expected_margin", 0) or 0),
        }
        return self._repo.create(record)

    def update(self, pid: str, body: dict) -> dict | None:
        """Update a publisher record by id.  Returns updated dict or None."""
        records = self._repo.get_all_raw()
        for rec in records:
            if rec.get("id") == pid:
                rec.update({
                    "publisher_id":   str(body.get("publisher_id",   rec["publisher_id"])).strip(),
                    "partner_name":   str(body.get("partner_name",   rec.get("partner_name",""))).strip(),
                    "game_name":      str(body.get("game_name",       rec.get("game_name",""))).strip(),
                    "game_id":        str(body.get("game_id",         rec.get("game_id",""))).strip(),
                    "game_type":      str(body.get("game_type",       rec.get("game_type",""))).strip(),
                    "payable_goals":  body.get("payable_goals", rec.get("payable_goals", []))
                                      if isinstance(body.get("payable_goals"), list)
                                      else rec.get("payable_goals", []),
                    "publisher_kpi":  _safe_kpi(body.get("publisher_kpi"), rec.get("publisher_kpi")),
                    "client_kpi":     _safe_kpi(body.get("client_kpi"),    rec.get("client_kpi")),
                    "expected_funnel": body.get("expected_funnel", rec.get("expected_funnel", []))
                                       if isinstance(body.get("expected_funnel"), list)
                                       else rec.get("expected_funnel", []),
                    "expected_margin": float(body.get("expected_margin", rec.get("expected_margin", 0)) or 0),
                })
                self._repo.save_all_raw(records)
                return rec
        return None

    def delete(self, pid: str) -> bool:
        """Delete by id.  Returns True if found and deleted."""
        records     = self._repo.get_all_raw()
        new_records = [r for r in records if r.get("id") != pid]
        if len(new_records) == len(records):
            return False
        self._repo.save_all_raw(new_records)
        return True
