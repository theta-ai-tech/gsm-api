from __future__ import annotations

import hashlib

from app.constants import PARTNER_INVITE_UID_PREFIX


def normalize_email(email: str) -> str:
    """Normalize an email for use as a durable match key (strip + lowercase)."""
    return email.strip().lower()


def partner_placeholder_uid(email: str) -> str:
    """Deterministic placeholder uid for an unregistered partner.

    ``"invite:" + sha256(normalized_email)[:24]`` — carries no PII, is stable
    across invites of the same email, and is prefix-detectable so rating math
    can skip it.
    """
    digest = hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()
    return f"{PARTNER_INVITE_UID_PREFIX}{digest[:24]}"
