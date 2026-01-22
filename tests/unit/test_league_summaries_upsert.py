from functions.league_triggers.on_league_member_write import upsert_league_summary


def test_upsert_into_empty_list() -> None:
    summary = {
        "leagueId": "l1",
        "name": "League 1",
        "sport": "padel",
        "status": "active",
        "role": "player",
    }

    updated = upsert_league_summary([], summary, cap=20)

    assert len(updated) == 1
    assert updated[0]["leagueId"] == "l1"


def test_upsert_same_league_twice_updates_entry() -> None:
    first = {
        "leagueId": "l1",
        "name": "League 1",
        "sport": "padel",
        "status": "active",
        "role": "player",
    }
    second = {**first, "role": "captain"}

    updated = upsert_league_summary([first], second, cap=20)

    assert len(updated) == 1
    assert updated[0]["role"] == "captain"


def test_role_change_reflected() -> None:
    summary = {
        "leagueId": "l1",
        "name": "League 1",
        "sport": "padel",
        "status": "active",
        "role": "player",
    }
    updated = upsert_league_summary([summary], {**summary, "role": "admin"}, cap=20)

    assert updated[0]["role"] == "admin"


def test_upsert_caps_at_twenty_and_drops_non_active_first() -> None:
    active = [
        {
            "leagueId": f"a{i}",
            "name": f"Active {i}",
            "sport": "padel",
            "status": "active",
            "role": "player",
        }
        for i in range(1, 11)
    ]
    inactive = [
        {
            "leagueId": f"c{i}",
            "name": f"Completed {i}",
            "sport": "padel",
            "status": "completed",
            "role": "player",
        }
        for i in range(1, 11)
    ]
    existing = active + inactive
    new_summary = {
        "leagueId": "a11",
        "name": "Active 11",
        "sport": "padel",
        "status": "active",
        "role": "player",
    }

    updated = upsert_league_summary(existing, new_summary, cap=20)

    assert len(updated) == 20
    assert any(item["leagueId"] == "a11" for item in updated)
    inactive_ids = {item["leagueId"] for item in updated if item["status"] != "active"}
    assert inactive_ids == {f"c{i}" for i in range(1, 10)}
