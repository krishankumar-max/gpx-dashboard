"""
CacheProvider — abstract interface + DictCache implementation.

Current: DictCache — in-process Python dict with per-key TTL.
Future:  RedisCache — swapped in by setting CACHE_BACKEND=redis.

The interface is intentionally minimal so a Redis implementation can
be added in Phase 8 without touching any call sites in app.py.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any


class CacheProvider(ABC):
    """Abstract cache interface."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """
        Return the cached value for *key*, or None if missing / expired.
        Expired entries are treated identically to missing ones.
        """

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """
        Store *value* under *key* with an optional TTL in seconds.
        A None TTL means the entry never expires.
        """

    @abstractmethod
    def evict(self, *keys: str) -> None:
        """Remove one or more keys from the cache (silent if absent)."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all entries from the cache."""

    @abstractmethod
    def has(self, key: str) -> bool:
        """Return True if *key* exists and has not expired."""


class DictCache(CacheProvider):
    """
    In-process dict cache with per-key TTL.

    Thread-safety note: individual dict operations in CPython are
    effectively atomic due to the GIL.  For multi-threaded Flask workers
    this is sufficient.  Switch to RedisCache for multi-process deployments.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any]           = {}
        self._timestamps: dict[str, float]    = {}
        self._ttls: dict[str, int | None]     = {}

    def _is_expired(self, key: str) -> bool:
        ttl = self._ttls.get(key)
        if ttl is None:
            return False  # no TTL → never expires
        return time.monotonic() - self._timestamps.get(key, 0.0) > ttl

    def get(self, key: str) -> Any | None:
        if key not in self._store:
            return None
        if self._is_expired(key):
            self.evict(key)
            return None
        return self._store[key]

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._store[key]      = value
        self._timestamps[key] = time.monotonic()
        self._ttls[key]       = ttl

    def evict(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)
            self._timestamps.pop(key, None)
            self._ttls.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
        self._timestamps.clear()
        self._ttls.clear()

    def has(self, key: str) -> bool:
        return key in self._store and not self._is_expired(key)

    def __repr__(self) -> str:
        live = [k for k in self._store if not self._is_expired(k)]
        return f"DictCache(live_keys={live})"


class RedisCache(CacheProvider):
    """
    Redis-backed cache.

    STATUS: skeleton — raises NotImplementedError.
    Activate by setting CACHE_BACKEND=redis and REDIS_URL.

    Requires: redis-py  (pip install redis)
    """

    def __init__(self, url: str) -> None:
        if not url:
            raise ValueError(
                "RedisCache requires a REDIS_URL environment variable."
            )
        self._url = url
        # Lazy import — redis-py is not in base requirements
        try:
            import redis  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "redis-py is required for RedisCache. "
                "Install it: pip install redis"
            ) from exc

    def get(self, key: str) -> Any | None:
        raise NotImplementedError("RedisCache — Phase 8 not yet implemented.")

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        raise NotImplementedError("RedisCache — Phase 8 not yet implemented.")

    def evict(self, *keys: str) -> None:
        raise NotImplementedError("RedisCache — Phase 8 not yet implemented.")

    def clear(self) -> None:
        raise NotImplementedError("RedisCache — Phase 8 not yet implemented.")

    def has(self, key: str) -> bool:
        raise NotImplementedError("RedisCache — Phase 8 not yet implemented.")


class CacheFactory:
    """Creates the configured CacheProvider."""

    @staticmethod
    def create(backend: str = "dict") -> CacheProvider:
        """
        Parameters
        ----------
        backend : "dict" | "redis"
        """
        backend = backend.lower().strip()
        if backend == "dict":
            return DictCache()
        if backend == "redis":
            from backend.config import REDIS_URL
            return RedisCache(url=REDIS_URL)
        raise ValueError(
            f"Unknown CACHE_BACKEND={backend!r}. Valid values: 'dict', 'redis'."
        )
