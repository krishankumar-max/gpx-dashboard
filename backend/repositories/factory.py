"""
RepositoryFactory — creates configured repository instances.

Usage (in app.py)
-----------------
    from backend.repositories.factory import RepositoryFactory
    from backend import config
    from backend.config import DATA_DIR

    game_config_repo = RepositoryFactory.create_game_config_repo(config.REPO_BACKEND)
    publisher_repo   = RepositoryFactory.create_publisher_repo(config.REPO_BACKEND)
    partner_repo     = RepositoryFactory.create_partner_repo(config.REPO_BACKEND)

Switching from JSON to PostgreSQL is a one-line env var change:
    REPO_BACKEND=pg
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from backend.repositories.base import (
    GameConfigRepository,
    PartnerRepository,
    PublisherRepository,
)


class RepositoryFactory:
    """Creates repository instances based on the REPO_BACKEND config value."""

    @staticmethod
    def create_game_config_repo(
        backend: str = "json",
        config_dir: Path | None = None,
    ) -> GameConfigRepository:
        """
        Parameters
        ----------
        backend    : "json" | "pg"
        config_dir : Directory containing config JSON files.
                     Defaults to <project_root>/data/config/.
        """
        backend = backend.lower().strip()

        if backend == "json":
            from backend.config import DATA_DIR
            from backend.repositories.json.game_config import JsonGameConfigRepository
            path = (config_dir or DATA_DIR / "config") / "game_configs.json"
            logger.debug(f"RepositoryFactory → JsonGameConfigRepository ({path})")
            return JsonGameConfigRepository(file_path=path)

        if backend == "pg":
            from backend.repositories.pg.game_config import PgGameConfigRepository
            logger.info("RepositoryFactory → PgGameConfigRepository (PostgreSQL)")
            return PgGameConfigRepository()

        raise ValueError(
            f"Unknown REPO_BACKEND={backend!r}. Valid values: 'json', 'pg'."
        )

    @staticmethod
    def create_publisher_repo(
        backend: str = "json",
        config_dir: Path | None = None,
    ) -> PublisherRepository:
        backend = backend.lower().strip()

        if backend == "json":
            from backend.config import DATA_DIR
            from backend.repositories.json.publisher import JsonPublisherRepository
            path = (config_dir or DATA_DIR / "config") / "publishers.json"
            logger.debug(f"RepositoryFactory → JsonPublisherRepository ({path})")
            return JsonPublisherRepository(file_path=path)

        if backend == "pg":
            from backend.repositories.pg.publisher import PgPublisherRepository
            logger.info("RepositoryFactory → PgPublisherRepository (PostgreSQL)")
            return PgPublisherRepository()

        raise ValueError(
            f"Unknown REPO_BACKEND={backend!r}. Valid values: 'json', 'pg'."
        )

    @staticmethod
    def create_partner_repo(
        backend: str = "json",
        config_dir: Path | None = None,
    ) -> PartnerRepository:
        backend = backend.lower().strip()

        if backend == "json":
            from backend.config import DATA_DIR
            from backend.repositories.json.partner import JsonPartnerRepository
            # Partners stored in partners.json (replaces clients.json for portal users)
            path = (config_dir or DATA_DIR / "config") / "partners.json"
            logger.debug(f"RepositoryFactory → JsonPartnerRepository ({path})")
            return JsonPartnerRepository(file_path=path)

        if backend == "pg":
            from backend.repositories.pg.partner import PgPartnerRepository
            logger.info("RepositoryFactory → PgPartnerRepository (PostgreSQL)")
            return PgPartnerRepository()

        raise ValueError(
            f"Unknown REPO_BACKEND={backend!r}. Valid values: 'json', 'pg'."
        )
