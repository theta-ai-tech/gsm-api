from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models.scouting import ScoutingProfile
from app.repos.scouting_repo import ScoutingRepo

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]


def _make_repo() -> tuple[ScoutingRepo, MagicMock]:
    mock_client = MagicMock(spec=firestore.Client)
    return ScoutingRepo(mock_client), mock_client


class TestGetProfile:
    def test_returns_none_when_doc_missing(self):
        repo, client = _make_repo()
        mock_snap = MagicMock()
        mock_snap.exists = False
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_profile("user_unknown")

        assert result is None
        client.collection.assert_called_once_with("scouting")
        client.collection.return_value.document.assert_called_once_with("user_unknown")

    def test_returns_profile_with_sport_data(self):
        repo, client = _make_repo()
        now = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.id = "user_bob"
        mock_snap.to_dict.return_value = {
            "uid": "user_bob",
            "tennis": {
                "weak": {
                    "backhand": {"count": 7, "lastReported": now},
                    "stamina_set3": {"count": 3, "lastReported": now},
                },
                "strong": {
                    "first_serve": {"count": 5, "lastReported": now},
                },
                "totalReports": 12,
                "uniqueReporters": 8,
                "lastUpdated": now,
            },
        }
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_profile("user_bob")

        assert result is not None
        assert isinstance(result, ScoutingProfile)
        assert result.uid == "user_bob"
        assert result.tennis is not None
        assert result.tennis.total_reports == 12
        assert result.tennis.unique_reporters == 8
        assert result.tennis.last_updated == now
        assert "backhand" in result.tennis.weak
        assert result.tennis.weak["backhand"].count == 7
        assert result.tennis.weak["backhand"].last_reported == now
        assert "stamina_set3" in result.tennis.weak
        assert result.tennis.weak["stamina_set3"].count == 3
        assert "first_serve" in result.tennis.strong
        assert result.tennis.strong["first_serve"].count == 5
        assert result.padel is None
        assert result.pickleball is None

    def test_returns_profile_with_empty_sport_data(self):
        repo, client = _make_repo()
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.id = "user_empty"
        mock_snap.to_dict.return_value = {"uid": "user_empty"}
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_profile("user_empty")

        assert result is not None
        assert result.uid == "user_empty"
        assert result.tennis is None
        assert result.padel is None
        assert result.pickleball is None


class TestIncrementTag:
    @patch("app.repos.scouting_repo.datetime")
    def test_increment_tag_calls_set_with_merge(self, mock_dt: MagicMock):
        now = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        repo, client = _make_repo()
        mock_doc_ref = MagicMock()
        client.collection.return_value.document.return_value = mock_doc_ref

        repo.increment_tag("user_bob", "tennis", "weak", "backhand")

        client.collection.assert_called_once_with("scouting")
        client.collection.return_value.document.assert_called_once_with("user_bob")
        mock_doc_ref.set.assert_called_once()
        call_args = mock_doc_ref.set.call_args
        data = call_args[0][0]
        assert data["uid"] == "user_bob"
        assert "tennis" in data
        assert "weak" in data["tennis"]
        assert "backhand" in data["tennis"]["weak"]
        assert data["tennis"]["weak"]["backhand"]["lastReported"] == now
        assert data["tennis"]["totalReports"] == firestore.Increment(1)
        assert data["tennis"]["lastUpdated"] == now
        assert call_args[1]["merge"] is True

    @patch("app.repos.scouting_repo.datetime")
    def test_increment_strong_tag(self, mock_dt: MagicMock):
        now = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        repo, client = _make_repo()
        mock_doc_ref = MagicMock()
        client.collection.return_value.document.return_value = mock_doc_ref

        repo.increment_tag("user_bob", "padel", "strong", "first_serve")

        call_args = mock_doc_ref.set.call_args
        data = call_args[0][0]
        assert data["uid"] == "user_bob"
        assert "padel" in data
        assert "strong" in data["padel"]
        assert "first_serve" in data["padel"]["strong"]
