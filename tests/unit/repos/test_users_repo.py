"""Unit tests for UsersRepo device-token methods."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.enums import PlatformEnum
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


def _make_query_doc(doc_id: str, data: dict) -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id
    doc.to_dict.return_value = data
    return doc


class TestSearchByNamePrefix:
    def _wire_stream(self, client: MagicMock, docs: list[MagicMock]) -> MagicMock:
        query = MagicMock()
        query.where.return_value = query
        query.limit.return_value = query
        query.stream.return_value = docs
        client.collection.return_value = query
        return query

    def test_returns_matching_docs_with_uid(self):
        repo, client = _make_repo()
        self._wire_stream(
            client,
            [
                _make_query_doc("user_maria", {"name": "Maria"}),
                _make_query_doc("user_marios", {"name": "Marios"}),
            ],
        )

        results = repo.search_by_name_prefix("Mar", limit=10)

        assert [r["uid"] for r in results] == ["user_maria", "user_marios"]

    def test_lowercases_query_for_range(self):
        repo, client = _make_repo()
        query = self._wire_stream(client, [])

        repo.search_by_name_prefix("MaR", limit=10)

        # First where clause is the >= lower bound on nameLower.
        first_where = query.where.call_args_list[0]
        assert first_where.args[0] == "nameLower"
        assert first_where.args[1] == ">="
        assert first_where.args[2] == "mar"

        # Second where clause is the < upper bound: prefix + the \uf8ff
        # Firestore sentinel. Without it the range is empty and search
        # silently returns nothing — do not drop the sentinel.
        second_where = query.where.call_args_list[1]
        assert second_where.args[0] == "nameLower"
        assert second_where.args[1] == "<"
        assert second_where.args[2] == "mar\uf8ff"

    def test_excludes_caller(self):
        repo, client = _make_repo()
        self._wire_stream(
            client,
            [
                _make_query_doc("user_me", {"name": "Marcus"}),
                _make_query_doc("user_other", {"name": "Marisol"}),
            ],
        )

        results = repo.search_by_name_prefix("mar", limit=10, exclude_uid="user_me")

        assert [r["uid"] for r in results] == ["user_other"]

    def test_respects_limit(self):
        repo, client = _make_repo()
        self._wire_stream(
            client,
            [_make_query_doc(f"user_{i}", {"name": f"Mar{i}"}) for i in range(5)],
        )

        results = repo.search_by_name_prefix("mar", limit=2)

        assert len(results) == 2

    def test_blank_query_returns_empty(self):
        repo, _ = _make_repo()
        assert repo.search_by_name_prefix("   ", limit=10) == []


class TestUpsertDeviceToken:
    def test_new_token_appended(self):
        repo, client = _make_repo()
        snap = _make_doc_snap({"deviceTokens": []})
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.upsert_device_token("user_test", "tok_abc", PlatformEnum.IOS)

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

        repo.upsert_device_token("user_test", "tok_abc", PlatformEnum.IOS)

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

        repo.upsert_device_token("user_test", "tok_abc", PlatformEnum.IOS)

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

        repo.upsert_device_token("user_test", "tok_xyz", PlatformEnum.ANDROID)

        user_ref = client.collection.return_value.document.return_value
        call_arg = user_ref.update.call_args[0][0]
        tokens = call_arg["deviceTokens"]
        assert len(tokens) == 2
        token_values = {t["token"] for t in tokens}
        assert token_values == {"tok_abc", "tok_xyz"}

    def test_raises_for_missing_user(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(None)
        client.collection.return_value.document.return_value.get.return_value = snap

        with pytest.raises(ValueError, match="user_not_found"):
            repo.upsert_device_token("ghost_uid", "tok_abc", PlatformEnum.IOS)

        user_ref = client.collection.return_value.document.return_value
        user_ref.update.assert_not_called()

    def test_new_token_when_device_tokens_field_absent(self):
        """upsert when the user doc exists but has no deviceTokens field yet."""
        repo, client = _make_repo()
        snap = _make_doc_snap({"name": "Alice"})  # no deviceTokens key
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.upsert_device_token("user_test", "tok_abc", PlatformEnum.IOS)

        user_ref = client.collection.return_value.document.return_value
        user_ref.update.assert_called_once()
        call_arg = user_ref.update.call_args[0][0]
        tokens = call_arg["deviceTokens"]
        assert len(tokens) == 1
        assert tokens[0]["token"] == "tok_abc"


class TestRemoveDeviceToken:
    def test_removes_matching_token(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(
            {
                "deviceTokens": [
                    {
                        "token": "tok_abc",
                        "platform": "ios",
                        "createdAt": _NOW,
                        "lastSeenAt": _NOW,
                    },
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

        repo.remove_device_token("user_test", "tok_not_present")

        user_ref = client.collection.return_value.document.return_value
        user_ref.update.assert_not_called()

    def test_removes_correct_token_from_mixed_list(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(
            {
                "deviceTokens": [
                    {
                        "token": "tok_1",
                        "platform": "ios",
                        "createdAt": _NOW,
                        "lastSeenAt": _NOW,
                    },
                    {
                        "token": "tok_2",
                        "platform": "android",
                        "createdAt": _NOW,
                        "lastSeenAt": _NOW,
                    },
                    {
                        "token": "tok_3",
                        "platform": "ios",
                        "createdAt": _NOW,
                        "lastSeenAt": _NOW,
                    },
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

    def test_no_op_when_user_not_found(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(None)
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.remove_device_token("ghost_uid", "tok_abc")

        user_ref = client.collection.return_value.document.return_value
        user_ref.update.assert_not_called()


class TestAnonymize:
    def test_keeps_uid_and_rankings_strips_pii(self):
        repo, client = _make_repo()
        rankings = {"padel": {"sport": "padel", "pts": 1020}}
        snap = _make_doc_snap(
            {
                "uid": "user_test",
                "name": "Ignatios",
                "email": "ignatios@example.com",
                "phone": "+301111111111",
                "profileUrl": "http://example.com/i.png",
                "preferences": {"area": 101},
                "deviceTokens": [{"token": "tok_abc"}],
                "skillDna": {"padel": {}},
                "rankings": rankings,
            }
        )
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.anonymize("user_test")

        user_ref = client.collection.return_value.document.return_value
        user_ref.set.assert_called_once()
        written = user_ref.set.call_args[0][0]
        # Kept
        assert written["uid"] == "user_test"
        assert written["rankings"] == rankings
        # Tombstone flags
        assert written["name"] == "Deleted Player"
        assert written["profileUrl"] is None
        assert written["isDeleted"] is True
        assert "deletedAt" in written
        # PII / private fields stripped (full-document overwrite, no merge)
        assert "email" not in written
        assert "phone" not in written
        assert "preferences" not in written
        assert "deviceTokens" not in written
        assert "skillDna" not in written

    def test_missing_doc_writes_bare_tombstone(self):
        repo, client = _make_repo()
        snap = _make_doc_snap(None)
        client.collection.return_value.document.return_value.get.return_value = snap

        repo.anonymize("ghost_uid")

        user_ref = client.collection.return_value.document.return_value
        written = user_ref.set.call_args[0][0]
        assert written["uid"] == "ghost_uid"
        assert written["rankings"] == {}
        assert written["isDeleted"] is True


class TestListDeviceTokens:
    def test_returns_token_dicts(self):
        repo, client = _make_repo()
        token_list = [
            {
                "token": "tok_abc",
                "platform": "ios",
                "createdAt": _NOW,
                "lastSeenAt": _NOW,
            },
            {
                "token": "tok_xyz",
                "platform": "android",
                "createdAt": _NOW,
                "lastSeenAt": _NOW,
            },
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
