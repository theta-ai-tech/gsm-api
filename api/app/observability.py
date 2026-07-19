from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import Request

logger = logging.getLogger("gsm-api")

_TRUTHY = {"1", "true", "on", "yes"}

# Fields redacted from logged bodies (case-insensitive match on JSON keys).
REDACTED_FIELDS = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "authorization",
    "secret",
    "api_key",
    "email",
}
REDACTED = "[REDACTED]"
MAX_BODY_LOG_BYTES = 10_000


def bodies_logging_enabled() -> bool:
    return os.getenv("GSM_LOG_BODIES", "").strip().lower() in _TRUTHY


def log_error_response(
    request: Request,
    status_code: int,
    detail: Any,
    *,
    exc: Exception | None = None,
) -> None:
    """Log a non-2xx response as a compact JSON line (WARNING for 4xx, ERROR for 5xx).

    JSON goes in the message itself because the root logger's default formatter
    (configured via logging.basicConfig in main.py) renders only the message —
    `extra` fields never reach stdout or Cloud Logging.
    """
    payload = {
        "event": "http_error",
        "request_id": getattr(request.state, "request_id", None),
        "method": request.method,
        "path": request.url.path,
        "status": status_code,
        "detail": detail,
    }
    message = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    if status_code >= 500:
        logger.error(message, exc_info=exc)
    else:
        logger.warning(message)


def _redact(obj: Any) -> Any:
    """Recursively replace values of sensitive keys in parsed JSON."""
    if isinstance(obj, dict):
        return {
            k: (REDACTED if k.lower() in REDACTED_FIELDS else _redact(v)) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _render_body(raw: bytes, content_type: str) -> Any:
    """Return a loggable, redacted representation of a body."""
    if not raw:
        return None
    if len(raw) > MAX_BODY_LOG_BYTES:
        return f"[truncated: {len(raw)} bytes]"
    if "application/json" in content_type:
        try:
            return _redact(json.loads(raw))
        except (ValueError, UnicodeDecodeError):
            pass
    if content_type.startswith("text/") or "application/json" in content_type:
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover — decode with errors="replace" cannot raise
            return f"[undecodable: {len(raw)} bytes]"
    return f"[binary or unsupported content-type: {content_type or 'unknown'}; {len(raw)} bytes]"


def log_request_response_bodies(
    request: Request,
    request_body: bytes,
    response_body: bytes,
    response_status: int,
    response_content_type: str,
) -> None:
    payload = {
        "event": "http_body",
        "request_id": getattr(request.state, "request_id", None),
        "method": request.method,
        "path": request.url.path,
        "status": response_status,
        "request_body": _render_body(request_body, request.headers.get("content-type", "")),
        "response_body": _render_body(response_body, response_content_type),
    }
    logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str))
