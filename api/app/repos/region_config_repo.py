from __future__ import annotations

import time
from typing import Optional, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.region_config import RegionConfig
from app.repos.base import RepoBase

_REGION_CONFIG_TTL = 300.0  # 5 minutes

_cache: Optional[RegionConfig] = None
_cache_ts: float = 0.0


class RegionConfigRepo(RepoBase):
    """Read-through repo for config/regions with a module-level in-memory TTL cache."""

    def get(self) -> RegionConfig:
        global _cache, _cache_ts
        now = time.monotonic()
        if _cache is not None and (now - _cache_ts) < _REGION_CONFIG_TTL:
            return _cache
        doc = cast(
            firestore.DocumentSnapshot,
            self.client.collection("config").document("regions").get(),
        )
        if not doc.exists:
            raise ValueError("Region config not found in Firestore (config/regions)")
        data = doc.to_dict() or {}
        _cache = RegionConfig(
            mapping=data.get("mapping", {}),
            version=data.get("version", 1),
        )
        _cache_ts = now
        return _cache
