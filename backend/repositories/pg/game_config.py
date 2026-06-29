"""
PgGameConfigRepository — GameConfigRepository backed by PostgreSQL.

Uses SQLAlchemy 2.0 ORM.  All mutations go through the ORM so that
created_at / updated_at are handled automatically.

get_all_raw / save_all_raw preserve backward-compatibility with
existing cache-layer callers that work with plain dicts.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from backend.models.game_config import GameConfig
from backend.repositories.base import GameConfigRepository


def _orm_to_dict(row) -> dict:
    """Convert a GameConfigORM row to a plain dict."""
    return {
        "id":               row.id,
        "offer_id":         row.offer_id,
        "offer_name":       row.offer_name,
        "game_type":        row.game_type,
        "payable_goals":    row.payable_goals    or [],
        "publisher_kpi":    row.publisher_kpi    or {},
        "client_kpi":       row.client_kpi       or {},
        "expected_funnel":  row.expected_funnel,
        "tracking_links":   row.tracking_links   or [],
        "play_store":       row.play_store,
        "assets":           row.assets           or [],
        "expected_margin":  row.expected_margin,
        "campaign_status":  row.campaign_status,
        "platform":         row.platform,
        "notes":            row.notes,
        "client_notes":     row.client_notes,
        "configured_at":    row.configured_at,
        "updated_at":       row.updated_at,
    }


def _dict_to_orm_kwargs(data: dict) -> dict:
    """Extract ORM column values from a raw dict."""
    return {
        "id":               data.get("id"),
        "offer_id":         str(data.get("offer_id", "")).strip(),
        "offer_name":       str(data.get("offer_name", "")).strip(),
        "game_type":        str(data.get("game_type", "CPI")).strip(),
        "payable_goals":    data.get("payable_goals") or [],
        "publisher_kpi":    data.get("publisher_kpi") or {},
        "client_kpi":       data.get("client_kpi")    or {},
        "expected_funnel":  data.get("expected_funnel"),
        "tracking_links":   data.get("tracking_links") or [],
        "play_store":       data.get("play_store"),
        "assets":           data.get("assets")         or [],
        "expected_margin":  data.get("expected_margin"),
        "campaign_status":  data.get("campaign_status"),
        "platform":         data.get("platform"),
        "notes":            data.get("notes"),
        "client_notes":     data.get("client_notes"),
        "configured_at":    data.get("configured_at"),
        "updated_at":       data.get("updated_at"),
    }


class PgGameConfigRepository(GameConfigRepository):
    """PostgreSQL-backed implementation of GameConfigRepository."""

    def __init__(self) -> None:
        # Deferred import so that running without DATABASE_URL doesn't crash at startup.
        from backend.repositories.pg.schema import GameConfigORM  # noqa: F401
        from backend.repositories.pg.db import get_session         # noqa: F401

    # ── Raw dict interface (backward-compat) ──────────────────────────────────

    def get_all_raw(self) -> list[dict]:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import GameConfigORM
        with get_session() as session:
            rows = session.query(GameConfigORM).order_by(GameConfigORM.offer_name).all()
            return [_orm_to_dict(r) for r in rows]

    def save_all_raw(self, records: list[dict]) -> None:
        """
        Full replacement — deletes all rows then inserts.
        Used by legacy callers that bulk-replace the entire config list.
        """
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import GameConfigORM
        with get_session() as session:
            session.query(GameConfigORM).delete()
            for data in records:
                kwargs = _dict_to_orm_kwargs(data)
                if not kwargs["id"]:
                    import uuid
                    kwargs["id"] = str(uuid.uuid4())
                session.add(GameConfigORM(**kwargs))
        logger.debug(f"PgGameConfigRepository.save_all_raw: replaced with {len(records)} records.")

    # ── Typed interface ───────────────────────────────────────────────────────

    def get_all(self) -> list[GameConfig]:
        return [GameConfig.model_validate(r) for r in self.get_all_raw()]

    def get_by_id(self, record_id: str) -> GameConfig | None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import GameConfigORM
        with get_session() as session:
            row = session.get(GameConfigORM, record_id)
            if row is None:
                return None
            return GameConfig.model_validate(_orm_to_dict(row))

    def get_by_offer_id(self, offer_id: str) -> GameConfig | None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import GameConfigORM
        with get_session() as session:
            row = (
                session.query(GameConfigORM)
                .filter(GameConfigORM.offer_id == str(offer_id).strip())
                .first()
            )
            if row is None:
                return None
            return GameConfig.model_validate(_orm_to_dict(row))

    def create(self, data: dict) -> dict:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import GameConfigORM
        import uuid
        kwargs = _dict_to_orm_kwargs(data)
        if not kwargs["id"]:
            kwargs["id"] = str(uuid.uuid4())
        with get_session() as session:
            row = GameConfigORM(**kwargs)
            session.add(row)
            session.flush()
            result = _orm_to_dict(row)
        logger.debug(f"PgGameConfigRepository.create: {result['id']}")
        return result

    def update(self, record_id: str, data: dict) -> dict | None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import GameConfigORM
        with get_session() as session:
            row = session.get(GameConfigORM, record_id)
            if row is None:
                return None
            kwargs = _dict_to_orm_kwargs(data)
            for k, v in kwargs.items():
                if k != "id":
                    setattr(row, k, v)
            session.flush()
            result = _orm_to_dict(row)
        logger.debug(f"PgGameConfigRepository.update: {record_id}")
        return result

    def delete(self, record_id: str) -> bool:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import GameConfigORM
        with get_session() as session:
            row = session.get(GameConfigORM, record_id)
            if row is None:
                return False
            session.delete(row)
        logger.debug(f"PgGameConfigRepository.delete: {record_id}")
        return True
