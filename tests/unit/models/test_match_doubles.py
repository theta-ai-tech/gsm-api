"""Unit tests for DBL-2: Match model doubles support and on-read defaults."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import (
    Match,
    MatchParticipant,
    MatchStatusEnum,
    MatchTypeEnum,
    SportEnum,
)
from app.models.enums import ParticipantRoleEnum
from app.repos.mappers import to_match


def _player(uid: str, team: str | None = None) -> MatchParticipant:
    return MatchParticipant(uid=uid, team=team, role=ParticipantRoleEnum.PLAYER)


class TestSinglesValidation:
    def test_singles_with_two_team_none_participants_is_valid(self) -> None:
        match = Match(
            match_id="m1",
            sport=SportEnum.TENNIS,
            status=MatchStatusEnum.SCHEDULED,
            participants=[_player("u1"), _player("u2")],
            participant_uids=["u1", "u2"],
        )
        assert match.match_type == MatchTypeEnum.SINGLES
        assert match.result_submitted_by == []

    def test_singles_with_three_participants_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly 2 participants"):
            Match(
                match_id="m1",
                sport=SportEnum.TENNIS,
                status=MatchStatusEnum.SCHEDULED,
                match_type=MatchTypeEnum.SINGLES,
                participants=[_player("u1"), _player("u2"), _player("u3")],
                participant_uids=["u1", "u2", "u3"],
            )

    def test_singles_with_team_set_rejected(self) -> None:
        with pytest.raises(ValidationError, match="team=None"):
            Match(
                match_id="m1",
                sport=SportEnum.TENNIS,
                status=MatchStatusEnum.SCHEDULED,
                match_type=MatchTypeEnum.SINGLES,
                participants=[_player("u1", team="A"), _player("u2")],
                participant_uids=["u1", "u2"],
            )


class TestDoublesValidation:
    def test_doubles_with_four_participants_two_per_team_is_valid(self) -> None:
        match = Match(
            match_id="m1",
            sport=SportEnum.PADEL,
            status=MatchStatusEnum.SCHEDULED,
            match_type=MatchTypeEnum.DOUBLES,
            participants=[
                _player("u1", team="A"),
                _player("u2", team="A"),
                _player("u3", team="B"),
                _player("u4", team="B"),
            ],
            participant_uids=["u1", "u2", "u3", "u4"],
        )
        assert match.match_type == MatchTypeEnum.DOUBLES
        assert [p.team for p in match.participants] == ["A", "A", "B", "B"]

    def test_doubles_with_three_participants_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly 4 participants"):
            Match(
                match_id="m1",
                sport=SportEnum.PADEL,
                status=MatchStatusEnum.SCHEDULED,
                match_type=MatchTypeEnum.DOUBLES,
                participants=[
                    _player("u1", team="A"),
                    _player("u2", team="A"),
                    _player("u3", team="B"),
                ],
                participant_uids=["u1", "u2", "u3"],
            )

    def test_doubles_with_uneven_team_distribution_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly 2 participants per team"):
            Match(
                match_id="m1",
                sport=SportEnum.PADEL,
                status=MatchStatusEnum.SCHEDULED,
                match_type=MatchTypeEnum.DOUBLES,
                participants=[
                    _player("u1", team="A"),
                    _player("u2", team="A"),
                    _player("u3", team="A"),
                    _player("u4", team="B"),
                ],
                participant_uids=["u1", "u2", "u3", "u4"],
            )

    def test_doubles_with_missing_team_assignment_rejected(self) -> None:
        with pytest.raises(ValidationError, match="team set to 'A' or 'B'"):
            Match(
                match_id="m1",
                sport=SportEnum.PADEL,
                status=MatchStatusEnum.SCHEDULED,
                match_type=MatchTypeEnum.DOUBLES,
                participants=[
                    _player("u1", team="A"),
                    _player("u2", team="A"),
                    _player("u3", team="B"),
                    _player("u4"),  # team=None
                ],
                participant_uids=["u1", "u2", "u3", "u4"],
            )

    def test_match_participant_invalid_team_value_rejected(self) -> None:
        with pytest.raises(ValidationError, match="team must be 'A', 'B', or None"):
            MatchParticipant(uid="u1", role=ParticipantRoleEnum.PLAYER, team="C")


class TestComputeOnReadDefaults:
    def test_legacy_doc_without_match_type_defaults_to_singles(self) -> None:
        doc = {
            "sport": "tennis",
            "status": "scheduled",
            "participantUids": ["u1", "u2"],
            "participants": [
                {"uid": "u1", "role": "player", "team": None},
                {"uid": "u2", "role": "player", "team": None},
            ],
        }
        match = to_match(doc, match_id="m_legacy")
        assert match.match_type == MatchTypeEnum.SINGLES
        assert match.result_submitted_by == []

    def test_legacy_doc_without_participants_array_is_built_from_uids(self) -> None:
        doc = {
            "sport": "tennis",
            "status": "scheduled",
            "participantUids": ["u1", "u2"],
        }
        match = to_match(doc, match_id="m_legacy")
        assert match.match_type == MatchTypeEnum.SINGLES
        assert len(match.participants) == 2
        assert {p.uid for p in match.participants} == {"u1", "u2"}
        assert all(p.team is None for p in match.participants)
        assert all(p.role == ParticipantRoleEnum.PLAYER for p in match.participants)

    def test_match_participant_coerces_legacy_int_team(self) -> None:
        # MatchParticipant alone (without doc context) coerces ints to A/B.
        m1 = MatchParticipant(uid="u1", team=1, role=ParticipantRoleEnum.PLAYER)
        assert m1.team == "A"
        m2 = MatchParticipant(uid="u2", team=2, role=ParticipantRoleEnum.PLAYER)
        assert m2.team == "B"

    def test_legacy_singles_doc_with_int_team_labels_normalizes_to_none(self) -> None:
        # Legacy seed data wrote team=1/team=2 onto singles matches. Without
        # a ``matchType`` field, the mapper treats the doc as singles and
        # clears the (meaningless) team labels so the singles validator
        # passes.
        doc = {
            "sport": "tennis",
            "status": "scheduled",
            "participantUids": ["u1", "u2"],
            "participants": [
                {"uid": "u1", "role": "player", "team": 1},
                {"uid": "u2", "role": "player", "team": 2},
            ],
        }
        match = to_match(doc, match_id="m_legacy")
        assert match.match_type == MatchTypeEnum.SINGLES
        assert [p.team for p in match.participants] == [None, None]

    def test_doubles_doc_round_trips(self) -> None:
        doc = {
            "sport": "padel",
            "status": "completed",
            "matchType": "doubles",
            "participantUids": ["u1", "u2", "u3", "u4"],
            "participants": [
                {"uid": "u1", "role": "player", "team": "A"},
                {"uid": "u2", "role": "player", "team": "A"},
                {"uid": "u3", "role": "player", "team": "B"},
                {"uid": "u4", "role": "player", "team": "B"},
            ],
            "resultSubmittedBy": ["u1", "u3"],
        }
        match = to_match(doc, match_id="m_doubles")
        assert match.match_type == MatchTypeEnum.DOUBLES
        assert match.result_submitted_by == ["u1", "u3"]
        assert len(match.participants) == 4
