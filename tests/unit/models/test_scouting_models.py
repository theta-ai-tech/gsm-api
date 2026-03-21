from datetime import datetime, timezone

from app.models.scouting import ScoutingProfile, ScoutingSportData, ScoutingTagCount


class TestScoutingTagCount:
    def test_defaults(self):
        tc = ScoutingTagCount()
        assert tc.count == 0
        assert tc.last_reported is None

    def test_with_values(self):
        now = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        tc = ScoutingTagCount(count=7, last_reported=now)
        assert tc.count == 7
        assert tc.last_reported == now


class TestScoutingSportData:
    def test_defaults(self):
        sd = ScoutingSportData()
        assert sd.weak == {}
        assert sd.strong == {}
        assert sd.total_reports == 0
        assert sd.unique_reporters == 0
        assert sd.last_updated is None

    def test_with_tags(self):
        now = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        sd = ScoutingSportData(
            weak={"backhand": ScoutingTagCount(count=7, last_reported=now)},
            strong={"first_serve": ScoutingTagCount(count=5, last_reported=now)},
            total_reports=12,
            unique_reporters=8,
            last_updated=now,
        )
        assert sd.weak["backhand"].count == 7
        assert sd.strong["first_serve"].count == 5
        assert sd.total_reports == 12
        assert sd.unique_reporters == 8


class TestScoutingProfile:
    def test_minimal(self):
        sp = ScoutingProfile(uid="user_bob")
        assert sp.uid == "user_bob"
        assert sp.tennis is None
        assert sp.padel is None
        assert sp.pickleball is None

    def test_with_sport_data(self):
        sd = ScoutingSportData(total_reports=5, unique_reporters=3)
        sp = ScoutingProfile(uid="user_bob", tennis=sd)
        assert sp.tennis is not None
        assert sp.tennis.total_reports == 5
        assert sp.padel is None
