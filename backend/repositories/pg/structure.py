"""
PgStructureRepository — StructureRepository backed by PostgreSQL.

Uses SQLAlchemy 2.0 ORM, following the same pattern as PgGameConfigRepository.
All mutations go through the ORM session; structural payload columns are never
overwritten — only status, live_at, and paused_at may change after creation.
"""
from __future__ import annotations

from loguru import logger

from backend.repositories.base import StructureRepository


def _orm_to_dict(row) -> dict:
    """Convert a PublisherStructureORM row to a plain dict."""
    return {
        "id":            row.id,
        "publisher_id":  row.publisher_id,
        "offer_id":      row.offer_id,
        "offer_name":    row.offer_name or "",
        "version":       row.version,
        "status":        row.status,
        "reward_steps":  row.reward_steps  or [],
        "tracking_link": row.tracking_link or "",
        "preview_url":   row.preview_url   or "",
        "iap_events":    row.iap_events    or [],
        "created_at":    row.created_at,
        "live_at":       row.live_at,
        "paused_at":     row.paused_at,
        "created_by":    row.created_by,
    }


def _data_to_kwargs(data: dict) -> dict:
    """Extract ORM column values from a plain dict."""
    return {
        "id":            data.get("id"),
        "publisher_id":  str(data.get("publisher_id", "")).strip(),
        "offer_id":      str(data.get("offer_id", "")).strip(),
        "offer_name":    str(data.get("offer_name", "")).strip(),
        "version":       int(data.get("version", 1)),
        "status":        str(data.get("status", "pending")),
        "reward_steps":  data.get("reward_steps")  or [],
        "tracking_link": data.get("tracking_link") or "",
        "preview_url":   data.get("preview_url")   or "",
        "iap_events":    data.get("iap_events")    or [],
        "created_at":    data.get("created_at"),
        "live_at":       data.get("live_at"),
        "paused_at":     data.get("paused_at"),
        "created_by":    data.get("created_by"),
    }


class PgStructureRepository(StructureRepository):
    """PostgreSQL-backed implementation of StructureRepository."""

    def __init__(self) -> None:
        from backend.repositories.pg.schema import PublisherStructureORM  # noqa: F401
        from backend.repositories.pg.db     import get_session             # noqa: F401

    # ── Raw dict interface ────────────────────────────────────────────────────

    def get_all_raw(self) -> list[dict]:
        from backend.repositories.pg.db     import get_session
        from backend.repositories.pg.schema import PublisherStructureORM
        with get_session() as session:
            rows = (
                session.query(PublisherStructureORM)
                .order_by(
                    PublisherStructureORM.publisher_id,
                    PublisherStructureORM.offer_id,
                    PublisherStructureORM.version,
                )
                .all()
            )
            return [_orm_to_dict(r) for r in rows]

    def save_all_raw(self, records: list[dict]) -> None:
        from backend.repositories.pg.db     import get_session
        from backend.repositories.pg.schema import PublisherStructureORM
        with get_session() as session:
            session.query(PublisherStructureORM).delete()
            for data in records:
                kw = _data_to_kwargs(data)
                if not kw["id"]:
                    import uuid
                    kw["id"] = str(uuid.uuid4())
                session.add(PublisherStructureORM(**kw))
        logger.debug(f"PgStructureRepository.save_all_raw: {len(records)} records.")

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_by_id(self, sid: str) -> dict | None:
        from backend.repositories.pg.db     import get_session
        from backend.repositories.pg.schema import PublisherStructureORM
        with get_session() as session:
            row = session.get(PublisherStructureORM, sid)
            return _orm_to_dict(row) if row else None

    def get_by_publisher_offer(self, publisher_id: str, offer_id: str) -> list[dict]:
        from backend.repositories.pg.db     import get_session
        from backend.repositories.pg.schema import PublisherStructureORM
        with get_session() as session:
            rows = (
                session.query(PublisherStructureORM)
                .filter_by(publisher_id=publisher_id, offer_id=offer_id)
                .order_by(PublisherStructureORM.version)
                .all()
            )
            return [_orm_to_dict(r) for r in rows]

    def get_live(self, publisher_id: str, offer_id: str) -> dict | None:
        from backend.repositories.pg.db     import get_session
        from backend.repositories.pg.schema import PublisherStructureORM
        with get_session() as session:
            row = (
                session.query(PublisherStructureORM)
                .filter_by(publisher_id=publisher_id, offer_id=offer_id, status="live")
                .first()
            )
            return _orm_to_dict(row) if row else None

    def next_version(self, publisher_id: str, offer_id: str) -> int:
        from sqlalchemy              import func
        from backend.repositories.pg.db     import get_session
        from backend.repositories.pg.schema import PublisherStructureORM
        with get_session() as session:
            result = (
                session.query(func.max(PublisherStructureORM.version))
                .filter_by(publisher_id=publisher_id, offer_id=offer_id)
                .scalar()
            )
            return (result or 0) + 1

    # ── Mutations ─────────────────────────────────────────────────────────────

    def create(self, data: dict) -> dict:
        import uuid as _uuid
        from backend.repositories.pg.db     import get_session
        from backend.repositories.pg.schema import PublisherStructureORM
        kw = _data_to_kwargs(data)
        if not kw["id"]:
            kw["id"] = str(_uuid.uuid4())
        with get_session() as session:
            row = PublisherStructureORM(**kw)
            session.add(row)
            session.flush()
            result = _orm_to_dict(row)
        logger.debug(f"PgStructureRepository.create: {result['id']}")
        return result

    def update(self, sid: str, data: dict) -> dict | None:
        from backend.repositories.pg.db     import get_session
        from backend.repositories.pg.schema import PublisherStructureORM
        with get_session() as session:
            row = session.get(PublisherStructureORM, sid)
            if row is None:
                return None
            kw = _data_to_kwargs(data)
            for k, v in kw.items():
                if k != "id":
                    setattr(row, k, v)
            session.flush()
            result = _orm_to_dict(row)
        logger.debug(f"PgStructureRepository.update: {sid}")
        return result
