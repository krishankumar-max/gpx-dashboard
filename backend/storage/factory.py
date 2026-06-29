"""
StorageFactory — creates the configured StorageProvider.

Usage (in app.py or any entry point)
--------------------------------------
    from backend.storage.factory import StorageFactory
    from backend import config

    storage = StorageFactory.create(config.STORAGE_BACKEND)

The returned provider is then passed to aggregator functions and
registered as the module-level provider in backend/storage/__init__.py.
"""

from __future__ import annotations

from loguru import logger

from backend.storage.base import StorageProvider


class StorageFactory:
    """Creates a StorageProvider based on the STORAGE_BACKEND config value."""

    @staticmethod
    def create(backend: str = "local", **kwargs: object) -> StorageProvider:
        """
        Instantiate and return a StorageProvider.

        Parameters
        ----------
        backend : "local" | "s3"
            Which implementation to use.  Defaults to "local".
        **kwargs :
            Reserved for future use (e.g. overriding raw_dir for tests).

        Raises
        ------
        ValueError
            If *backend* is not a known implementation.
        """
        backend = backend.lower().strip()

        if backend == "local":
            from backend.config import RAW_DIR, AGG_DIR
            from backend.storage.local import LocalStorage
            provider = LocalStorage(raw_dir=RAW_DIR, agg_dir=AGG_DIR)
            logger.debug("StorageFactory → LocalStorage (filesystem)")
            return provider

        if backend == "s3":
            from backend.config import S3_BUCKET, AWS_REGION, S3_RAW_PREFIX, S3_AGG_PREFIX
            from backend.storage.s3 import S3Storage
            provider = S3Storage(
                bucket=S3_BUCKET,
                region=AWS_REGION,
                raw_prefix=S3_RAW_PREFIX,
                agg_prefix=S3_AGG_PREFIX,
            )
            logger.info(
                f"StorageFactory → S3Storage (bucket={S3_BUCKET!r}, "
                f"region={AWS_REGION!r})"
            )
            return provider

        raise ValueError(
            f"Unknown STORAGE_BACKEND={backend!r}. "
            "Valid values: 'local', 's3'."
        )
