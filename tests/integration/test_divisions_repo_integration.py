from __future__ import annotations

import pytest

from app.models import Division, RatingRange
from app.models.enums import LeagueStatusEnum
from app.repos.divisions_repo import DivisionsRepo
from app.repos.leagues_repo import LeaguesRepo

pytestmark = [pytest.mark.integration]

_LEAGUE_ID = "ldiv1_divisions_repo_integration"
_MEMBER_UID = "ldiv1_member"


@pytest.fixture(autouse=True)
def _cleanup(db):
    league_ref = db.collection("leagues").document(_LEAGUE_ID)
    yield
    for doc in league_ref.collection("divisions").stream():
        doc.reference.delete()
    for doc in league_ref.collection("members").stream():
        doc.reference.delete()
    league_ref.delete()


def test_division_schema_foundations_round_trip(db):
    leagues_repo = LeaguesRepo(db)
    divisions_repo = DivisionsRepo(db)
    league_ref = db.collection("leagues").document(_LEAGUE_ID)
    league_ref.set(
        {
            "name": "LDIV Integration League",
            "sport": "padel",
            "status": "open",
            "ownerUid": "owner_1",
            "divisionConfig": {"targetSize": 6, "maxDivisions": 2},
        }
    )
    league_ref.collection("members").document(_MEMBER_UID).set(
        {
            "role": "player",
            "status": "active",
            "joinedAt": "2030-01-01T00:00:00Z",
            "divisionId": "div-1",
        }
    )

    divisions_repo.create_division(
        _LEAGUE_ID,
        Division(
            division_id="div-2",
            name="Division 2",
            ordinal=2,
            rating_range=RatingRange(min=700, max=900),
            current_players=5,
            status=LeagueStatusEnum.ACTIVE,
        ),
    )
    divisions_repo.create_division(
        _LEAGUE_ID,
        Division(
            division_id="div-1",
            name="Division 1",
            ordinal=1,
            rating_range=RatingRange(min=901, max=1200),
            current_players=6,
            status=LeagueStatusEnum.ACTIVE,
        ),
    )

    league = leagues_repo.get_by_id(_LEAGUE_ID)
    member = leagues_repo.get_member(_LEAGUE_ID, _MEMBER_UID)
    divisions = divisions_repo.list_for_league(_LEAGUE_ID)
    missing_division = divisions_repo.get_by_id(_LEAGUE_ID, "missing")

    assert league is not None
    assert league.division_config is not None
    assert league.division_config.target_size == 6
    assert league.division_config.max_divisions == 2
    assert member is not None
    assert member.division_id == "div-1"
    assert [division.division_id for division in divisions] == ["div-1", "div-2"]
    assert divisions[0].rating_range.min == 901
    assert divisions[0].current_players == 6
    assert missing_division is None
