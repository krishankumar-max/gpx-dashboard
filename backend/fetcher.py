"""
Sapphyre Postbacks API fetcher.

Architecture
------------
- requests.Session with HTTPAdapter (pool sized to SYNC_WORKERS, max 8)
- ThreadPoolExecutor(max_workers=SYNC_WORKERS) — one thread per page
- GET with query params (not POST with JSON body)
- Response key: data["payload"]  (not "data")
- Bounded retry (HTTP_MAX_RETRIES) on 429 / 5xx / timeout / network errors
- Streaming: completed pages are flushed to an on_rows_ready() callback in
  DB_BATCH_SIZE chunks — no full-day accumulation in RAM
- Validation: raises RuntimeError only if pages permanently fail

Usage
-----
    from backend.fetcher import fetch_day_sync
    import datetime as dt

    rows = fetch_day_sync(dt.date(2026, 6, 3))
    print(len(rows))
"""

import datetime as dt
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from loguru import logger

from backend.config import (
    SAPPHYRE_API_KEY,
    SAPPHYRE_BASE_URL,
    SAPPHYRE_TIMEZONE,
    SYNC_WORKERS,
    SYNC_PAGE_SIZE,
    HTTP_TIMEOUT_SECONDS,
    HTTP_MAX_RETRIES,
    API_MAX_PAGE_SIZE,
    DB_BATCH_SIZE,
    KEEP_COLS,
)

# Type alias for the progress callback: (pages_done, pages_total, rows_so_far) -> None
_ProgressCB = Callable[[int, int, int], None]

# ── Backoff settings ──────────────────────────────────────────────────────────
_BACKOFF_BASE: float = 2.0      # seconds for first retry
_BACKOFF_STEP: float = 2.0      # added on each subsequent retry
_BACKOFF_MAX: float = 30.0      # ceiling
_MAX_RETRIES: int = HTTP_MAX_RETRIES

# Clamp SYNC_PAGE_SIZE to the API's hard cap. Both the limit= param and the skip
# increment must use the same value, otherwise pages are silently skipped.
if SYNC_PAGE_SIZE > API_MAX_PAGE_SIZE:
    logger.warning(
        f"SYNC_PAGE_SIZE={SYNC_PAGE_SIZE} exceeds API_MAX_PAGE_SIZE={API_MAX_PAGE_SIZE}. "
        f"Clamping to {API_MAX_PAGE_SIZE}. Update SYNC_PAGE_SIZE in your .env to suppress this."
    )
_EFFECTIVE_PAGE_SIZE: int = min(SYNC_PAGE_SIZE, API_MAX_PAGE_SIZE)


class PageFetchFailed(Exception):
    """
    Raised by _fetch_page when a single page exhausts all retry attempts.

    Attributes
    ----------
    date        : Calendar date being fetched.
    skip        : Row offset (page start) of the failed page.
    attempts    : Number of attempts made.
    last_exc    : Last network exception, or None if failure was HTTP-status-based.
    last_status : Last HTTP status code seen, or None if last failure was a network error.
    """
    def __init__(
        self,
        date: dt.date,
        skip: int,
        attempts: int,
        last_exc: Exception | None = None,
        last_status: int | None = None,
    ) -> None:
        self.date        = date
        self.skip        = skip
        self.attempts    = attempts
        self.last_exc    = last_exc
        self.last_status = last_status
        detail = f"status={last_status}" if last_status else f"exc={last_exc}"
        super().__init__(
            f"[{date}] skip={skip}: gave up after {attempts} attempts ({detail})"
        )


def _make_session() -> requests.Session:
    """Create a requests.Session sized to match SYNC_WORKERS (capped at 8)."""
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=SYNC_WORKERS,
        pool_maxsize=SYNC_WORKERS,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "apiKey": SAPPHYRE_API_KEY,
        "Accept": "application/json",
    })
    return session


def _build_params(
    date: dt.date,
    skip: int,
    limit: int,
    partner_ids: list[int] | None = None,
) -> dict[str, Any]:
    """
    Build GET query parameters for one page.

    If *partner_ids* is supplied, the `partner` key is added as a list so that
    requests sends: ``partner=1081&partner=2050&partner=3001``.
    The Sapphyre API interprets repeated `partner` params as an OR filter,
    returning only postbacks whose `partner` field matches one of those IDs.
    """
    tz_suffix = "+05:30"
    params: dict[str, Any] = {
        "fromDate": f"{date.isoformat()}T00:00:00{tz_suffix}",
        "toDate":   f"{(date + dt.timedelta(days=1)).isoformat()}T00:00:00{tz_suffix}",
        "timezone": SAPPHYRE_TIMEZONE,
        "skip":     skip,
        "limit":    limit,
    }
    if partner_ids:
        params["partner"] = partner_ids   # requests serialises as repeated params
    return params


