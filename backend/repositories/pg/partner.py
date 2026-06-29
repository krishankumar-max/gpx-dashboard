"""
PgPartnerRepository — PartnerRepository backed by PostgreSQL.
"""

from __future__ import annotations

from loguru import logger

from backend.models.partner import Partner
from backend.repositories.base import PartnerRepository


def _orm_to_dict(row) -> dict:
    return {
        "id":            row.id,
        "partner_name":  row.partner_name,
        "company_name":  row.company_name,
        "email":         row.email,
        "password_hash": row.password_hash,
        "status":        row.status,
        "last_login":    row.last_login,
        "created_at":    row.created_at,
    }


def _dict_to_orm_kwargs(data: dict) -> dict:
    return {
        "id":            data.get("id"),
        "partner_name":  str(data.get("partner_name",  "")).strip(),
        "company_name":  str(data.get("company_name",  "")).strip(),
        "email":         str(data.get("email",         "")).strip().lower(),
        "password_hash": str(data.get("password_hash", "")),
        "status":        str(data.get("status",        "active")),
        "last_login":    data.get("last_login"),
        "created_at":    data.get("created_at"),
    }


class PgPartnerRepository(PartnerRepository):

    def __init__(self) -> None:
        from backend.repositories.pg.schema import PartnerORM  # noqa: F401
        from backend.repositories.pg.db import get_session      # noqa: F401

    # ── Raw dict interface ────────────────────────────────────────────────────

    def get_all_raw(self) -> list[dict]:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PartnerORM
        with get_session() as session:
            rows = session.query(PartnerORM).order_by(PartnerORM.partner_name).all()
            return [_orm_to_dict(r) for r in rows]

    def save_all_raw(self, records: list[dict]) -> None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PartnerORM
        with get_session() as session:
            session.query(PartnerORM).delete()
            for data in records:
                kwargs = _dict_to_orm_kwargs(data)
                if not kwargs["id"]:
                    import uuid
                    kwargs["id"] = str(uuid.uuid4())
                session.add(PartnerORM(**kwargs))
        logger.debug(f"PgPartnerRepository.save_all_raw: replaced with {len(records)} records.")

    # ── Typed interface ───────────────────────────────────────────────────────

    def get_all(self) -> list[Partner]:
        return [Partner.model_validate(r) for r in self.get_all_raw()]

    def get_by_id(self, record_id: str) -> Partner | None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PartnerORM
        with get_session() as session:
            row = session.get(PartnerORM, record_id)
            return Partner.model_validate(_orm_to_dict(row)) if row else None

    def get_by_email(self, email: str) -> Partner | None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PartnerORM
        with get_session() as session:
            row = (
                session.query(PartnerORM)
                .filter(PartnerORM.email == str(email).strip().lower())
                .first()
            )
            return Partner.model_validate(_orm_to_dict(row)) if row else None

    def create(self, data: dict) -> dict:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PartnerORM
        import uuid
        kwargs = _dict_to_orm_kwargs(data)
        if not kwargs["id"]:
            kwargs["id"] = str(uuid.uuid4())
        with get_session() as session:
            row = PartnerORM(**kwargs)
            session.add(row)
            session.flush()
            result = _orm_to_dict(row)
        return result

    def update(self, record_id: str, data: dict) -> dict | None:
        from backend.repositories.pg.db import get_session
        from backend.repositories.pg.schema import PartnerORM
        with get_session() as session:
            row = session.get(PartnerORM, record_id)
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
        from backend.repositories.pg.schema import PartnerORM
        with get_session() as session:
            row = session.get(PartnerORM, record_id)
            if row is None:
                return False
            session.delete(row)
        return True
