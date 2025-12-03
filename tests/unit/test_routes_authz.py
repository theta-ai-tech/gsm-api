import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_role_service
from app.main import app
from app.security import CurrentUser


class FakeRoleService:
    def __init__(
        self, member: bool, member_role: str | None = None, owner_uid: str | None = None
    ):
        self.member = member
        self.member_role = member_role
        self.owner_uid = owner_uid

    def is_league_member(self, league_id: str, uid: str) -> bool:  # noqa: ARG002
        return self.member

    def get_league_member_role(self, league_id: str, uid: str) -> str | None:  # noqa: ARG002
        return self.member_role

    def get_league_owner_uid(self, league_id: str) -> str | None:  # noqa: ARG002
        return self.owner_uid


@pytest.fixture(autouse=True)
def _reset_overrides():
    original = app.dependency_overrides.copy()
    yield
    app.dependency_overrides = original


def _client(user: CurrentUser, role_service: FakeRoleService) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_role_service] = lambda: role_service
    return TestClient(app)


def test_add_member_requires_admin_token_or_membership():
    admin_user = CurrentUser(uid="admin-1", roles=["admin"])
    client = _client(admin_user, FakeRoleService(member=False))

    resp = client.post("/leagues/league-1/members")
    assert resp.status_code == 201


def test_add_member_blocks_non_admin_member():
    member_user = CurrentUser(uid="user-1", roles=["player"])
    client = _client(member_user, FakeRoleService(member=True, member_role="player"))

    resp = client.post("/leagues/league-1/members")
    assert resp.status_code == 403


def test_delete_member_requires_admin():
    admin_user = CurrentUser(uid="admin-1", roles=["admin"])
    client = _client(admin_user, FakeRoleService(member=False))

    resp = client.delete("/leagues/league-1/members/target-1")
    assert resp.status_code == 204


def test_delete_member_blocks_non_admin_member():
    member_user = CurrentUser(uid="user-1", roles=["player"])
    client = _client(member_user, FakeRoleService(member=True, member_role="player"))

    resp = client.delete("/leagues/league-1/members/target-1")
    assert resp.status_code == 403
