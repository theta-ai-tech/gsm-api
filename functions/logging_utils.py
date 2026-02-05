from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger("gsm-functions")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(val) for key, val in value.items()}
    return value


def runtime_revision() -> str:
    # Prefer explicit app revision, then Cloud Run revision, then fallback.
    return os.getenv("GSM_REVISION") or os.getenv("K_REVISION") or "unknown"


def build_event(trigger: str, action: str, **fields: Any) -> dict[str, Any]:
    payload = {"trigger": trigger, "action": action, "revision": runtime_revision(), **fields}
    return _jsonable(payload)


def format_event(trigger: str, action: str, **fields: Any) -> str:
    return json.dumps(build_event(trigger, action, **fields), sort_keys=True)


def log_event(trigger: str, action: str, **fields: Any) -> None:
    logger.info(format_event(trigger, action, **fields))


def summarize_uids(uids: list[str], limit: int = 3) -> dict[str, Any]:
    normalized = [str(uid) for uid in uids]
    return {
        "uids_count": len(normalized),
        "uids_preview": normalized[:limit],
    }
