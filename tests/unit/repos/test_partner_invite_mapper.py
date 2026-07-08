from __future__ import annotations

from datetime import datetime, timezone

from app.repos.mappers import to_league_team


def test_to_league_team_placeholder_null_partner_and_invite_hidden_email():
    doc = {
        "status": "active",
        "captainUid": "cap",
        "partnerUid": None,
        "partnerPlaceholderUid": "invite:abc123",
        "partnerInvite": {
            "name": "Newbie Nick",
            "emailNormalized": "nick@example.com",
            "phone": "+30123",
            "invitedAt": datetime(2026, 6, 1, tzinfo=timezone.utc),
        },
        "memberUids": ["cap", "invite:abc123"],
        "name": "Captain / Newbie Nick",
        "createdAt": datetime(2026, 6, 1, tzinfo=timezone.utc),
    }
    team = to_league_team(doc, team_id="t1")

    assert team.partner_uid is None
    assert team.partner_placeholder_uid == "invite:abc123"
    assert team.partner_invite is not None
    assert team.partner_invite.name == "Newbie Nick"
    assert team.partner_invite.phone == "+30123"
    # Email must never surface on the model.
    assert not hasattr(team.partner_invite, "email")
    dumped = team.partner_invite.model_dump()
    assert "email" not in dumped
    assert "emailNormalized" not in dumped


def test_to_league_team_registered_team_has_no_invite():
    doc = {
        "status": "active",
        "captainUid": "cap",
        "partnerUid": "partner",
        "memberUids": ["cap", "partner"],
        "name": "Captain / Partner",
        "createdAt": datetime(2026, 6, 1, tzinfo=timezone.utc),
    }
    team = to_league_team(doc, team_id="t1")
    assert team.partner_uid == "partner"
    assert team.partner_invite is None
    assert team.partner_placeholder_uid is None
