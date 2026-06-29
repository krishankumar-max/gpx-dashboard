"""
PostgreSQL database session management (SQLAlchemy 2.0).

Usage
-----
    from backend.repositories.pg.db import get_session, init_db

    # At application startup:
    init_db()

    # Inside a repository method:
    with get_session() as session:
        session.add(orm_object)
        session.commit()

STATUS: ready for Phase 6.  Not wired until DATABASE_URL is set.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.repositories.pg.schema import Base

_engine = None
_SessionLocal = None


def init_db(database_url: str | None = None) -> None:
    """
    Initialise the SQLAlchemy engine and create all tables.

    Parameters
    ----------
    database_url :
        PostgreSQL DSN.  If None, reads from backend.config.DATABASE_URL.
    """
    global _engine, _SessionLocal

    if not database_url:
        from backend.config import DATABASE_URL
        database_url = DATABASE_URL

    if not database_url:
        raise ValueError(
            "DATABASE_URL is required to initialise PostgreSQL. "
            "Set the DATABASE_URL environment variable or pass it explicitly."
        )

    _engine = create_engine(
        database_url,
        pool_pre_ping=True,       # detect stale connections before use
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,        # recycle connections after 1 hour (EC2 idle periods)
        echo=False,               # set True for SQL query logging
    )
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

    # Create all tables defined in schema.py (safe — won't drop existing tables)
    Base.metadata.create_all(_engine)
    logger.info("PostgreSQL connected and schema applied.")


def get_engine():
    """Return the active SQLAlchemy engine (raises if not initialised)."""
    if _engine is None:
        raise RuntimeError(
            "Database not initialised. Call init_db() at application startup."
        )
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Yield a SQLAlchemy Session as a context manager.

    Commits on clean exit, rolls back on exception.

    Example::

        with get_session() as session:
            result = session.execute(text("SELECT 1"))
    """
    if _SessionLocal is None:
        raise RuntimeError(
            "Database not initialised. Call init_db() at application startup."
        )
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def health_check() -> bool:
    """Return True if the database is reachable."""
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error(f"Database health check failed: {exc}")
        return False
