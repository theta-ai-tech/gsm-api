from __future__ import annotations

import json
import logging
from typing import Any


def log_analytics_event(
    logger: logging.Logger,
    *,
    event: str,
    uid: str,
    created_at: str | None = None,
    sport: str | None = None,
    match_type: str | None = None,
    region: str | None = None,
    venue_present: bool | None = None,
    broadcast_id: str | None = None,
    offer_id: str | None = None,
    match_id: str | None = None,
    entry_type: str | None = None,
) -> None:
    """Emit a compact, structured analytics event without sensitive payload fields."""
    payload: dict[str, Any] = {
        "event": event,
        "uid": uid,
        "created_at": created_at,
        "sport": sport,
        "match_type": match_type,
        "region": region,
        "venue_present": venue_present,
        "broadcast_id": broadcast_id,
        "offer_id": offer_id,
        "match_id": match_id,
        "entry_type": entry_type,
    }
    logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
