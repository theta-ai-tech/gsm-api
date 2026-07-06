from __future__ import annotations

from typing import Any

import firebase_admin  # type: ignore[import-untyped]
from firebase_admin import auth as firebase_auth  # type: ignore[import-untyped]


class AuthAdmin:
    """Thin wrapper over ``firebase_admin.auth`` identity-admin operations.

    Isolated behind a class so the account-deletion service can be unit-tested
    with a mock instead of reaching out to Firebase Auth.
    """

    def __init__(self, app: firebase_admin.App) -> None:
        self._app = app

    def delete_user(self, uid: str) -> None:
        """Delete the Firebase Auth user record.

        This is the single destructive Auth operation for account deletion:
        deleting the user removes their refresh tokens and causes the next
        ``verify_id_token(..., check_revoked=True)`` to fail with
        ``UserNotFoundError``, so the caller is locked out immediately. We
        deliberately do NOT call ``revoke_refresh_tokens`` separately — a
        standalone revoke that succeeds before a failed delete would leave the
        Auth user (and its PII) present while signing the caller out, with no
        way to retry.
        """
        firebase_auth.delete_user(uid, app=self._app)


def _make_auth_admin(settings: Any) -> AuthAdmin:
    from app.deps import _get_firebase_app

    return AuthAdmin(_get_firebase_app(settings))
