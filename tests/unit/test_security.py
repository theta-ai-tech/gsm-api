import pytest
from fastapi import HTTPException
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.security import (
    CurrentUser,
    require_membership,
    require_league_member,
    is_admin,
    is_owner,
    require_any_role,
    require_roles,
    require_self,
)
from app.deps import get_current_user, get_role_service


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


class FakeRoleService:
    def __init__(self, member: bool, member_role: str | None = None, owner_uid: str | None = None):
        self.member = member
        self.member_role = member_role
        self.owner_uid = owner_uid

    def is_league_member(self, league_id: str, uid: str) -> bool:  # noqa: ARG002
        return self.member

    def get_league_member_role(self, league_id: str, uid: str) -> str | None:  # noqa: ARG002
        return self.member_role

    def get_league_owner_uid(self, league_id: str) -> str | None:  # noqa: ARG002
        return self.owner_uid


def test_require_membership_allows_global_role_without_firestore_call():
    user = CurrentUser(uid="u1", roles=["Player"])
    role_service = FakeRoleService(member=False, member_role=None)

    require_membership(user, "league-1", role_service, required_role="player")


def test_require_membership_allows_member_role_from_firestore():
    user = CurrentUser(uid="u1", roles=[])
    role_service = FakeRoleService(member=True, member_role="captain")

    require_membership(user, "league-1", role_service, required_role="captain")


def test_require_membership_allows_owner_even_without_role():
    user = CurrentUser(uid="owner-1", roles=[])
    role_service = FakeRoleService(member=False, member_role=None, owner_uid="owner-1")

    require_membership(user, "league-1", role_service, required_role=None)


def test_require_membership_forbidden_when_no_match():
    user = CurrentUser(uid="u1", roles=[])
    role_service = FakeRoleService(member=False, member_role=None)

    with pytest.raises(HTTPException) as excinfo:
        require_membership(user, "league-1", role_service, required_role="player")

    assert excinfo.value.status_code == 403


def test_require_league_member_dependency_passes_for_member():
    user = CurrentUser(uid="u1", roles=[])
    role_service = FakeRoleService(member=True, member_role="player")
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_role_service] = lambda: role_service

    @app.get("/leagues/{league_id}/protected", dependencies=[Depends(require_league_member("player"))])
    def _protected():  # pragma: no cover - simple passthrough
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/leagues/league-1/protected")
    assert response.status_code == 200


def test_require_league_member_dependency_blocks_non_member():
    user = CurrentUser(uid="u1", roles=[])
    role_service = FakeRoleService(member=False, member_role=None)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_role_service] = lambda: role_service

    @app.get("/leagues/{league_id}/protected", dependencies=[Depends(require_league_member("player"))])
    def _protected():  # pragma: no cover - simple passthrough
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/leagues/league-1/protected")
    assert response.status_code == 403
