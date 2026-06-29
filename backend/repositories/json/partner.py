"""
JsonPartnerRepository — PartnerRepository backed by a JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from backend.models.partner import Partner
from backend.repositories.base import PartnerRepository


class JsonPartnerRepository(PartnerRepository):
    """JSON-file backed implementation of PartnerRepository."""

    def __init__(self, file_path: Path) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

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

    def get_all(self) -> list[Partner]:
        return [Partner.model_validate(r) for r in self.get_all_raw()]

    def get_by_id(self, record_id: str) -> Partner | None:
        for r in self.get_all_raw():
            if r.get("id") == record_id:
                return Partner.model_validate(r)
        return None

    def get_by_email(self, email: str) -> Partner | None:
        email = email.lower().strip()
        for r in self.get_all_raw():
            if str(r.get("email", "")).lower().strip() == email:
                return Partner.model_validate(r)
        return None

    def create(self, data: dict) -> dict:
        records = self.get_all_raw()
        records.append(data)
        self.save_all_raw(records)
        return data

    def update(self, record_id: str, data: dict) -> dict | None:
        records = self.get_all_raw()
        for i, rec in enumerate(records):
            if rec.get("id") == record_id:
                records[i] = data
                self.save_all_raw(records)
                return data
        return None

    def delete(self, record_id: str) -> bool:
        records     = self.get_all_raw()
        new_records = [r for r in records if r.get("id") != record_id]
        if len(new_records) == len(records):
            return False
        self.save_all_raw(new_records)
        return True
