"""
backend.models — Pydantic domain models.

Import directly from the sub-modules for clarity:

    from backend.models.game_config import GameConfig, PayableGoal
    from backend.models.publisher  import Publisher
    from backend.models.partner    import Partner
"""

from backend.models.game_config import (
    GameConfig,
    GameConfigCreate,
    GameConfigUpdate,
    KpiThresholds,
    PayableGoal,
    TrackingLink,
    PlayStore,
    CampaignAsset,
)
from backend.models.publisher import Publisher, PublisherCreate, PublisherUpdate
from backend.models.partner   import Partner, PartnerCreate, PartnerUpdate

__all__ = [
    "GameConfig", "GameConfigCreate", "GameConfigUpdate",
    "KpiThresholds", "PayableGoal", "TrackingLink", "PlayStore", "CampaignAsset",
    "Publisher", "PublisherCreate", "PublisherUpdate",
    "Partner", "PartnerCreate", "PartnerUpdate",
]
