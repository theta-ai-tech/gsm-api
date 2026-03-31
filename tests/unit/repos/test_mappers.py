from datetime import datetime, timedelta, timezone


from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    CourtStatusEnum,
    JournalEntryTypeEnum,
    JournalVisibilityEnum,
    MatchResultEnum,
    OfferStatusEnum,
    SportEnum,
    TrainingFocusEnum,
)
from app.repos.mappers import (
    _parse_broadcast_location,
    _parse_geo_location,
    _parse_journal_entry_summary,
    _parse_sport_ranking,
    to_broadcast,
    to_journal_entry,
    to_offer,
)
from app.models.journal import JournalEntry, MatchReflection
from tools.seed_mapping import journal_entry_to_firestore_doc


class TestToBroadcast:
    def test_to_broadcast_complete(self):
        """Maps all fields correctly including nested location and ownerRanking"""
        now = datetime.now(timezone.utc)
        doc = {
            "ownerUid": "user123",
            "ownerName": "Alice",
            "ownerRanking": {"sport": "tennis", "pts": 1200, "globalRanking": 42},
            "sport": "tennis",
            "availability": "today",
            "courtStatus": "have_court",
            "courtLocation": "Central Park",
            "status": "active",
            "expiresAt": now + timedelta(hours=2),
            "createdAt": now,
            "location": {
                "area": 10001,
                "geo": {"lat": 40.7128, "lng": -74.0060},
                "radiusKm": 5.0,
            },
        }

        broadcast = to_broadcast(doc, broadcast_id="broadcast123")

        assert broadcast.broadcast_id == "broadcast123"
        assert broadcast.owner_uid == "user123"
        assert broadcast.owner_name == "Alice"
        assert broadcast.owner_ranking is not None
        assert broadcast.owner_ranking.sport == SportEnum.TENNIS
        assert broadcast.owner_ranking.pts == 1200
        assert broadcast.owner_ranking.global_ranking == 42
        assert broadcast.sport == SportEnum.TENNIS
        assert broadcast.availability == AvailabilityEnum.TODAY
        assert broadcast.court_status == CourtStatusEnum.HAVE_COURT
        assert broadcast.court_location == "Central Park"
        assert broadcast.status == BroadcastStatusEnum.ACTIVE
        assert broadcast.location.area == 10001
        assert broadcast.location.geo.lat == 40.7128
        assert broadcast.location.geo.lng == -74.0060
        assert broadcast.location.radius_km == 5.0

    def test_to_broadcast_minimal(self):
        """Handles minimal doc with required fields only"""
        now = datetime.now(timezone.utc)
        doc = {
            "ownerUid": "user123",
            "sport": "tennis",
            "availability": "today",
            "courtStatus": "need_court",
            "status": "active",
            "expiresAt": now + timedelta(hours=2),
            "createdAt": now,
            "location": {},
        }

        broadcast = to_broadcast(doc, broadcast_id="broadcast123")

        assert broadcast.broadcast_id == "broadcast123"
        assert broadcast.owner_uid == "user123"
        assert broadcast.owner_name == ""
        assert broadcast.owner_ranking is None
        assert broadcast.court_location is None
        assert broadcast.location.area is None
        assert broadcast.location.geo is None
        assert broadcast.location.radius_km is None


