"""Unit tests for UsersRepo device-token methods."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.repos.users_repo import UsersRepo

_NOW = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)


def _make_repo() -> tuple[UsersRepo, MagicMock]:
    mock_client = MagicMock(spec=firestore.Client)
    return UsersRepo(mock_client), mock_client


def _make_doc_snap(data: dict | None) -> MagicMock:
    """Return a mock DocumentSnapshot that behaves like a real one."""
    snap = MagicMock()
    snap.exists = data is not None
    snap.id = "user_test"
    snap.to_dict.return_value = data or {}
    return snap


class TestUpsertDeviceToken:
    def test_new_token_appended(self):
        repo, client = _make_repo()
        snap = _make_doc_snap({"deviceTokens": []})
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.upsert_device_token("user_test", "tok_abc", "ios")

        user_ref = client.collection.return_value.document.return_value
        user_ref.update.assert_called_once()
        call_arg = user_ref.update.call_args[0][0]
        tokens = call_arg["deviceTokens"]
        assert len(tokens) == 1
        assert tokens[0]["token"] == "tok_abc"
        assert tokens[0]["platform"] == "ios"
        assert "createdAt" in tokens[0]
        assert "lastSeenAt" in tokens[0]

    def test_existing_token_refreshes_last_seen_at(self):
        repo, client = _make_repo()
        existing_created = datetime(2026, 1, 1, tzinfo=timezone.utc)
        existing_last_seen = datetime(2026, 3, 1, tzinfo=timezone.utc)
        snap = _make_doc_snap(
            {
                "deviceTokens": [
                    {
                        "token": "tok_abc",
                        "platform": "ios",
                        "createdAt": existing_created,
                        "lastSeenAt": existing_last_seen,
                    }
                ]
            }
        )
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.upsert_device_token("user_test", "tok_abc", "ios")

        user_ref = client.collection.return_value.document.return_value
        user_ref.update.assert_called_once()
        call_arg = user_ref.update.call_args[0][0]
        tokens = call_arg["deviceTokens"]
        # lastSeenAt must be updated, createdAt must stay the same
        assert tokens[0]["createdAt"] == existing_created
        assert tokens[0]["lastSeenAt"] != existing_last_seen

    def test_does_not_duplicate_when_token_exists(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(
            {
                "deviceTokens": [
                    {
                        "token": "tok_abc",
                        "platform": "ios",
                        "createdAt": _NOW,
                        "lastSeenAt": _NOW,
                    }
                ]
            }
        )
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.upsert_device_token("user_test", "tok_abc", "ios")

        user_ref = client.collection.return_value.document.return_value
        call_arg = user_ref.update.call_args[0][0]
        tokens = call_arg["deviceTokens"]
        assert len(tokens) == 1

    def test_multiple_tokens_can_coexist(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(
            {
                "deviceTokens": [
                    {
                        "token": "tok_abc",
                        "platform": "ios",
                        "createdAt": _NOW,
                        "lastSeenAt": _NOW,
                    }
                ]
            }
        )
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.upsert_device_token("user_test", "tok_xyz", "android")

        user_ref = client.collection.return_value.document.return_value
        call_arg = user_ref.update.call_args[0][0]
        tokens = call_arg["deviceTokens"]
        assert len(tokens) == 2
        token_values = {t["token"] for t in tokens}
        assert token_values == {"tok_abc", "tok_xyz"}


class TestRemoveDeviceToken:
    def test_removes_matching_token(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(
            {
                "deviceTokens": [
                    {"token": "tok_abc", "platform": "ios", "createdAt": _NOW, "lastSeenAt": _NOW},
                    {
                        "token": "tok_xyz",
                        "platform": "android",
                        "createdAt": _NOW,
                        "lastSeenAt": _NOW,
                    },
                ]
            }
        )
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.remove_device_token("user_test", "tok_abc")

        user_ref = client.collection.return_value.document.return_value
        user_ref.update.assert_called_once()
        call_arg = user_ref.update.call_args[0][0]
        tokens = call_arg["deviceTokens"]
        assert len(tokens) == 1
        assert tokens[0]["token"] == "tok_xyz"

    def test_no_op_when_token_not_found(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(
            {
                "deviceTokens": [
                    {"token": "tok_abc", "platform": "ios", "createdAt": _NOW, "lastSeenAt": _NOW}
                ]
            }
        )
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.remove_device_token("user_test", "tok_not_present")

        user_ref = client.collection.return_value.document.return_value
        user_ref.update.assert_not_called()

    def test_removes_correct_token_from_mixed_list(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(
            {
                "deviceTokens": [
                    {"token": "tok_1", "platform": "ios", "createdAt": _NOW, "lastSeenAt": _NOW},
                    {
                        "token": "tok_2",
                        "platform": "android",
                        "createdAt": _NOW,
                        "lastSeenAt": _NOW,
                    },
                    {"token": "tok_3", "platform": "ios", "createdAt": _NOW, "lastSeenAt": _NOW},
                ]
            }
        )
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.remove_device_token("user_test", "tok_2")

        user_ref = client.collection.return_value.document.return_value
        call_arg = user_ref.update.call_args[0][0]
        tokens = call_arg["deviceTokens"]
        assert len(tokens) == 2
        remaining = [t["token"] for t in tokens]
        assert "tok_2" not in remaining
        assert "tok_1" in remaining
        assert "tok_3" in remaining


class TestListDeviceTokens:
    def test_returns_token_dicts(self):
        repo, client = _make_repo()
        token_list = [
            {"token": "tok_abc", "platform": "ios", "createdAt": _NOW, "lastSeenAt": _NOW},
            {"token": "tok_xyz", "platform": "android", "createdAt": _NOW, "lastSeenAt": _NOW},
        ]
        snap = _make_doc_snap({"deviceTokens": token_list, "id": "user_test"})
        client.collection.return_value.document.return_value.get.return_value = snap

        result = repo.list_device_tokens("user_test")

        assert len(result) == 2
        assert result[0]["token"] == "tok_abc"
        assert result[1]["token"] == "tok_xyz"

    def test_returns_empty_list_for_missing_field(self):
        repo, client = _make_repo()
        snap = _make_doc_snap({"name": "Alice"})
        client.collection.return_value.document.return_value.get.return_value = snap

        result = repo.list_device_tokens("user_test")

        assert result == []

    def test_returns_empty_list_when_user_not_found(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(None)
        client.collection.return_value.document.return_value.get.return_value = snap

        result = repo.list_device_tokens("user_test")

        assert result == []
