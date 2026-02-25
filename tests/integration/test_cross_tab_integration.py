from datetime import datetime, timedelta, timezone

import pytest

from app.models.enums import JournalEntryTypeEnum, MatchResultEnum, SportEnum
from app.models.journal import CreateJournalEntryRequest
from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.users_repo import UsersRepo
from app.services.journal_service import JournalService
from functions.match_triggers.main import handle_match_write_migrate_on_completion

pytestmark = [pytest.mark.integration]


def _seed_user(db, uid: str) -> None:
    db.collection("users").document(uid).set(
        {
            "uid": uid,
            "name": f"User {uid}",
            "email": f"{uid}@test.com",
        }
    )


def _make_journal_service(db) -> JournalService:
    return JournalService(
        users_repo=UsersRepo(db),
        journal_repo=JournalRepo(db),
        matches_repo=MatchesRepo(db),
        firestore_client=db,
    )


def _complete_match_and_run_cache_trigger(
    db,
    *,
    match_id: str,
    home_uid: str,
    away_uid: str,
) -> tuple[datetime, dict]:
    now = datetime.now(timezone.utc)
    scheduled_at = now - timedelta(hours=2)
    finished_at = now - timedelta(minutes=10)

    before = {
        "matchId": match_id,
        "status": "scheduled",
        "sport": SportEnum.TENNIS.value,
        "scheduledAt": scheduled_at,
        "participantUids": [home_uid, away_uid],
        "participants": [
            {"uid": home_uid, "role": "player", "team": 1},
            {"uid": away_uid, "role": "player", "team": 2},
        ],
        "leagueId": "league_cross_tab",
    }

    after = {
        **before,
        "status": "completed",
        "finishedAt": finished_at,
        "resultByUser": {
            home_uid: MatchResultEnum.WIN.value,
            away_uid: MatchResultEnum.LOSS.value,
        },
        "score": {
            "scoreText": "6-4 6-3",
            "sets": [
                {"p1Games": 6, "p2Games": 4},
                {"p1Games": 6, "p2Games": 3},
            ],
        },
    }

    # Persist final match state so JournalService can resolve match_id via MatchesRepo.
    db.collection("matches").document(match_id).set(after)

    # Simulate the Firestore onWrite trigger that maintains users/{uid}.completedMatches[].
    handle_match_write_migrate_on_completion(
        client=db,
        before=before,
        after=after,
        now=now,
    )
    return finished_at, after


def test_complete_match_populates_completed_matches_cache(db) -> None:
    home_uid = "cross_tab_home_cache"
    away_uid = "cross_tab_away_cache"
    match_id = "cross_tab_match_cache"
    _seed_user(db, home_uid)
    _seed_user(db, away_uid)

    finished_at, _ = _complete_match_and_run_cache_trigger(
        db,
        match_id=match_id,
        home_uid=home_uid,
        away_uid=away_uid,
    )

    home_doc = db.collection("users").document(home_uid).get().to_dict() or {}
    completed = home_doc.get("completedMatches") or []
    assert completed, "Expected completedMatches cache to have at least one item"

    first = completed[0]
    assert first["matchId"] == match_id
    assert first["sport"] == SportEnum.TENNIS.value
    assert first["finishedAt"] == finished_at
    assert first["result"] == MatchResultEnum.WIN.value
    assert first["scoreText"] == "6-4 6-3"


def test_create_journal_entry_referencing_completed_match_keeps_link(db) -> None:
    home_uid = "cross_tab_home_journal"
    away_uid = "cross_tab_away_journal"
    match_id = "cross_tab_match_journal"
    _seed_user(db, home_uid)
    _seed_user(db, away_uid)

    _complete_match_and_run_cache_trigger(
        db,
        match_id=match_id,
        home_uid=home_uid,
        away_uid=away_uid,
    )

    service = _make_journal_service(db)
    response = service.create_entry(
        home_uid,
        CreateJournalEntryRequest(
            entry_type=JournalEntryTypeEnum.MATCH,
            title="Post-match notes",
            body="Solid first serve and good net play.",
            match_id=match_id,
            sport=SportEnum.TENNIS,
        ),
    )

    entry = JournalRepo(db).get_entry(home_uid, response.entry_id)
    assert entry is not None
    assert entry.match_id == match_id
    assert entry.result == MatchResultEnum.WIN

    home_doc = db.collection("users").document(home_uid).get().to_dict() or {}
    journal_recent = home_doc.get("journalRecent") or []
    assert journal_recent, "Expected journalRecent cache to include the new entry"
    assert journal_recent[0]["entryId"] == response.entry_id
    assert journal_recent[0]["matchId"] == match_id


def test_completed_match_picker_shape_matches_quick_entry_needs(db) -> None:
    home_uid = "cross_tab_home_picker"
    away_uid = "cross_tab_away_picker"
    match_id = "cross_tab_match_picker"
    _seed_user(db, home_uid)
    _seed_user(db, away_uid)

    finished_at, _ = _complete_match_and_run_cache_trigger(
        db,
        match_id=match_id,
        home_uid=home_uid,
        away_uid=away_uid,
    )

    user_doc = db.collection("users").document(home_uid).get().to_dict() or {}
    completed_raw = user_doc.get("completedMatches") or []
    assert completed_raw, "Expected completedMatches cache item for quick-entry picker"

    picker_item_raw = completed_raw[0]
    assert set(picker_item_raw.keys()) >= {
        "matchId",
        "sport",
        "finishedAt",
        "result",
        "scoreText",
        "leagueId",
    }
    assert picker_item_raw["matchId"] == match_id
    assert picker_item_raw["finishedAt"] == finished_at
    assert picker_item_raw["result"] == MatchResultEnum.WIN.value
    assert picker_item_raw["scoreText"] == "6-4 6-3"

    # Also verify the mapped API-facing shape from UsersRepo/PrivateUserProfile.
    profile = UsersRepo(db).get_private_profile(home_uid)
    assert profile is not None
    assert profile.completed_matches, (
        "Expected mapped completed_matches in private profile"
    )
    picker_item = profile.completed_matches[0]
    assert picker_item.match_id == match_id
    assert picker_item.sport == SportEnum.TENNIS
    assert picker_item.finished_at == finished_at
    assert picker_item.result == MatchResultEnum.WIN
    assert picker_item.score_text == "6-4 6-3"
    assert picker_item.league_id == "league_cross_tab"
