"""
PgOverrideRepository — OverrideRepository backed by PostgreSQL.

Uses SQLAlchemy 2.0 ORM.  Upsert is implemented as a SELECT-then-UPDATE-or-INSERT
pattern so it works on all PostgreSQL versions without requiring ON CONFLICT syntax.
"""
from __future__ import annotations

from loguru import logger

from backend.repositories.base import OverrideRepository


def _orm_to_dict(row) -> dict:
    return {
        "id":               row.id,
        "date":             row.date,
        "publisher_id":     row.publisher_id,
        "publisher_name":   row.publisher_name,
        "offer_id":         row.offer_id,
        "offer_name":       row.offer_name,
        "revenue_override": row.revenue_override,
        "cost_override":    row.cost_override,
        "reason":           row.reason,
        "notes":            row.notes,
        "created_at":       row.created_at,
        "updated_at":       row.updated_at,
        "created_by":       row.created_by,
    }


class PgOverrideRepository(OverrideRepository):
    """PostgreSQL-backed implementation of OverrideRepository."""

    def __init__(self) -> None:
        from backend.repositories.pg.schema import ManualOverrideORM  # noqa: F401
        from backend.repositories.pg.db import get_session              # noqa: F401

    def get_all(self) -> list[dict]:
        from backend.repositories.pg.schema import ManualOverrideORM
        from backend.repositories.pg.db import get_session
        with get_session() as session:
            rows = (
                session.query(ManualOverrideORM)
                .order_by(ManualOverrideORM.date.desc(),
                          ManualOverrideORM.publisher_id,
                          ManualOverrideORM.offer_id)
                .all()
            )
            return [_orm_to_dict(r) for r in rows]

    def get_by_id(self, override_id: str) -> dict | None:
        from backend.repositories.pg.schema import ManualOverrideORM
        from backend.repositories.pg.db import get_session
        with get_session() as session:
            row = session.get(ManualOverrideORM, override_id)
            return _orm_to_dict(row) if row else None

    def get_by_key(self, date: str, publisher_id: str, offer_id: str) -> dict | None:
        from backend.repositories.pg.schema import ManualOverrideORM
        from backend.repositories.pg.db import get_session
        with get_session() as session:
            row = (
                session.query(ManualOverrideORM)
                .filter_by(date=date, publisher_id=publisher_id, offer_id=offer_id)
                .first()
            )
            return _orm_to_dict(row) if row else None

    def upsert(self, data: dict) -> dict:
        from backend.repositories.pg.schema import ManualOverrideORM
        from backend.repositories.pg.db import get_session
        date         = data["date"]
        publisher_id = data["publisher_id"]
        offer_id     = data["offer_id"]
        with get_session() as session:
            row = (
                session.query(ManualOverrideORM)
                .filter_by(date=date, publisher_id=publisher_id, offer_id=offer_id)
                .first()
            )
            if row:
                # Update existing
                row.publisher_name   = data.get("publisher_name", row.publisher_name)
                row.offer_name       = data.get("offer_name", row.offer_name)
                row.revenue_override = data.get("revenue_override")
                row.cost_override    = data.get("cost_override")
                row.reason           = data.get("reason")
                row.notes            = data.get("notes")
                row.updated_at       = data.get("updated_at", row.updated_at)
                result = _orm_to_dict(row)
            else:
                # Create new
                row = ManualOverrideORM(**{k: v for k, v in data.items()
                                           if hasattr(ManualOverrideORM, k)})
                session.add(row)
                session.flush()
                result = _orm_to_dict(row)
            return result

    def delete(self, override_id: str) -> bool:
        from backend.repositories.pg.schema import ManualOverrideORM
        from backend.repositories.pg.db import get_session
        with get_session() as session:
            row = session.get(ManualOverrideORM, override_id)
            if row is None:
                return False
            session.delete(row)
            return True
