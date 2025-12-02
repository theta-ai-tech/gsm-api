import pytest
from fastapi import HTTPException

from app.security import (
    CurrentUser,
    is_admin,
    is_owner,
    require_any_role,
    require_roles,
    require_self,
)


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


def test_require_roles_all_present():
    user = CurrentUser(uid="abc123", roles=["Admin", "Editor"])

    require_roles(user, ["admin", "editor"])
    require_roles(user, [])  # empty required roles should pass


def test_require_roles_missing_forbidden():
    user = CurrentUser(uid="abc123", roles=["editor"])

    with pytest.raises(HTTPException) as excinfo:
        require_roles(user, ["admin"])

    assert excinfo.value.status_code == 403


def test_require_any_role_passes_when_one_matches():
    user = CurrentUser(uid="abc123", roles=["viewer"])

    require_any_role(user, ["admin", "viewer"])
    require_any_role(user, [])  # empty required roles should pass


def test_require_any_role_forbidden_when_none_match():
    user = CurrentUser(uid="abc123", roles=["viewer"])

    with pytest.raises(HTTPException) as excinfo:
        require_any_role(user, ["admin", "editor"])

    assert excinfo.value.status_code == 403


def test_is_admin_detects_aliases_case_insensitive():
    assert is_admin(CurrentUser(uid="abc123", roles=["ADMIN"])) is True
    assert is_admin(CurrentUser(uid="abc123", roles=["administrator"])) is True
    assert is_admin(CurrentUser(uid="abc123", roles=["user"])) is False
