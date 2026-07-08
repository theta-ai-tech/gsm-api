from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_league_service, get_leagues_repo
from app.deps import get_current_user
from app.main import app
from app.repos.leagues_repo import LeaguesRepo
from app.security import CurrentUser
from app.services.league_service import LeagueService
from app.utils.contact import partner_placeholder_uid

pytestmark = [pytest.mark.integration]

_LEAGUE_ID = "test-partner-invite-league"
_CAPTAIN = "pi-captain"
_INVITE_EMAIL = "Newbie@Example.com"
_INVITE_EMAIL_NORM = "newbie@example.com"
_CLAIMANT = "pi-claimant"


def _cleanup(db) -> None:
    league_ref = db.collection("leagues").document(_LEAGUE_ID)
    for sub in ("members", "teams", "divisions"):
        for doc in league_ref.collection(sub).stream():
            doc.reference.delete()
    league_ref.delete()
    for doc in db.collection("partnerInvites").stream():
        doc.reference.delete()
    for uid in (_CAPTAIN, _CLAIMANT):
        db.collection("users").document(uid).delete()


def _seed(db) -> None:
    db.collection("leagues").document(_LEAGUE_ID).set(
        {
            "name": "Partner Invite Doubles",
            "sport": "padel",
            "status": "open",
            "ownerUid": _CAPTAIN,
            "format": "doubles",
            "maxPlayers": 8,
            "currentPlayers": 0,
            "startDate": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "divisionConfig": {"targetSize": 6, "maxDivisions": None},
        }
    )
    db.collection("users").document(_CAPTAIN).set(
        {
            "uid": _CAPTAIN,
            "name": "Captain One",
            "email": "captain.one@example.com",
            "emailLower": "captain.one@example.com",
            "rankings": {"padel": {"pts": 1500}},
        }
    )


@pytest.fixture
def invite_client(db):
    _cleanup(db)
    _seed(db)
    app.dependency_overrides[get_leagues_repo] = lambda: LeaguesRepo(db)
    app.dependency_overrides[get_league_service] = lambda: LeagueService(
        LeaguesRepo(db), db
    )
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_CAPTAIN, email="captain.one@example.com", display_name="Captain One"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()
    _cleanup(db)


