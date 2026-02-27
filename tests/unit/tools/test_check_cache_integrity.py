from unittest.mock import Mock

from tools.check_cache_integrity import (
    IntegrityReport,
    _summary_entry_ids,
    _validate_journal_recent,
)


def test_summary_entry_ids_detects_duplicates_and_cap() -> None:
    report = IntegrityReport()
    items = [{"entryId": "e1"} for _ in range(11)]

    ids = _summary_entry_ids(report, "u1", items, "journalRecent", 10)

    assert ids == ["e1"] * 11
    assert any("exceeds cap 10" in failure for failure in report.failures)
    assert any("duplicate entryId values" in failure for failure in report.failures)


def test_validate_journal_recent_reports_missing_or_deleted_entries() -> None:
    report = IntegrityReport()
    client = Mock()

    # users/u1/journalEntries/e_missing -> not found
    missing_snap = Mock()
    missing_snap.exists = False

    # users/u1/journalEntries/e_deleted -> found + isDeleted=true
    deleted_snap = Mock()
    deleted_snap.exists = True
    deleted_snap.to_dict.return_value = {"isDeleted": True}

    doc_ref = client.collection.return_value.document.return_value.collection.return_value.document
    doc_ref.side_effect = [
        Mock(get=Mock(return_value=missing_snap)),
        Mock(get=Mock(return_value=deleted_snap)),
    ]

    _validate_journal_recent(
        client,
        report,
        "u1",
        {"journalRecent": [{"entryId": "e_missing"}, {"entryId": "e_deleted"}]},
    )

    assert any(
        "missing canonical journal entry: e_missing" in failure
        for failure in report.failures
    )
    assert any(
        "soft-deleted journal entry: e_deleted" in failure
        for failure in report.failures
    )
