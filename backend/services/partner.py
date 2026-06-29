"""
PartnerService — business logic for client/partner CRUD.

Field-name contract
-------------------
The API accepts both the legacy schema (client_name, games, bid, kpi, notes)
and the current Partner model schema (partner_name, company_name, email,
password_hash, status).  partner_name takes precedence over client_name so
that PgPartnerRepository._dict_to_orm_kwargs() finds the correct key while
JSON-backend records remain backward-compatible.

Legacy → canonical aliases (accepted on input):
    client_name  →  partner_name
"""
from __future__ import annotations

import uuid

from backend.repositories.base import PartnerRepository


def _resolve_name(body: dict, existing: dict | None = None) -> str:
    """Return partner_name, falling back to client_name for backward compat."""
    explicit = str(body.get("partner_name", "")).strip()
    if explicit:
        return explicit
    legacy = str(body.get("client_name", "")).strip()
    if legacy:
        return legacy
    if existing is not None:
        return str(existing.get("partner_name") or existing.get("client_name") or "").strip()
    return ""


class PartnerService:
    """Business logic for partner (client) configuration records."""

    def __init__(self, repo: PartnerRepository) -> None:
        self._repo = repo

    def list(self) -> list[dict]:
        return self._repo.get_all_raw()

    def create(self, body: dict) -> dict:
        partner_name = _resolve_name(body)
        if not partner_name:
            raise ValueError("partner_name (or client_name) is required")

        record = {
            "id":           str(uuid.uuid4()),
            # ── Current schema (used by PgPartnerRepository) ──────────────
            "partner_name": partner_name,
            "company_name": str(body.get("company_name", "")).strip(),
            "email":        str(body.get("email",        "")).strip().lower(),
            "password_hash": str(body.get("password_hash", "")),
            "status":       str(body.get("status", "active")).strip(),
            # ── Legacy fields (kept for JSON backward compat + frontend) ──
            "client_name":  partner_name,   # mirror so old readers still work
            "games":        str(body.get("games", "")).strip(),
            "bid":          float(body.get("bid", 0) or 0),
            "kpi":          str(body.get("kpi",   "")).strip(),
            "notes":        str(body.get("notes", "")).strip(),
        }
        return self._repo.create(record)

    def update(self, cid: str, body: dict) -> dict | None:
        records = self._repo.get_all_raw()
        for rec in records:
            if rec.get("id") == cid:
                partner_name = _resolve_name(body, rec)
                rec.update({
                    # ── Current schema ────────────────────────────────────
                    "partner_name": partner_name,
                    "company_name": str(body.get("company_name", rec.get("company_name", ""))).strip(),
                    "email":        str(body.get("email", rec.get("email", ""))).strip().lower(),
                    "password_hash": str(body.get("password_hash", rec.get("password_hash", ""))),
                    "status":       str(body.get("status", rec.get("status", "active"))).strip(),
                    # ── Legacy fields ─────────────────────────────────────
                    "client_name":  partner_name,
                    "games":        str(body.get("games",  rec.get("games",  ""))).strip(),
                    "bid":          float(body.get("bid",  rec.get("bid", 0)) or 0),
                    "kpi":          str(body.get("kpi",   rec.get("kpi",   ""))).strip(),
                    "notes":        str(body.get("notes", rec.get("notes", ""))).strip(),
                })
                self._repo.save_all_raw(records)
                return rec
        return None

    def delete(self, cid: str) -> bool:
        records     = self._repo.get_all_raw()
        new_records = [r for r in records if r.get("id") != cid]
        if len(new_records) == len(records):
            return False
        self._repo.save_all_raw(new_records)
        return True