class TestToOffer:
    def test_to_offer_complete(self):
        """Maps all offer fields including rankings"""
        now = datetime.now(timezone.utc)
        doc = {
            "fromUid": "alice",
            "fromName": "Alice",
            "fromRanking": {"sport": "tennis", "pts": 1200, "globalRanking": 42},
            "toUid": "bob",
            "toName": "Bob",
            "toRanking": {"sport": "tennis", "pts": 1100, "globalRanking": 50},
            "sport": "tennis",
            "proposedTime": now + timedelta(hours=2),
            "courtLocation": "Central Park",
            "message": "Let's play!",
            "status": "pending",
            "expiresAt": now + timedelta(minutes=5),
            "createdAt": now,
            "matchId": None,
        }

        offer = to_offer(doc, offer_id="offer123")

        assert offer.offer_id == "offer123"
        assert offer.from_uid == "alice"
        assert offer.from_name == "Alice"
        assert offer.from_ranking.sport == SportEnum.TENNIS
        assert offer.from_ranking.pts == 1200
        assert offer.to_uid == "bob"
        assert offer.to_name == "Bob"
        assert offer.to_ranking.sport == SportEnum.TENNIS
        assert offer.to_ranking.pts == 1100
        assert offer.sport == SportEnum.TENNIS
        assert offer.court_location == "Central Park"
        assert offer.message == "Let's play!"
        assert offer.status == OfferStatusEnum.PENDING
        assert offer.match_id is None

    def test_to_offer_no_rankings(self):
        """Rankings can be None"""
        now = datetime.now(timezone.utc)
        doc = {
            "fromUid": "alice",
            "toUid": "bob",
            "sport": "tennis",
            "proposedTime": now + timedelta(hours=2),
            "status": "pending",
            "expiresAt": now + timedelta(minutes=5),
            "createdAt": now,
        }

        offer = to_offer(doc, offer_id="offer123")

        assert offer.from_ranking is None
        assert offer.to_ranking is None
        assert offer.from_name == ""
        assert offer.to_name == ""


class TestParseGeoLocation:
    def test_parse_geo_location_none(self):
        """Returns None when data is None"""
        result = _parse_geo_location(None)
        assert result is None

    def test_parse_geo_location_valid(self):
        """Parses lat/lng correctly"""
        data = {"lat": 40.7128, "lng": -74.0060}
        result = _parse_geo_location(data)

        assert result is not None
        assert result.lat == 40.7128
        assert result.lng == -74.0060


class TestParseBroadcastLocation:
    def test_parse_broadcast_location_area_only(self):
        """area set, geo=None, radiusKm=None"""
        data = {"area": 10001}
        result = _parse_broadcast_location(data)

        assert result.area == 10001
        assert result.geo is None
        assert result.radius_km is None

    def test_parse_broadcast_location_geo_only(self):
        """geo set, area=None, radiusKm set"""
        data = {"geo": {"lat": 40.7128, "lng": -74.0060}, "radiusKm": 5.0}
        result = _parse_broadcast_location(data)

        assert result.area is None
        assert result.geo is not None
        assert result.geo.lat == 40.7128
        assert result.geo.lng == -74.0060
        assert result.radius_km == 5.0

    def test_parse_broadcast_location_hybrid(self):
        """Both area and geo set (hybrid model)"""
        data = {
            "area": 10001,
            "geo": {"lat": 40.7128, "lng": -74.0060},
            "radiusKm": 5.0,
        }
        result = _parse_broadcast_location(data)

        assert result.area == 10001
        assert result.geo is not None
        assert result.geo.lat == 40.7128
        assert result.geo.lng == -74.0060
        assert result.radius_km == 5.0

    def test_parse_broadcast_location_empty(self):
        """Empty location dict"""
        data = {}
        result = _parse_broadcast_location(data)

        assert result.area is None
        assert result.geo is None
        assert result.radius_km is None


# ── to_journal_entry ──────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc)


def _base_entry_doc(**overrides) -> dict:
    """Minimal valid Firestore journal entry document."""
    doc = {
        "uid": "user1",
        "createdAt": NOW,
        "title": "Match notes",
        "body": "Good game",
        "visibility": "private",
    }
    doc.update(overrides)
    return doc


