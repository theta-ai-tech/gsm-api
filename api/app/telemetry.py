"""Cloud Logging / Error Reporting wiring for production.

The app already emits structured logs and logs 5xx with a traceback (see
`observability.py`). For those exceptions to surface in **Cloud Error Reporting**
they must reach Cloud Logging with severity ``ERROR`` — plain stdout text on Cloud
Run is ingested at severity ``DEFAULT`` and is not reliably grouped as an error.

`setup_cloud_logging()` attaches the `google-cloud-logging` handler, which maps
Python levels to Cloud Logging severities (so `logger.error(..., exc_info=exc)`
becomes a severity-ERROR entry with a stack trace that Error Reporting groups).

It is **gated** so tests and local runs are never affected:
  - Enabled when `GSM_ENABLE_CLOUD_LOGGING` is truthy, OR when running on Cloud Run
    (`K_SERVICE` is set) unless explicitly disabled with `GSM_ENABLE_CLOUD_LOGGING=0`.
  - Any failure to initialize is swallowed (logged as a warning) so it can never
    break app startup.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("gsm-api")

_TRUTHY = {"1", "true", "on", "yes"}
_FALSY = {"0", "false", "off", "no"}


def cloud_logging_enabled() -> bool:
    """Whether the Cloud Logging handler should be installed for this process."""
    flag = os.getenv("GSM_ENABLE_CLOUD_LOGGING", "").strip().lower()
    if flag in _TRUTHY:
        return True
    if flag in _FALSY:
        return False
    # No explicit flag: enable automatically on Cloud Run (K_SERVICE is set there).
    return bool(os.getenv("K_SERVICE"))


def setup_cloud_logging() -> bool:
    """Attach the Cloud Logging handler when enabled. Returns True if installed."""
    if not cloud_logging_enabled():
        return False
    try:
        import google.cloud.logging  # imported lazily; only needed in prod

        client = google.cloud.logging.Client()
        # Routes stdlib logging → Cloud Logging with correct severities, which is
        # what lets ERROR entries (with tracebacks) show up in Error Reporting.
        client.setup_logging(log_level=logging.INFO)
        logger.info('{"event":"cloud_logging_enabled"}')
        return True
    except Exception as exc:  # pragma: no cover - defensive, prod-only path
        logger.warning(
            '{"event":"cloud_logging_setup_failed","detail":"%s"}',
            type(exc).__name__,
        )
        return False
