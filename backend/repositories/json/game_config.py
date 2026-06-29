"""
JsonGameConfigRepository — GameConfigRepository backed by a JSON file.

Wraps the existing read/write pattern from app.py:
    _cfg_read(_GAME_CONFIGS_FILE)   →  get_all_raw()
    _cfg_write(_GAME_CONFIGS_FILE)  →  save_all_raw()

All mutating operations (create, update, delete) go through save_all_raw
so the JSON file remains the single source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from backend.models.game_config import GameConfig
from backend.repositories.base import GameConfigRepository


class JsonGameConfigRepository(GameConfigRepository):
    """JSON-file backed implementation of GameConfigRepository."""

    def __init__(self, file_path: Path) -> None:
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Raw I/O (backward-compat) ─────────────────────────────────────────────

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

    # ── Typed interface ───────────────────────────────────────────────────────

    def get_all(self) -> list[GameConfig]:
        return [GameConfig.model_validate(r) for r in self.get_all_raw()]

    def get_by_id(self, record_id: str) -> GameConfig | None:
        for r in self.get_all_raw():
            if r.get("id") == record_id:
                return GameConfig.model_validate(r)
        return None

    def get_by_offer_id(self, offer_id: str) -> GameConfig | None:
        for r in self.get_all_raw():
            if str(r.get("offer_id", "")).strip() == str(offer_id).strip():
                return GameConfig.model_validate(r)
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