def test_invite_placeholder_team_active_and_hidden_email(invite_client, db):
    resp = invite_client.post(
        f"/leagues/{_LEAGUE_ID}/join",
        json={
            "partner_invite": {
                "name": "Newbie Nick",
                "email": _INVITE_EMAIL,
                "phone": "+30123",
            }
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Immediate ACTIVE team, no registered partner uid, email never surfaced.
    assert body["status"] == "active"
    assert body["partner_uid"] is None
    placeholder_uid = partner_placeholder_uid(_INVITE_EMAIL_NORM)
    assert body["partner_placeholder_uid"] == placeholder_uid
    assert body["partner_invite"] == {"name": "Newbie Nick", "phone": "+30123"}
    assert "email" not in body["partner_invite"]
    assert body["member_uids"] == [_CAPTAIN, placeholder_uid]

    # Capacity consumed (+2).
    league = db.collection("leagues").document(_LEAGUE_ID).get().to_dict()
    assert league["currentPlayers"] == 2

    # Placeholder + captain member docs exist.
    members = {
        d.id: d.to_dict()
        for d in db.collection("leagues")
        .document(_LEAGUE_ID)
        .collection("members")
        .stream()
    }
    assert set(members) == {_CAPTAIN, placeholder_uid}
    assert members[placeholder_uid]["displayName"] == "Newbie Nick"
    assert members[_CAPTAIN]["partnerUid"] == placeholder_uid

    # Lookup doc stores the normalized email (server-side only).
    lookup_id = f"{placeholder_uid}__{_LEAGUE_ID}"
    lookup = db.collection("partnerInvites").document(lookup_id).get().to_dict()
    assert lookup["emailNormalized"] == _INVITE_EMAIL_NORM
    assert lookup["captainUid"] == _CAPTAIN


def test_duplicate_email_same_league_conflicts(invite_client):
    payload = {"partner_invite": {"name": "Newbie Nick", "email": _INVITE_EMAIL}}
    first = invite_client.post(f"/leagues/{_LEAGUE_ID}/join", json=payload)
    assert first.status_code == 201, first.text
    second = invite_client.post(f"/leagues/{_LEAGUE_ID}/join", json=payload)
    assert second.status_code == 409, second.text


def test_self_email_rejected(invite_client):
    resp = invite_client.post(
        f"/leagues/{_LEAGUE_ID}/join",
        json={"partner_invite": {"name": "Me", "email": "captain.one@example.com"}},
    )
    assert resp.status_code == 400, resp.text


def test_registered_email_rejected(invite_client, db):
    db.collection("users").document(_CLAIMANT).set(
        {
            "uid": _CLAIMANT,
            "name": "Already Here",
            "email": _INVITE_EMAIL_NORM,
            "emailLower": _INVITE_EMAIL_NORM,
        }
    )
    resp = invite_client.post(
        f"/leagues/{_LEAGUE_ID}/join",
        json={"partner_invite": {"name": "Dup", "email": _INVITE_EMAIL}},
    )
    assert resp.status_code == 409, resp.text


def test_registered_email_rejected_case_insensitive(invite_client, db):
    # User doc as onboarding writes it: `email` keeps the user-entered casing,
    # `emailLower` is the normalized match key. The invite arrives with yet
    # another casing — the guard must still 409 instead of creating a
    # placeholder for an already-registered user.
    db.collection("users").document(_CLAIMANT).set(
        {
            "uid": _CLAIMANT,
            "name": "Already Here",
            "email": "NEWBIE@Example.COM",
            "emailLower": _INVITE_EMAIL_NORM,
        }
    )
    resp = invite_client.post(
        f"/leagues/{_LEAGUE_ID}/join",
        json={"partner_invite": {"name": "Dup", "email": _INVITE_EMAIL}},
    )
    assert resp.status_code == 409, resp.text


def test_xor_partner_uid_and_invite_rejected(invite_client):
    resp = invite_client.post(
        f"/leagues/{_LEAGUE_ID}/join",
        json={
            "partner_uid": "someone",
            "partner_invite": {"name": "Nick", "email": _INVITE_EMAIL},
        },
    )
    assert resp.status_code == 422, resp.text


def test_claim_on_registration_backfills_team(invite_client, db):
    # 1. Captain invites an unregistered partner.
    resp = invite_client.post(
        f"/leagues/{_LEAGUE_ID}/join",
        json={"partner_invite": {"name": "Newbie Nick", "email": _INVITE_EMAIL}},
    )
    assert resp.status_code == 201, resp.text
    team_id = resp.json()["team_id"]
    placeholder_uid = partner_placeholder_uid(_INVITE_EMAIL_NORM)

    # 2. The invited person registers with that email — claim runs.
    db.collection("users").document(_CLAIMANT).set(
        {"uid": _CLAIMANT, "name": "Real Nick", "email": _INVITE_EMAIL_NORM}
    )
    LeagueService(LeaguesRepo(db), db).claim_partner_invites(_CLAIMANT, _INVITE_EMAIL)

    # Team rewritten to the real uid; placeholder + invite PII gone.
    team = (
        db.collection("leagues")
        .document(_LEAGUE_ID)
        .collection("teams")
        .document(team_id)
        .get()
    )
    team_data = team.to_dict()
    assert team_data["partnerUid"] == _CLAIMANT
    assert team_data["memberUids"] == [_CAPTAIN, _CLAIMANT]
    assert "partnerInvite" not in team_data
    assert "partnerPlaceholderUid" not in team_data
    assert team_data["name"] == "Captain One / Real Nick"

    members = {
        d.id: d.to_dict()
        for d in db.collection("leagues")
        .document(_LEAGUE_ID)
        .collection("members")
        .stream()
    }
    assert placeholder_uid not in members
    assert _CLAIMANT in members
    assert members[_CLAIMANT]["teamId"] == team_id
    assert members[_CAPTAIN]["partnerUid"] == _CLAIMANT

    # Lookup consumed.
    lookup_id = f"{placeholder_uid}__{_LEAGUE_ID}"
    assert not db.collection("partnerInvites").document(lookup_id).get().exists

    # Idempotent re-run is a no-op.
    LeagueService(LeaguesRepo(db), db).claim_partner_invites(_CLAIMANT, _INVITE_EMAIL)
    team_again = (
        db.collection("leagues")
        .document(_LEAGUE_ID)
        .collection("teams")
        .document(team_id)
        .get()
        .to_dict()
    )
    assert team_again["partnerUid"] == _CLAIMANT


def test_kickoff_with_placeholder_team_uses_captain_rating(invite_client, db):
    resp = invite_client.post(
        f"/leagues/{_LEAGUE_ID}/join",
        json={"partner_invite": {"name": "Newbie Nick", "email": _INVITE_EMAIL}},
    )
    assert resp.status_code == 201, resp.text
    team_id = resp.json()["team_id"]

    svc = LeagueService(LeaguesRepo(db), db)
    result = svc.kickoff_league(_LEAGUE_ID)
    assert not result.already_kicked_off
    assert len(result.divisions) == 1
    # Captain-only mean == captain pts (placeholder skipped, not averaged to 0).
    assert result.divisions[0].rating_range.min == 1500

    team = (
        db.collection("leagues")
        .document(_LEAGUE_ID)
        .collection("teams")
        .document(team_id)
        .get()
        .to_dict()
    )
    assert team["divisionId"] == "div-1"
