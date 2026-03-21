from datetime import datetime, timezone

from app.models.scouting import ScoutingProfile
from app.repos.mappers import to_scouting_profile


class TestToScoutingProfile:
    def test_complete_doc(self):
        now = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        doc = {
            "uid": "user_bob",
            "tennis": {
                "weak": {
                    "backhand": {"count": 7, "lastReported": now},
                    "stamina_set3": {"count": 3, "lastReported": now},
                },
                "strong": {
                    "first_serve": {"count": 5, "lastReported": now},
                },
                "totalReports": 12,
                "uniqueReporters": 8,
                "lastUpdated": now,
            },
            "padel": {
                "weak": {},
                "strong": {"net_approach": {"count": 2, "lastReported": now}},
                "totalReports": 2,
                "uniqueReporters": 2,
                "lastUpdated": now,
            },
        }

        profile = to_scouting_profile(doc)

        assert isinstance(profile, ScoutingProfile)
        assert profile.uid == "user_bob"
        assert profile.tennis is not None
        assert profile.tennis.total_reports == 12
        assert profile.tennis.unique_reporters == 8
        assert profile.tennis.weak["backhand"].count == 7
        assert profile.tennis.weak["stamina_set3"].count == 3
        assert profile.tennis.strong["first_serve"].count == 5
        assert profile.padel is not None
        assert profile.padel.total_reports == 2
        assert profile.padel.strong["net_approach"].count == 2
        assert profile.pickleball is None

    def test_empty_doc(self):
        doc = {"uid": "user_nobody"}
        profile = to_scouting_profile(doc)
        assert profile.uid == "user_nobody"
        assert profile.tennis is None
        assert profile.padel is None
        assert profile.pickleball is None

    def test_uid_from_id_field(self):
        doc = {"id": "user_fallback"}
        profile = to_scouting_profile(doc)
        assert profile.uid == "user_fallback"

    def test_ignores_non_dict_tag_entries(self):
        doc = {
            "uid": "user_x",
            "tennis": {
                "weak": {
                    "backhand": {"count": 3, "lastReported": "2026-03-01T10:00:00Z"},
                    "bad_entry": "not_a_dict",
                },
                "strong": {},
                "totalReports": 3,
                "uniqueReporters": 2,
            },
        }
        profile = to_scouting_profile(doc)
        assert profile.tennis is not None
        assert "backhand" in profile.tennis.weak
        assert "bad_entry" not in profile.tennis.weak
