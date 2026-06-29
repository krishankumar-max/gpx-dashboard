"""
JsonPublisherRepository — PublisherRepository backed by a JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from backend.models.publisher import Publisher
from backend.repositories.base import PublisherRepository


class JsonPublisherRepository(PublisherRepository):
    """JSON-file backed implementation of PublisherRepository."""

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

    def get_all(self) -> list[Publisher]:
        return [Publisher.model_validate(r) for r in self.get_all_raw()]

    def get_by_id(self, record_id: str) -> Publisher | None:
        for r in self.get_all_raw():
            if r.get("id") == record_id:
                return Publisher.model_validate(r)
        return None

    def get_by_publisher_id(self, publisher_id: str) -> Publisher | None:
        for r in self.get_all_raw():
            if str(r.get("publisher_id", "")).strip() == str(publisher_id).strip():
                return Publisher.model_validate(r)
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

    def get_enabled_partner_ids(self) -> tuple[list[int], dict[str, str]]:
        partner_ids: list[int] = []
        partner_names: dict[str, str] = {}
        for rec in self.get_all_raw():
            # Records without an "enabled" key are treated as enabled (backward compat)
            if not rec.get("enabled", True):
                continue
            pid_str = str(rec.get("publisher_id", "")).strip()
            try:
                partner_ids.append(int(pid_str))
                partner_names[pid_str] = str(rec.get("partner_name") or "Unknown").strip()
            except ValueError:
                logger.warning(
                    f"JsonPublisherRepository: non-numeric publisher_id {pid_str!r} skipped."
                )
        return partner_ids, partner_names
