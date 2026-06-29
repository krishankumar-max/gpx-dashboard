"""
PgPublisherRepository — PublisherRepository backed by PostgreSQL.
"""

from __future__ import annotations

from loguru import logger

from backend.models.publisher import Publisher
from backend.repositories.base import PublisherRepository


def _orm_to_dict(row) -> dict:
    return {
        "id":               row.id,
        "publisher_id":     row.publisher_id,
        "partner_name":     row.partner_name,
        "enabled":          bool(row.enabled) if row.enabled is not None else True,
        "game_name":        row.game_name,
        "game_id":          row.game_id,
        "game_type":        row.game_type,
        "payable_goals":    row.payable_goals    or [],
        "publisher_kpi":    row.publisher_kpi    or {},
        "client_kpi":       row.client_kpi       or {},
        "expected_funnel":  row.expected_funnel,
        "expected_margin":  row.expected_margin  or 0.0,
    }


def _dict_to_orm_kwargs(data: dict) -> dict:
    return {
        "id":               data.get("id"),
        "publisher_id":     str(data.get("publisher_id", "")).strip(),
        "partner_name":     str(data.get("partner_name", "")).strip(),
        "enabled":          bool(data.get("enabled", True)),
        "game_name":        str(data.get("game_name",   "")).strip(),
        "game_id":          str(data.get("game_id",     "")).strip(),
        "game_type":        str(data.get("game_type",   "")).strip(),
        "payable_goals":    data.get("payable_goals")  or [],
        "publisher_kpi":    data.get("publisher_kpi")  or {},
        "client_kpi":       data.get("client_kpi")     or {},
        "expected_funnel":  data.get("expected_funnel"),
        "expected_margin":  float(data.get("expected_margin") or 0.0),
    }


class PgPublisherRepository(PublisherRepository):

    def __init__(self) -> None:
        from backend.repositories.pg.schema import PublisherORM  # noqa: F401
        from backend.repositories.pg.db import get_session        # noqa: F401

    # ── Raw dict interface ────────────────────────────────────────────────────

    def get_all_raw(self) -> list[dict]:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PublisherORM
        with get_session() as session:
            rows = session.query(PublisherORM).order_by(PublisherORM.publisher_id).all()
            return [_orm_to_dict(r) for r in rows]

    def save_all_raw(self, records: list[dict]) -> None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PublisherORM
        with get_session() as session:
            session.query(PublisherORM).delete()
            for data in records:
                kwargs = _dict_to_orm_kwargs(data)
                if not kwargs["id"]:
                    import uuid
                    kwargs["id"] = str(uuid.uuid4())
                session.add(PublisherORM(**kwargs))
        logger.debug(f"PgPublisherRepository.save_all_raw: replaced with {len(records)} records.")

    # ── Typed interface ───────────────────────────────────────────────────────

    def get_all(self) -> list[Publisher]:
        return [Publisher.model_validate(r) for r in self.get_all_raw()]

    def get_by_id(self, record_id: str) -> Publisher | None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PublisherORM
        with get_session() as session:
            row = session.get(PublisherORM, record_id)
            return Publisher.model_validate(_orm_to_dict(row)) if row else None

    def get_by_publisher_id(self, publisher_id: str) -> Publisher | None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PublisherORM
        with get_session() as session:
            row = (
                session.query(PublisherORM)
                .filter(PublisherORM.publisher_id == str(publisher_id).strip())
                .first()
            )
            return Publisher.model_validate(_orm_to_dict(row)) if row else None

    def create(self, data: dict) -> dict:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PublisherORM
        import uuid
        kwargs = _dict_to_orm_kwargs(data)
        if not kwargs["id"]:
            kwargs["id"] = str(uuid.uuid4())
        with get_session() as session:
            row = PublisherORM(**kwargs)
            session.add(row)
            session.flush()
            result = _orm_to_dict(row)
        return result

    def update(self, record_id: str, data: dict) -> dict | None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PublisherORM
        with get_session() as session:
            row = session.get(PublisherORM, record_id)
            if row is None:
                return None
            for k, v in _dict_to_orm_kwargs(data).items():
                if k != "id":
                    setattr(row, k, v)
            session.flush()
            result = _orm_to_dict(row)
        return result

    def delete(self, record_id: str) -> bool:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PublisherORM
        with get_session() as session:
            row = session.get(PublisherORM, record_id)
            if row is None:
                return False
            session.delete(row)
        return True

    def get_enabled_partner_ids(self) -> tuple[list[int], dict[str, str]]:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PublisherORM
        partner_ids: list[int] = []
        partner_names: dict[str, str] = {}
        with get_session() as session:
            # Project only the two columns needed — returns plain Row namedtuples,
            # not ORM instances, so they remain usable after the session closes.
            # All processing is done inside the block as an extra safeguard.
            rows = (
                session.query(PublisherORM.publisher_id, PublisherORM.partner_name)
                .filter(PublisherORM.enabled.is_(True))
                .order_by(PublisherORM.publisher_id)
                .all()
            )
            for row in rows:
                pid_str = str(row.publisher_id).strip()
                try:
                    partner_ids.append(int(pid_str))
                    partner_names[pid_str] = str(row.partner_name or "Unknown").strip()
                except ValueError:
                    logger.warning(
                        f"PgPublisherRepository: non-numeric publisher_id {pid_str!r} skipped."
                    )
        return partner_ids, partner_names
