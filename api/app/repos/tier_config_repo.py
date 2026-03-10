from __future__ import annotations

import time
from typing import Optional, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.tier import TierConfig
from app.repos.base import RepoBase

_TIER_CONFIG_TTL = 300.0  # 5 minutes

_cache: Optional[TierConfig] = None
_cache_ts: float = 0.0


class TierConfigRepo(RepoBase):
    """Read-through repo for config/tiers with a module-level in-memory TTL cache."""

    def get(self) -> TierConfig:
        global _cache, _cache_ts
        now = time.monotonic()
        if _cache is not None and (now - _cache_ts) < _TIER_CONFIG_TTL:
            return _cache
        doc = cast(
            firestore.DocumentSnapshot, self.client.collection("config").document("tiers").get()
        )
        if not doc.exists:
            raise ValueError("Tier config not found in Firestore (config/tiers)")
        data = doc.to_dict() or {}
        _cache = TierConfig.model_validate(
            {
                "thresholds": data.get("thresholds", []),
                "version": data.get("version", 1),
                "updatedAt": data["updatedAt"],
            }
        )
        _cache_ts = now
        return _cache
