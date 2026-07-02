"""
Abstract repository interfaces.

Each repository declares what operations are available.
Implementations (JSON, PostgreSQL) live in the json/ and pg/ sub-packages.

Design rules
------------
- Repositories own persistence only.  No business logic.
- Callers receive plain dicts for backward compat with existing route logic,
  and typed Pydantic objects for new code.  Both interfaces co-exist via the
  get_all_raw / save_all_raw pair (compat) and get_all / get_by_id (typed).
- Cache invalidation is the caller's responsibility — repos never touch cache.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.models.game_config import GameConfig
from backend.models.partner     import Partner
from backend.models.publisher   import Publisher


class GameConfigRepository(ABC):
    """Persistence interface for game configuration records."""

    # ── Typed interface (new code) ────────────────────────────────────────────

    @abstractmethod
    def get_all(self) -> list[GameConfig]:
        """Return all game configs as typed Pydantic objects."""

    @abstractmethod
    def get_by_id(self, record_id: str) -> GameConfig | None:
        """Return a single config by its UUID id, or None."""

    @abstractmethod
    def get_by_offer_id(self, offer_id: str) -> GameConfig | None:
        """Return the config whose offer_id matches, or None."""

    @abstractmethod
    def create(self, data: dict) -> dict:
        """Persist a new record and return the saved dict (with generated id)."""

    @abstractmethod
    def update(self, record_id: str, data: dict) -> dict | None:
        """Update an existing record by id.  Returns updated dict or None."""

    @abstractmethod
    def delete(self, record_id: str) -> bool:
        """Delete by id.  Returns True if found and deleted."""

    # ── Raw dict interface (backward compat with existing route logic) ────────

    @abstractmethod
    def get_all_raw(self) -> list[dict]:
        """
        Return all game configs as plain dicts.

        Drop-in replacement for: _cfg_read(_GAME_CONFIGS_FILE)
        """

    @abstractmethod
    def save_all_raw(self, records: list[dict]) -> None:
        """
        Persist a complete list of raw dicts (full replacement).

        Drop-in replacement for: _cfg_write(_GAME_CONFIGS_FILE, records)
        """


class PublisherRepository(ABC):
    """Persistence interface for publisher configuration records."""

    @abstractmethod
    def get_all(self) -> list[Publisher]: ...

    @abstractmethod
    def get_by_id(self, record_id: str) -> Publisher | None: ...

    @abstractmethod
    def get_by_publisher_id(self, publisher_id: str) -> Publisher | None: ...

    @abstractmethod
    def create(self, data: dict) -> dict: ...

    @abstractmethod
    def update(self, record_id: str, data: dict) -> dict | None: ...

    @abstractmethod
    def delete(self, record_id: str) -> bool: ...

    @abstractmethod
    def get_all_raw(self) -> list[dict]:
        """Drop-in replacement for: _cfg_read(_PUBLISHERS_FILE)"""

    @abstractmethod
    def save_all_raw(self, records: list[dict]) -> None:
        """Drop-in replacement for: _cfg_write(_PUBLISHERS_FILE, records)"""

    @abstractmethod
    def get_enabled_partner_ids(self) -> tuple[list[int], dict[str, str]]:
        """
        Return (partner_ids, partner_names) for all enabled publishers.

        partner_ids   : integer Sapphyre partner IDs (publisher_id cast to int,
                        non-numeric entries skipped with a warning).
        partner_names : {str(publisher_id): partner_name} label map for logging.

        Returns ([], {}) when no enabled publishers are configured.
        This is the single call the sync pipeline makes to resolve which
        partners to fetch — it must never be bypassed or cached across runs.
        """


class StructureRepository(ABC):
    """Persistence interface for publisher structure version records.

    Structures are append-only — the delete() operation is intentionally
    absent.  All history must be preserved; only status and timestamps
    may change after creation.
    """

    @abstractmethod
    def get_all_raw(self) -> list[dict]:
        """Return all structure records as plain dicts."""

    @abstractmethod
    def save_all_raw(self, records: list[dict]) -> None:
        """Persist a complete list of raw dicts (full replacement)."""

    @abstractmethod
    def get_by_id(self, sid: str) -> dict | None:
        """Return a single structure by UUID, or None."""

    @abstractmethod
    def get_by_publisher_offer(self, publisher_id: str, offer_id: str) -> list[dict]:
        """Return all structures for a (publisher_id, offer_id) pair, sorted by version asc."""

    @abstractmethod
    def get_live(self, publisher_id: str, offer_id: str) -> dict | None:
        """Return the single live structure for this publisher+offer, or None."""

    @abstractmethod
    def next_version(self, publisher_id: str, offer_id: str) -> int:
        """Return the next version number: max(existing versions) + 1, minimum 1."""

    @abstractmethod
    def create(self, data: dict) -> dict:
        """Persist a new record and return the saved dict."""

    @abstractmethod
    def update(self, sid: str, data: dict) -> dict | None:
        """Update status / timestamps on an existing record.  Returns updated dict or None."""


class OverrideRepository(ABC):
    """
    Persistence interface for manual revenue / cost overrides.

    Key constraint: at most one override per (date, publisher_id, offer_id).
    upsert() must create or update — never duplicate.
    """

    @abstractmethod
    def get_all(self) -> list[dict]:
        """Return all overrides as plain dicts, ordered by date desc."""

    @abstractmethod
    def get_by_id(self, override_id: str) -> dict | None:
        """Return a single override by UUID, or None."""

    @abstractmethod
    def get_by_key(self, date: str, publisher_id: str, offer_id: str) -> dict | None:
        """Return the override for a specific (date, publisher_id, offer_id), or None."""

    @abstractmethod
    def upsert(self, data: dict) -> dict:
        """
        Create or update the override for (date, publisher_id, offer_id).

        If a record with the same (date, publisher_id, offer_id) already exists,
        update it and return the updated record.  Otherwise create a new record.
        """

    @abstractmethod
    def delete(self, override_id: str) -> bool:
        """Delete by id.  Returns True if found and deleted."""


class PartnerRepository(ABC):
    """Persistence interface for partner (portal user) records."""

    @abstractmethod
    def get_all(self) -> list[Partner]: ...

    @abstractmethod
    def get_by_id(self, record_id: str) -> Partner | None: ...

    @abstractmethod
    def get_by_email(self, email: str) -> Partner | None: ...

    @abstractmethod
    def create(self, data: dict) -> dict: ...

    @abstractmethod
    def update(self, record_id: str, data: dict) -> dict | None: ...

    @abstractmethod
    def delete(self, record_id: str) -> bool: ...

    @abstractmethod
    def get_all_raw(self) -> list[dict]:
        """Drop-in replacement for: _cfg_read(_CLIENTS_FILE)"""

    @abstractmethod
    def save_all_raw(self, records: list[dict]) -> None:
        """Drop-in replacement for: _cfg_write(_CLIENTS_FILE, records)"""
