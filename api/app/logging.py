from __future__ import annotations

import json
import logging
from typing import Any


def log_analytics_event(
    logger: logging.Logger,
    *,
    event: str,
    uid: str,
    entry_type: str | None = None,
    sport: str | None = None,
    match_id: str | None = None,
) -> None:
    """Emit a compact, structured analytics event without sensitive payload fields."""
    payload: dict[str, Any] = {
        "event": event,
        "uid": uid,
        "entry_type": entry_type,
        "sport": sport,
        "match_id": match_id,
    }
    logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