class TestToJournalEntry:
    def test_maps_entry_type_correctly(self):
        """entryType='training' is parsed to JournalEntryTypeEnum.TRAINING."""
        doc = _base_entry_doc(entryType="training", durationMinutes=60)

        entry = to_journal_entry(doc, entry_id="e1", uid="user1")

        assert entry.entry_type == JournalEntryTypeEnum.TRAINING
        assert entry.duration_minutes == 60

    def test_defaults_entry_type_to_match_when_absent(self):
        """Missing entryType defaults to JournalEntryTypeEnum.MATCH."""
        doc = _base_entry_doc()  # no entryType key

        entry = to_journal_entry(doc, entry_id="e1", uid="user1")

        assert entry.entry_type == JournalEntryTypeEnum.MATCH

    def test_maps_training_focus_list(self):
        """trainingFocus string list is parsed to list[TrainingFocusEnum]."""
        doc = _base_entry_doc(
            entryType="training",
            durationMinutes=45,
            trainingFocus=["serve", "footwork"],
        )

        entry = to_journal_entry(doc, entry_id="e1", uid="user1")

        assert entry.training_focus == [
            TrainingFocusEnum.SERVE,
            TrainingFocusEnum.FOOTWORK,
        ]

    def test_maps_nested_reflection_object(self):
        """reflection dict is parsed to a MatchReflection model."""
        doc = _base_entry_doc(
            reflection={
                "wentWell": ["first_serve", "net_play"],
                "wentWrong": ["double_faults"],
                "opponentWeak": ["backhand"],
                "opponentStrong": ["serve"],
                "aiSummary": None,
                "reflectionVersion": "v1",
            }
        )

        entry = to_journal_entry(doc, entry_id="e1", uid="user1")

        assert entry.reflection is not None
        assert entry.reflection.went_well == ["first_serve", "net_play"]
        assert entry.reflection.went_wrong == ["double_faults"]
        assert entry.reflection.opponent_weak == ["backhand"]
        assert entry.reflection.opponent_strong == ["serve"]
        assert entry.reflection.ai_summary is None
        assert entry.reflection.reflection_version == "v1"

    def test_backward_compat_missing_new_fields(self):
        """Old doc without new fields deserialises with correct defaults."""
        doc = _base_entry_doc()  # no entryType, trainingFocus, reflection, etc.

        entry = to_journal_entry(doc, entry_id="e1", uid="user1")

        assert entry.entry_type == JournalEntryTypeEnum.MATCH
        assert entry.training_focus == []
        assert entry.reflection is None
        assert entry.duration_minutes is None
        assert entry.score_text is None
        assert entry.result is None
        assert entry.client_request_id is None
        assert entry.is_deleted is False
        assert entry.deleted_at is None

    def test_maps_result_and_score_text(self):
        """result and scoreText are parsed correctly."""
        doc = _base_entry_doc(result="W", scoreText="6-4 7-5")

        entry = to_journal_entry(doc, entry_id="e1", uid="user1")

        assert entry.result == MatchResultEnum.WIN
        assert entry.score_text == "6-4 7-5"


# ── _parse_journal_entry_summary ──────────────────────────────────────────────


class TestParseJournalEntrySummary:
    def test_includes_entry_type(self):
        """entryType is parsed and exposed on JournalEntrySummary."""
        data = {
            "entryId": "e1",
            "createdAt": NOW,
            "title": "Training session",
            "entryType": "training",
        }

        summary = _parse_journal_entry_summary(data)

        assert summary.entry_id == "e1"
        assert summary.entry_type == JournalEntryTypeEnum.TRAINING

    def test_entry_type_none_when_absent(self):
        """Missing entryType results in entry_type=None (not MATCH default)."""
        data = {
            "entryId": "e2",
            "createdAt": NOW,
            "title": "Old entry",
        }

        summary = _parse_journal_entry_summary(data)

        assert summary.entry_type is None


# ── journal_entry_to_firestore_doc ────────────────────────────────────────────


