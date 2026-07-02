"""
JsonOverrideRepository — OverrideRepository backed by a JSON file.

Storage: data/config/manual_overrides.json (created on first write).
Upsert semantics: if a record with the same (date, publisher_id, offer_id)
already exists it is updated in-place; otherwise a new record is appended.
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from backend.repositories.base import OverrideRepository


class JsonOverrideRepository(OverrideRepository):

    def __init__(self, file_path: Path) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Raw I/O ───────────────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            with open(self._path) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Failed to read {self._path}: {exc}")
            return []

    def _save(self, records: list[dict]) -> None:
        try:
            with open(self._path, "w") as f:
                json.dump(records, f, indent=2)
        except OSError as exc:
            logger.error(f"Failed to write {self._path}: {exc}")
            raise

    # ── OverrideRepository interface ──────────────────────────────────────────

    def get_all(self) -> list[dict]:
        records = self._load()
        # Sort by date desc, then publisher_id, offer_id
        return sorted(records, key=lambda r: (r.get("date", ""), r.get("publisher_id", ""), r.get("offer_id", "")), reverse=True)

    def get_by_id(self, override_id: str) -> dict | None:
        for r in self._load():
            if r.get("id") == override_id:
                return r
        return None

    def get_by_key(self, date: str, publisher_id: str, offer_id: str) -> dict | None:
        for r in self._load():
            if (
                r.get("date") == date
                and r.get("publisher_id") == publisher_id
                and r.get("offer_id") == offer_id
            ):
                return r
        return None

    def upsert(self, data: dict) -> dict:
        records = self._load()
        date         = data["date"]
        publisher_id = data["publisher_id"]
        offer_id     = data["offer_id"]

        for i, rec in enumerate(records):
            if (
                rec.get("date") == date
                and rec.get("publisher_id") == publisher_id
                and rec.get("offer_id") == offer_id
            ):
                # Update existing
                merged = dict(rec)
                merged.update(data)
                merged["id"] = rec["id"]        # preserve original id
                records[i] = merged
                self._save(records)
                return merged

        # Create new
        records.append(data)
        self._save(records)
        return data

    def delete(self, override_id: str) -> bool:
        records = self._load()
        new_records = [r for r in records if r.get("id") != override_id]
        if len(new_records) == len(records):
            return False
        self._save(new_records)
        return True
