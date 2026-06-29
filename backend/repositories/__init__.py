"""
backend.repositories — data access layer.

Entry points
------------
    from backend.repositories.base    import GameConfigRepository, PublisherRepository, PartnerRepository
    from backend.repositories.cache   import CacheFactory, DictCache
    from backend.repositories.factory import RepositoryFactory
"""

from backend.repositories.base    import GameConfigRepository, PublisherRepository, PartnerRepository
from backend.repositories.cache   import CacheFactory, CacheProvider, DictCache
from backend.repositories.factory import RepositoryFactory

__all__ = [
    "GameConfigRepository",
    "PublisherRepository",
    "PartnerRepository",
    "CacheProvider",
    "DictCache",
    "CacheFactory",
    "RepositoryFactory",
]
