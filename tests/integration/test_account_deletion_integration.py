"""Integration tests for DELETE /me/account (emulator-backed).

Covers the anonymize-in-place (tombstone) contract: own subcollections and device
tokens are deleted, the user doc is tombstoned keeping uid + rankings, and an
opponent's rivalry read against the deleted uid still returns 200 as "Deleted Player".

Firebase Auth admin is faked (no Auth emulator dependency); the Firestore side is real.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.dependencies.repos import (
    get_auth_admin,
    get_journal_repo,
    get_matches_repo,
    get_point_history_repo,
    get_users_repo,
)
from app.deps import get_current_user
from app.main import app
from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.users_repo import UsersRepo
from app.models import compute_participant_pair
from app.security import CurrentUser

pytestmark = [pytest.mark.integration]

_TARGET = "user_acct_del_target"
_OPPONENT = "user_acct_del_opponent"
_MATCH_ID = "match_acct_del"
_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


class _FakeAuthAdmin:
    """Records Auth-admin calls without touching Firebase."""

    def __init__(self) -> None:
        self.revoked: list[str] = []
        self.deleted: list[str] = []

    def revoke_refresh_tokens(self, uid: str) -> None:
        self.revoked.append(uid)

    def delete_user(self, uid: str) -> None:
        self.deleted.append(uid)


def _seed(db: firestore.Client) -> None:
    users = db.collection("users")
    users.document(_TARGET).set(
        {
            "uid": _TARGET,
            "name": "Target Player",
            "email": "target@example.com",
            "phone": "+301234567890",
            "profileUrl": "http://example.com/t.png",
            "preferences": {"area": 101, "sports": ["padel"]},
            "deviceTokens": [
                {
                    "token": "tok_target",
                    "platform": "ios",
                    "createdAt": _NOW,
                    "lastSeenAt": _NOW,
                }
            ],
            "rankings": {"padel": {"sport": "padel", "pts": 1200, "tier": "amateur"}},
        }
    )
    users.document(_TARGET).collection("journalEntries").document("j1").set(
        {
            "uid": _TARGET,
            "createdAt": _NOW,
            "title": "note",
            "body": "b",
            "visibility": "private",
        }
    )
    users.document(_TARGET).collection("pointHistory").document("p1").set(
        {
            "sport": "padel",
            "pts": 1200,
            "delta": 20,
            "reason": "match_win",
            "createdAt": _NOW,
        }
    )
    users.document(_OPPONENT).set(
        {
            "uid": _OPPONENT,
            "name": "Opponent Player",
            "email": "opp@example.com",
            "preferences": {"area": 101, "sports": ["padel"]},
            "rankings": {"padel": {"sport": "padel", "pts": 1100, "tier": "amateur"}},
        }
    )
    pair = compute_participant_pair([_TARGET, _OPPONENT])
    db.collection("matches").document(_MATCH_ID).set(
        {
            "sport": "padel",
            "status": "completed",
            "matchType": "singles",
            "participantUids": [_TARGET, _OPPONENT],
            "participantPair": pair,
            "resultByUser": {_TARGET: "W", _OPPONENT: "L"},
            "finishedAt": _NOW,
        }
    )


def _cleanup(db: firestore.Client) -> None:
    for uid in (_TARGET, _OPPONENT):
        ref = db.collection("users").document(uid)
        for sub in ("journalEntries", "pointHistory"):
            for doc in ref.collection(sub).stream():
                doc.reference.delete()
        ref.delete()
    db.collection("matches").document(_MATCH_ID).delete()


@pytest.fixture()
def account_client(firestore_client: firestore.Client):
    _cleanup(firestore_client)
    _seed(firestore_client)
    fake_auth = _FakeAuthAdmin()
    app.dependency_overrides[get_users_repo] = lambda: UsersRepo(firestore_client)
    app.dependency_overrides[get_journal_repo] = lambda: JournalRepo(firestore_client)
    app.dependency_overrides[get_point_history_repo] = lambda: PointHistoryRepo(
        firestore_client
    )
    app.dependency_overrides[get_matches_repo] = lambda: MatchesRepo(firestore_client)
    app.dependency_overrides[get_auth_admin] = lambda: fake_auth
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_TARGET, email=None
    )
    yield TestClient(app), firestore_client, fake_auth
    app.dependency_overrides.clear()
    _cleanup(firestore_client)


class TestAccountDeletionIntegration:
    def test_delete_tombstones_and_cleans_up(self, account_client) -> None:
        client, db, fake_auth = account_client

        response = client.request("DELETE", "/me/account")
        assert response.status_code == 204

        # Auth revoke + delete happened.
        assert fake_auth.revoked == [_TARGET]
        assert fake_auth.deleted == [_TARGET]

        # Own subcollections deleted.
        assert (
            list(
                db.collection("users")
                .document(_TARGET)
                .collection("journalEntries")
                .stream()
            )
            == []
        )
        assert (
            list(
                db.collection("users")
                .document(_TARGET)
                .collection("pointHistory")
                .stream()
            )
            == []
        )

        # User doc tombstoned: uid + rankings kept, PII + tokens stripped.
        doc = db.collection("users").document(_TARGET).get().to_dict() or {}
        assert doc["name"] == "Deleted Player"
        assert doc["profileUrl"] is None
        assert doc["isDeleted"] is True
        assert "deletedAt" in doc
        assert doc["rankings"]["padel"]["pts"] == 1200
        assert "email" not in doc
        assert "phone" not in doc
        assert "preferences" not in doc
        assert "deviceTokens" not in doc

    def test_opponent_rivalry_still_resolves_as_deleted_player(
        self, account_client
    ) -> None:
        client, db, _fake_auth = account_client

        # Delete the target account.
        assert client.request("DELETE", "/me/account").status_code == 204

        # Match doc must be untouched (no cascade).
        match = db.collection("matches").document(_MATCH_ID).get()
        assert match.exists

        # Opponent reads the rivalry against the deleted uid -> 200, "Deleted Player".
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            uid=_OPPONENT, email=None
        )
        rivalry = client.get(f"/me/lab/rivalry/{_TARGET}", params={"sport": "padel"})
        assert rivalry.status_code == 200
        body = rivalry.json()
        assert body["opponent"]["uid"] == _TARGET
        assert body["opponent"]["name"] == "Deleted Player"
        assert body["head_to_head"]["total_matches"] == 1
