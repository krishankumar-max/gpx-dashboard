"""
backend.services — Service layer factory and public exports.

Usage in app.py:
    from backend.services import build_services

    (
        game_config_svc,
        publisher_svc,
        partner_svc,
        funnel_svc,
        analytics_svc,
        sync_svc,
    ) = build_services(cache, game_config_repo, publisher_repo, partner_repo, storage)
"""
from __future__ import annotations

from backend.repositories.cache import CacheProvider
from backend.services.analytics   import AnalyticsService
from backend.services.funnel       import FunnelService
from backend.services.game_config  import GameConfigService
from backend.services.partner      import PartnerService
from backend.services.publisher    import PublisherService
from backend.services.sync         import SyncService


def build_services(
    cache,
    game_config_repo,
    publisher_repo,
    partner_repo,
    storage=None,
    sync_day_workers: int = 2,
    sync_shared_state=None,
    sync_shared_lock=None,
) -> tuple:
    """
    Construct and wire all services from their dependencies.

    Returns
    -------
    (game_config_svc, publisher_svc, partner_svc, funnel_svc, analytics_svc, sync_svc)
    """
    game_config_svc = GameConfigService(repo=game_config_repo, cache=cache, storage=storage)
    publisher_svc   = PublisherService(repo=publisher_repo)
    partner_svc     = PartnerService(repo=partner_repo)

    funnel_svc      = FunnelService(cache=cache, storage=storage)

    analytics_svc   = AnalyticsService(
        cache=cache,
        game_config_svc=game_config_svc,
        publisher_svc=publisher_svc,
        funnel_svc=funnel_svc,
    )

    sync_svc        = SyncService(
        publisher_repo=publisher_repo,
        cache=cache,
        sync_day_workers=sync_day_workers,
        shared_state=sync_shared_state,
        shared_lock=sync_shared_lock,
    )

    return (
        game_config_svc,
        publisher_svc,
        partner_svc,
        funnel_svc,
        analytics_svc,
        sync_svc,
    )


__all__ = [
    "build_services",
    "AnalyticsService",
    "FunnelService",
    "GameConfigService",
    "PartnerService",
    "PublisherService",
    "SyncService",
]
