"""
Shared base model configuration for all domain models.

All models use:
  - extra="allow"  → preserves unknown JSON fields; prevents data loss when
                     the JSON config files contain keys the model doesn't declare
  - populate_by_name=True → allow both alias and field name for initialisation
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AppBaseModel(BaseModel):
    """
    Base class for all GPX domain models.

    extra="allow" is critical: the JSON config files may contain fields added
    by future versions of the app.  We never discard unknown fields on read,
    so round-tripping JSON → model → JSON always preserves all data.
    """

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
    )
