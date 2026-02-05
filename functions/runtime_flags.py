from __future__ import annotations

import os


def _to_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def triggers_enabled() -> bool:
    """
    Global kill switch for trigger writes.
    Defaults to enabled when GSM_TRIGGERS_ENABLED is not set.
    """
    return _to_bool(os.getenv("GSM_TRIGGERS_ENABLED"), default=True)