class TestJournalEntryToFirestoreDoc:
    def test_serializes_new_fields_to_camel_case(self):
        """All new DM-01 fields appear in the Firestore dict with camelCase keys."""
        entry = JournalEntry(
            entry_id="e1",
            uid="user1",
            created_at=NOW,
            title="Training day",
            body="Hard session",
            visibility=JournalVisibilityEnum.PRIVATE,
            entry_type=JournalEntryTypeEnum.TRAINING,
            duration_minutes=90,
            training_focus=[TrainingFocusEnum.SERVE, TrainingFocusEnum.CARDIO],
            reflection=MatchReflection(
                went_well=["serve"],
                went_wrong=["footwork"],
                reflection_version="v1",
            ),
            score_text=None,
            result=None,
            client_request_id="req_123",
            is_deleted=False,
            deleted_at=None,
        )

        doc = journal_entry_to_firestore_doc(entry)

        assert doc["entryType"] == "training"
        assert doc["durationMinutes"] == 90
        assert doc["trainingFocus"] == ["serve", "cardio"]
        assert doc["reflection"] == {
            "wentWell": ["serve"],
            "wentWrong": ["footwork"],
            "opponentWeak": [],
            "opponentStrong": [],
            "aiSummary": None,
            "reflectionVersion": "v1",
        }
        assert doc["scoreText"] is None
        assert doc["result"] is None
        assert doc["clientRequestId"] == "req_123"
        assert doc["isDeleted"] is False
        assert doc["deletedAt"] is None
        # Legacy fields still present
        assert doc["title"] == "Training day"
        assert doc["visibility"] == "private"

    def test_reflection_none_serializes_as_none(self):
        """When reflection is None, the Firestore dict has reflection: None."""
        entry = JournalEntry(
            entry_id="e2",
            uid="user1",
            created_at=NOW,
            title="Quick match",
            body="",
            visibility=JournalVisibilityEnum.PRIVATE,
        )

        doc = journal_entry_to_firestore_doc(entry)

        assert doc["reflection"] is None
        assert doc["trainingFocus"] == []


# ── _parse_sport_ranking (personal_best) ─────────────────────────────────────


class TestParseSportRankingPersonalBest:
    def test_personal_best_parsed_from_firestore(self):
        """personalBest in Firestore doc maps to personal_best on the model."""
        data = {"sport": "tennis", "pts": 1200, "personalBest": 1350}

        ranking = _parse_sport_ranking(data)

        assert ranking is not None
        assert ranking.personal_best == 1350

    def test_personal_best_none_when_absent(self):
        """Legacy docs without personalBest default to None."""
        data = {"sport": "tennis", "pts": 1000}

        ranking = _parse_sport_ranking(data)

        assert ranking is not None
        assert ranking.personal_best is None

    def test_personal_best_none_when_explicitly_null(self):
        """Explicitly null personalBest maps to None."""
        data = {"sport": "padel", "pts": 800, "personalBest": None}

        ranking = _parse_sport_ranking(data)

        assert ranking is not None
        assert ranking.personal_best is None

    def test_sport_ranking_model_default(self):
        """SportRanking model defaults personal_best to None."""
        from app.models.common import SportRanking

        ranking = SportRanking(sport=SportEnum.TENNIS, pts=1000)

        assert ranking.personal_best is None


# ── _parse_sport_ranking (currentStreak, bestStreak) ─────────────────────────


class TestParseSportRankingStreaks:
    def test_streaks_parsed_from_firestore(self):
        """currentStreak and bestStreak in Firestore doc map to model fields."""
        data = {"sport": "tennis", "pts": 1200, "currentStreak": 5, "bestStreak": 8}

        ranking = _parse_sport_ranking(data)

        assert ranking is not None
        assert ranking.current_streak == 5
        assert ranking.best_streak == 8

    def test_streaks_default_to_zero_when_absent(self):
        """Legacy docs without streak fields default to 0."""
        data = {"sport": "tennis", "pts": 1000}

        ranking = _parse_sport_ranking(data)

        assert ranking is not None
        assert ranking.current_streak == 0
        assert ranking.best_streak == 0

    def test_streaks_zero_when_explicitly_zero(self):
        """Explicitly zero streak values are preserved."""
        data = {"sport": "padel", "pts": 800, "currentStreak": 0, "bestStreak": 0}

        ranking = _parse_sport_ranking(data)

        assert ranking is not None
        assert ranking.current_streak == 0
        assert ranking.best_streak == 0

    def test_streaks_default_to_zero_when_explicitly_null(self):
        """Explicit null in Firestore doesn't raise TypeError — defaults to 0."""
        data = {
            "sport": "tennis",
            "pts": 900,
            "currentStreak": None,
            "bestStreak": None,
        }

        result = _parse_sport_ranking(data)

        assert result.current_streak == 0
        assert result.best_streak == 0

    def test_sport_ranking_model_streak_defaults(self):
        """SportRanking model defaults current_streak and best_streak to 0."""
        from app.models.common import SportRanking

        ranking = SportRanking(sport=SportEnum.TENNIS, pts=1000)

        assert ranking.current_streak == 0
        assert ranking.best_streak == 0
