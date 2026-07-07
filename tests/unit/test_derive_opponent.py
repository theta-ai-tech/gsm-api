from functions.match_triggers.upcoming_cache import derive_opponent


def test_singles_returns_other_participant_with_name() -> None:
    participants = [
        {"uid": "me", "team": None, "displayName": "Me"},
        {"uid": "rival", "team": None, "displayName": "Rival"},
    ]

    assert derive_opponent(participants, ["me", "rival"], "me") == ("rival", "Rival")


def test_doubles_returns_first_opponent_on_other_team() -> None:
    participants = [
        {"uid": "me", "team": "A", "displayName": "Me"},
        {"uid": "partner", "team": "A", "displayName": "Partner"},
        {"uid": "opp1", "team": "B", "displayName": "Opp One"},
        {"uid": "opp2", "team": "B", "displayName": "Opp Two"},
    ]

    assert derive_opponent(participants, ["me", "partner", "opp1", "opp2"], "me") == (
        "opp1",
        "Opp One",
    )


def test_missing_display_name_returns_none_name() -> None:
    participants = [
        {"uid": "me", "team": None},
        {"uid": "rival", "team": None},
    ]

    assert derive_opponent(participants, ["me", "rival"], "me") == ("rival", None)


def test_falls_back_to_participant_uids_when_participants_empty() -> None:
    assert derive_opponent(None, ["me", "rival"], "me") == ("rival", None)
    assert derive_opponent([], ["me", "rival"], "me") == ("rival", None)


def test_no_opponent_returns_none_pair() -> None:
    participants = [{"uid": "me", "team": None, "displayName": "Me"}]

    assert derive_opponent(participants, ["me"], "me") == (None, None)