def _filter_row(row: dict[str, Any]) -> dict[str, Any]:
    """Keep only KEEP_COLS from a raw API row."""
    return {k: row.get(k) for k in KEEP_COLS}


# ── Single-page fetch with bounded retry ─────────────────────────────────────

def _fetch_page(
    session: requests.Session,
    date: dt.date,
    skip: int,
    partner_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch one page (skip offset) for *date*.

    Retries up to _MAX_RETRIES times on:
      - HTTP 429 (rate limited)
      - HTTP 5xx (server errors)
      - requests.Timeout
      - requests.ConnectionError

    Raises immediately on any other HTTP error (4xx except 429).
    Raises PageFetchFailed after _MAX_RETRIES exhausted.

    Returns the filtered rows for this page.
    """
    params = _build_params(date, skip=skip, limit=_EFFECTIVE_PAGE_SIZE, partner_ids=partner_ids)
    wait = _BACKOFF_BASE
    last_exc: Exception | None = None
    last_status: int | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = session.get(
                SAPPHYRE_BASE_URL,
                params=params,
                timeout=HTTP_TIMEOUT_SECONDS,
            )

            # ── Rate limit: back off and retry ───────────────────────────────
            if resp.status_code == 429:
                last_status = 429
                retry_after = float(resp.headers.get("Retry-After", wait))
                sleep_for = max(retry_after, wait)
                logger.warning(
                    f"[{date}] skip={skip} → 429 rate-limit "
                    f"(attempt {attempt}/{_MAX_RETRIES}). Sleeping {sleep_for:.1f}s…"
                )
                time.sleep(sleep_for)
                wait = min(wait + _BACKOFF_STEP, _BACKOFF_MAX)
                continue

            # ── Server errors: back off and retry ────────────────────────────
            if resp.status_code >= 500:
                last_status = resp.status_code
                logger.warning(
                    f"[{date}] skip={skip} → HTTP {resp.status_code} "
                    f"(attempt {attempt}/{_MAX_RETRIES}). Sleeping {wait:.1f}s…"
                )
                time.sleep(wait)
                wait = min(wait + _BACKOFF_STEP, _BACKOFF_MAX)
                continue

            # ── Client errors (4xx except 429): fatal ─────────────────────────
            if resp.status_code >= 400:
                resp.raise_for_status()

            # ── Success ───────────────────────────────────────────────────────
            data = resp.json()
            rows: list[dict] = data.get("payload", [])

            if not isinstance(rows, list):
                # Unexpected response shape — treat as transient and retry
                last_status = resp.status_code
                logger.warning(
                    f"[{date}] skip={skip} → unexpected payload type "
                    f"{type(rows).__name__} (attempt {attempt}/{_MAX_RETRIES}). Retrying…"
                )
                time.sleep(wait)
                wait = min(wait + _BACKOFF_STEP, _BACKOFF_MAX)
                continue

            return [_filter_row(r) for r in rows]

        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            logger.warning(
                f"[{date}] skip={skip} → network error (attempt {attempt}/{_MAX_RETRIES}): "
                f"{exc}. Sleeping {wait:.1f}s…"
            )
            time.sleep(wait)
            wait = min(wait + _BACKOFF_STEP, _BACKOFF_MAX)

    raise PageFetchFailed(
        date=date,
        skip=skip,
        attempts=_MAX_RETRIES,
        last_exc=last_exc,
        last_status=last_status,
    )


# ── Probe total row count ─────────────────────────────────────────────────────

def _probe_total(
    session: requests.Session,
    date: dt.date,
    partner_ids: list[int] | None = None,
) -> int:
    """
    Fire a limit=1 request to read the server-reported total for *date*.
    Retries indefinitely on 429 / network errors.

    If *partner_ids* is supplied the total reflects only those publishers,
    so the subsequent row-count validation stays accurate.
    """
    params = _build_params(date, skip=0, limit=1, partner_ids=partner_ids)
    wait = _BACKOFF_BASE

    while True:
        try:
            resp = session.get(
                SAPPHYRE_BASE_URL,
                params=params,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code == 429:
                sleep_for = float(resp.headers.get("Retry-After", wait))
                logger.warning(f"[{date}] probe 429. Sleeping {sleep_for:.1f}s…")
                time.sleep(sleep_for)
                wait = min(wait + _BACKOFF_STEP, _BACKOFF_MAX)
                continue
            if resp.status_code >= 500:
                logger.warning(
                    f"[{date}] probe HTTP {resp.status_code}. "
                    f"Sleeping {wait:.1f}s…"
                )
                time.sleep(wait)
                wait = min(wait + _BACKOFF_STEP, _BACKOFF_MAX)
                continue
            resp.raise_for_status()
            total: int = resp.json().get("total", 0)
            logger.info(f"[{date}] Server total: {total:,} rows")
            return total
        except (requests.Timeout, requests.ConnectionError) as exc:
            logger.warning(f"[{date}] probe network error: {exc}. Sleeping {wait:.1f}s…")
            time.sleep(wait)
            wait = min(wait + _BACKOFF_STEP, _BACKOFF_MAX)


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_day_sync(
    date: dt.date,
    partner_ids: list[int] | None = None,
    on_page_done: _ProgressCB | None = None,
    on_rows_ready: Callable[[list[dict[str, Any]]], None] | None = None,
    is_live: bool = False,
) -> list[dict[str, Any]]:
    """
    Fetch ALL postback rows for *date* synchronously.

    Parameters
    ----------
    date          : Calendar date to fetch (IST-aligned day window).
    partner_ids   : Integer publisher IDs sent as repeated query params.
                    None = fetch all.
    on_page_done  : Optional progress callback — (pages_done, pages_total,
                    rows_so_far) -> None.  Called every 20 pages and at end.
    on_rows_ready : Optional streaming callback — (batch: list[dict]) -> None.
                    When provided, completed pages are flushed to this callback
                    in DB_BATCH_SIZE chunks instead of being accumulated in RAM.
                    The function returns [] in this mode; all rows are delivered
                    through the callback.  Validation is skipped for live dates;
                    historical dates raise only on permanent page failures.
    is_live       : When True, row-count validation is bypassed (live data grows
                    during the fetch window).

    Returns
    -------
    list[dict] — all rows (KEEP_COLS only) when on_rows_ready is None.
    []         — when on_rows_ready is provided (rows delivered via callback).
    """
    session  = _make_session()
    pid_list = partner_ids if partner_ids else None

    # ── Step 1: probe total rows for this date ────────────────────────────────
    total = _probe_total(session, date, partner_ids=pid_list)

    if total == 0:
        logger.info(f"[{date}] No data — skipping.")
        if on_page_done:
            on_page_done(0, 0, 0)
        return []

    # ── Step 2: compute page offsets ──────────────────────────────────────────
    offsets = list(range(0, total, _EFFECTIVE_PAGE_SIZE))
    pub_note = f"publishers={partner_ids}" if pid_list else "all publishers"
    logger.info(
        f"[{date}] {total:,} rows / {len(offsets)} pages "
        f"/ {SYNC_WORKERS} workers  [{pub_note}]"
    )

    # ── Step 3: fan-out — one future per page ─────────────────────────────────
    # Streaming mode: pages are flushed to on_rows_ready in DB_BATCH_SIZE chunks.
    # Classic mode:   pages accumulate in `results` dict, returned as a flat list.
    failed: dict[int, PageFetchFailed] = {}

    if on_rows_ready is not None:
        # ── STREAMING PATH ────────────────────────────────────────────────────
        _pending: list[dict[str, Any]] = []   # bounded buffer, flushed every DB_BATCH_SIZE rows
        rows_delivered = 0
        completed = 0

        with ThreadPoolExecutor(max_workers=SYNC_WORKERS) as executor:
            future_to_offset = {
                executor.submit(_fetch_page, session, date, offset, pid_list): offset
                for offset in offsets
            }
            for future in as_completed(future_to_offset):
                offset = future_to_offset[future]
                try:
                    page_rows = future.result()
                    _pending.extend(page_rows)
                    # Flush complete batches immediately
                    while len(_pending) >= DB_BATCH_SIZE:
                        on_rows_ready(_pending[:DB_BATCH_SIZE])
                        rows_delivered += DB_BATCH_SIZE
                        _pending = _pending[DB_BATCH_SIZE:]
                except PageFetchFailed as exc:
                    logger.error(
                        f"[{date}] skip={offset} → gave up after {exc.attempts} attempts "
                        f"(status={exc.last_status}, exc={exc.last_exc}). Will retry sequentially."
                    )
                    failed[offset] = exc
                completed += 1
                if on_page_done and (completed % 20 == 0 or completed == len(offsets)):
                    on_page_done(completed, len(offsets), rows_delivered + len(_pending))
                if completed % 20 == 0 or completed == len(offsets):
                    logger.info(
                        f"[{date}] {completed}/{len(offsets)} pages"
                        f"  ({rows_delivered + len(_pending):,} rows buffered)"
                    )

        # Flush the tail (remainder < DB_BATCH_SIZE)
        if _pending:
            on_rows_ready(_pending)
            rows_delivered += len(_pending)
            _pending = []

    else:
        # ── CLASSIC PATH (backward-compatible) ────────────────────────────────
        results: dict[int, list[dict[str, Any]]] = {}
        completed = 0

        with ThreadPoolExecutor(max_workers=SYNC_WORKERS) as executor:
            future_to_offset = {
                executor.submit(_fetch_page, session, date, offset, pid_list): offset
                for offset in offsets
            }
            for future in as_completed(future_to_offset):
                offset = future_to_offset[future]
                try:
                    results[offset] = future.result()
                except PageFetchFailed as exc:
                    logger.error(
                        f"[{date}] skip={offset} → gave up after {exc.attempts} attempts "
                        f"(status={exc.last_status}, exc={exc.last_exc}). Will retry sequentially."
                    )
                    failed[offset] = exc
                completed += 1
                rows_so_far = sum(len(v) for v in results.values())
                if on_page_done and (completed % 20 == 0 or completed == len(offsets)):
                    on_page_done(completed, len(offsets), rows_so_far)
                if completed % 20 == 0 or completed == len(offsets):
                    logger.info(
                        f"[{date}] {completed}/{len(offsets)} pages  "
                        f"({rows_so_far:,} rows so far)"
                    )

    # ── Step 3b: sequential retry for permanently failed pages ────────────────
    if failed:
        logger.warning(
            f"[{date}] {len(failed)} page(s) failed in parallel — retrying sequentially: "
            f"offsets={sorted(failed)}"
        )
        still_failed: list[int] = []
        for offset in sorted(failed):
            try:
                recovered = _fetch_page(session, date, offset, pid_list)
                logger.info(f"[{date}] skip={offset} → sequential retry succeeded.")
                if on_rows_ready is not None:
                    on_rows_ready(recovered)
                else:
                    results[offset] = recovered  # type: ignore[possibly-undefined]
            except PageFetchFailed as exc:
                logger.error(
                    f"[{date}] skip={offset} → sequential retry also failed "
                    f"after {exc.attempts} attempts."
                )
                still_failed.append(offset)
        if still_failed:
            raise RuntimeError(
                f"[{date}] Sync failed: {len(still_failed)} page(s) could not be fetched "
                f"after parallel + sequential retries. "
                f"Failed offsets: {still_failed}"
            )

    # ── Step 4 (streaming mode): validation and return ────────────────────────
    if on_rows_ready is not None:
        if not is_live:
            # Streaming validation: succeed if all pages were delivered.
            # Row-count check is omitted because rows were already flushed.
            logger.success(f"[{date}] ✓ Streaming fetch complete — no permanent failures.")
        return []

    # ── Step 4 (classic mode): flatten + validate ─────────────────────────────
    all_rows: list[dict[str, Any]] = []
    for offset in offsets:
        if offset in results:  # type: ignore[possibly-undefined]
            all_rows.extend(results[offset])

    fetched = len(all_rows)
    if fetched != total:
        if is_live:
            logger.warning(
                f"[{date}] Live data window detected. Validation bypassed. "
                f"(probed {total:,}, fetched {fetched:,} rows)"
            )
        else:
            raise RuntimeError(
                f"[{date}] Row-count mismatch: "
                f"expected {total:,}, fetched {fetched:,}. "
                "Sync aborted — do not save partial data."
            )
    else:
        logger.success(f"[{date}] ✓ {fetched:,} rows validated.")
    return all_rows
