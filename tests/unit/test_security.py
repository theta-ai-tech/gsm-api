import pytest
from fastapi import HTTPException

from app.security import CurrentUser, is_owner, require_self


def test_is_owner_allows_self_access():
    user = CurrentUser(uid="abc123", email="alex@example.com")

    assert is_owner(user, "abc123") is True
    require_self(user, "abc123")  # does not raise


def test_require_self_non_owner_forbidden():
    user = CurrentUser(uid="abc123")

    with pytest.raises(HTTPException) as excinfo:
        require_self(user, "other-user")

    assert excinfo.value.status_code == 403


def test_missing_user_context_returns_unauthorized(client):
    response = client.get("/users/abc123")

    assert response.status_code == 401
