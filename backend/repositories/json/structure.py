"""
JsonStructureRepository — StructureRepository backed by a JSON file.

Storage: data/config/publisher_structures.json (created on first write).
All mutations go through save_all_raw so the file is the single source
of truth, matching the pattern used by all other JSON repositories.
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from backend.repositories.base import StructureRepository


class JsonStructureRepository(StructureRepository):

    def __init__(self, file_path: Path) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Raw I/O ───────────────────────────────────────────────────────────────

    def get_all_raw(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            with open(self._path) as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Failed to read {self._path}: {exc}")
            return []

    def save_all_raw(self, records: list[dict]) -> None:
        try:
            with open(self._path, "w") as f:
                json.dump(records, f, indent=2)
        except OSError as exc:
            logger.error(f"Failed to write {self._path}: {exc}")
            raise

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_by_id(self, sid: str) -> dict | None:
        for r in self.get_all_raw():
            if r.get("id") == sid:
                return r
        return None

    def get_by_publisher_offer(self, publisher_id: str, offer_id: str) -> list[dict]:
        records = [
            r for r in self.get_all_raw()
            if r.get("publisher_id") == publisher_id and r.get("offer_id") == offer_id
        ]
        return sorted(records, key=lambda r: r.get("version", 0))

    def get_live(self, publisher_id: str, offer_id: str) -> dict | None:
        for r in self.get_all_raw():
            if (
                r.get("publisher_id") == publisher_id
                and r.get("offer_id") == offer_id
                and r.get("status") == "live"
            ):
                return r
        return None

    def next_version(self, publisher_id: str, offer_id: str) -> int:
        versions = [
            r.get("version", 0)
            for r in self.get_all_raw()
            if r.get("publisher_id") == publisher_id and r.get("offer_id") == offer_id
        ]
        return max(versions, default=0) + 1

    # ── Mutations ─────────────────────────────────────────────────────────────

    def create(self, data: dict) -> dict:
        records = self.get_all_raw()
        records.append(data)
        self.save_all_raw(records)
        return data

    def update(self, sid: str, data: dict) -> dict | None:
        records = self.get_all_raw()
        for i, rec in enumerate(records):
            if rec.get("id") == sid:
                records[i] = data
                self.save_all_raw(records)
                return data
        return None

    def delete(self, sid: str) -> bool:
        records = self.get_all_raw()
        new_records = [r for r in records if r.get("id") != sid]
        if len(new_records) == len(records):
            return False
        self.save_all_raw(new_records)
        return True
