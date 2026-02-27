from tools.migrate_journal_fields import _backfill_updates


def test_backfill_updates_adds_missing_fields() -> None:
    updates = _backfill_updates({"title": "t1"})

    assert updates["entryType"] == "match"
    assert updates["trainingFocus"] == []
    assert updates["durationMinutes"] is None
    assert updates["clientRequestId"] is None
    assert updates["isDeleted"] is False
    assert updates["deletedAt"] is None


def test_backfill_updates_keeps_present_fields_untouched() -> None:
    updates = _backfill_updates(
        {
            "entryType": "training",
            "trainingFocus": ["serve"],
            "durationMinutes": 30,
            "clientRequestId": "req-1",
            "isDeleted": False,
            "deletedAt": None,
            "visibility": "private",
            "title": "x",
            "body": "y",
            "tags": [],
            "reflection": None,
            "scoreText": None,
            "result": None,
        }
    )

    assert updates == {}
