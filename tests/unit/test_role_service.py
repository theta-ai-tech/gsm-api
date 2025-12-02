from unittest.mock import MagicMock

from app.services.role_service import (
    RoleService,
    get_league_member_role,
    is_league_member,
)


def _mock_db(member_exists: bool = True, role_value: str | None = "captain"):
    snapshot = MagicMock()
    snapshot.exists = member_exists
    snapshot.to_dict.return_value = {"role": role_value} if role_value else {}

    member_doc = MagicMock()
    member_doc.get.return_value = snapshot

    members_collection = MagicMock()
    members_collection.document.return_value = member_doc

    league_doc = MagicMock()
    league_doc.collection.return_value = members_collection

    leagues_collection = MagicMock()
    leagues_collection.document.return_value = league_doc

    db = MagicMock()
    db.collection.return_value = leagues_collection
    return db, snapshot, member_doc


def test_is_league_member_true():
    db, snapshot, _ = _mock_db(member_exists=True)
    service = RoleService(db=db)

    assert service.is_league_member("league-1", "user-1") is True
    assert snapshot.get_mock_calls  # snapshot was fetched


def test_is_league_member_false_when_doc_missing():
    db, _, _ = _mock_db(member_exists=False)
    service = RoleService(db=db)

    assert service.is_league_member("league-1", "user-1") is False


def test_get_league_member_role_returns_value():
    db, _, _ = _mock_db(member_exists=True, role_value="Admin")
    service = RoleService(db=db)

    assert service.get_league_member_role("league-1", "user-1") == "Admin"


def test_get_league_member_role_none_when_missing():
    db, _, _ = _mock_db(member_exists=True, role_value=None)
    service = RoleService(db=db)

    assert service.get_league_member_role("league-1", "user-1") is None


def test_convenience_functions_use_service():
    db, _, _ = _mock_db(member_exists=True, role_value="organizer")

    assert is_league_member(db, "league-2", "user-2") is True
    assert get_league_member_role(db, "league-2", "user-2") == "organizer"
