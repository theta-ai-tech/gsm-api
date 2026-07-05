from __future__ import annotations

from typing import Any

from functions.league_triggers import on_league_member_write as trigger


class _FakeDoc:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return self._data


class _FakeDocument:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data

    def get(self) -> _FakeDoc:
        return _FakeDoc(self._data)


class _FakeCollection:
    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = docs

    def document(self, doc_id: str) -> _FakeDocument:
        return _FakeDocument(self._docs.get(doc_id))


class _FakeClient:
    def __init__(self, leagues: dict[str, dict[str, Any]]) -> None:
        self._leagues = leagues

    def collection(self, name: str) -> _FakeCollection:
        assert name == "leagues"
        return _FakeCollection(self._leagues)


def test_division_id_only_member_change_qualifies_for_upsert() -> None:
    before = {
        "uid": "user_1",
        "role": "player",
        "status": "active",
        "divisionId": None,
    }
    after = {**before, "divisionId": "div-1"}

    result = trigger.qualify_league_member_upsert("league_1", before, after)

    assert result.qualifies is True


def test_unchanged_division_id_does_not_qualify_as_no_op() -> None:
    before = {
        "uid": "user_1",
        "role": "player",
        "status": "active",
        "divisionId": "div-1",
    }
    after = dict(before)

    result = trigger.qualify_league_member_upsert("league_1", before, after)

    assert result.qualifies is False
    assert result.reason == "no_op"


def test_handle_league_member_upsert_writes_division_id_summary(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def _capture_upsert(
        client,
        uid: str,
        league_id: str,
        summary: dict[str, Any],
        cap: int = 20,
    ) -> bool:
        captured.update(
            {
                "uid": uid,
                "league_id": league_id,
                "summary": summary,
                "cap": cap,
            }
        )
        return True

    monkeypatch.setattr(trigger, "_upsert_user_league_summary", _capture_upsert)
    client = _FakeClient(
        {
            "league_1": {
                "name": "Athens League",
                "sport": "padel",
                "status": "active",
            }
        }
    )
    before = {
        "uid": "user_1",
        "role": "player",
        "status": "active",
        "displayName": "Alice",
        "divisionId": None,
    }
    after = {**before, "divisionId": "div-1"}

    changed = trigger.handle_league_member_upsert(client, "league_1", before, after)

    assert changed is True
    assert captured["uid"] == "user_1"
    assert captured["league_id"] == "league_1"
    assert captured["summary"] == {
        "leagueId": "league_1",
        "name": "Athens League",
        "sport": "padel",
        "status": "active",
        "role": "player",
        "displayName": "Alice",
        "divisionId": "div-1",
    }
