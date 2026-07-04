from datetime import datetime, timedelta, timezone


from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    BroadcastTypeEnum,
    CourtStatusEnum,
    JournalEntryTypeEnum,
    JournalVisibilityEnum,
    LeagueStatusEnum,
    MatchResultEnum,
    MatchTypeEnum,
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
    to_division,
    to_journal_entry,
    to_league,
    to_league_browse_card,
    to_league_member,
    to_match,
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

    def test_to_broadcast_legacy_doc_defaults_doubles_fields(self):
        """Pre-DBL-3 documents (no matchType/broadcastType/partnerUid) default to
        singles + find_opponent + None partner."""
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

        broadcast = to_broadcast(doc, broadcast_id="broadcast_legacy")

        assert broadcast.match_type == MatchTypeEnum.SINGLES
        assert broadcast.broadcast_type == BroadcastTypeEnum.FIND_OPPONENT
        assert broadcast.partner_uid is None

    def test_to_broadcast_doubles_find_opponent(self):
        """Doubles + find_opponent + partner round-trips."""
        now = datetime.now(timezone.utc)
        doc = {
            "ownerUid": "user123",
            "sport": "tennis",
            "matchType": "doubles",
            "broadcastType": "find_opponent",
            "partnerUid": "user_partner",
            "availability": "today",
            "courtStatus": "have_court",
            "status": "active",
            "expiresAt": now + timedelta(hours=2),
            "createdAt": now,
            "location": {"area": 10001},
        }

        broadcast = to_broadcast(doc, broadcast_id="broadcast_dbl")

        assert broadcast.match_type == MatchTypeEnum.DOUBLES
        assert broadcast.broadcast_type == BroadcastTypeEnum.FIND_OPPONENT
        assert broadcast.partner_uid == "user_partner"

    def test_to_broadcast_doubles_find_fourth_no_partner(self):
        """Doubles + find_fourth without partner is valid (solo seeking 3)."""
        now = datetime.now(timezone.utc)
        doc = {
            "ownerUid": "user123",
            "sport": "padel",
            "matchType": "doubles",
            "broadcastType": "find_fourth",
            "availability": "today",
            "courtStatus": "have_court",
            "status": "active",
            "expiresAt": now + timedelta(hours=2),
            "createdAt": now,
            "location": {"area": 10001},
        }

        broadcast = to_broadcast(doc, broadcast_id="broadcast_4th")

        assert broadcast.match_type == MatchTypeEnum.DOUBLES
        assert broadcast.broadcast_type == BroadcastTypeEnum.FIND_FOURTH
        assert broadcast.partner_uid is None


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
            "venueRef": {
                "venueId": "ten_twenty_club",
                "placeId": None,
                "name": "Ten Twenty Club",
                "coordinates": {"lat": 37.8362, "lng": 23.7627},
            },
            "sourceBroadcastId": "broadcast123",
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
        assert offer.venue_ref.venue_id == "ten_twenty_club"
        assert offer.source_broadcast_id == "broadcast123"
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

    def test_to_offer_legacy_doc_defaults_to_singles(self):
        """DBL-4: legacy offer doc without matchType/partnerUid → singles."""
        from app.models.enums import MatchTypeEnum

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

        assert offer.match_type == MatchTypeEnum.SINGLES
        assert offer.partner_uid is None

    def test_to_offer_doubles_persists_partner_uid(self):
        """DBL-4: doubles offer doc carries matchType and partnerUid."""
        from app.models.enums import MatchTypeEnum

        now = datetime.now(timezone.utc)
        doc = {
            "fromUid": "alice",
            "toUid": "bob",
            "sport": "padel",
            "matchType": "doubles",
            "partnerUid": "charlie",
            "proposedTime": now + timedelta(hours=2),
            "status": "pending",
            "expiresAt": now + timedelta(minutes=5),
            "createdAt": now,
        }

        offer = to_offer(doc, offer_id="offer_doubles")

        assert offer.match_type == MatchTypeEnum.DOUBLES
        assert offer.partner_uid == "charlie"


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


class TestParseUserPreferences:
    def test_feed_opt_out_defaults_to_false_when_missing(self):
        """A Firestore preferences doc without feedOptOut should default feed_opt_out to False."""
        from app.repos.mappers import _parse_user_preferences

        prefs = _parse_user_preferences({"area": 1, "levels": {}, "sports": ["padel"]})

        assert prefs.feed_opt_out is False

    def test_feed_opt_out_true_is_parsed(self):
        """feedOptOut=true in Firestore maps to feed_opt_out=True on the model."""
        from app.repos.mappers import _parse_user_preferences

        prefs = _parse_user_preferences(
            {"area": 1, "levels": {}, "sports": [], "feedOptOut": True}
        )

        assert prefs.feed_opt_out is True

    def test_user_preferences_model_default(self):
        """UserPreferences model defaults feed_opt_out to False."""
        from app.models.common import PerSportLevels, UserPreferences

        prefs = UserPreferences(area=1, levels=PerSportLevels(), sports=[])

        assert prefs.feed_opt_out is False


# ── league division schema mappers ────────────────────────────────────────────


class TestLeagueDivisionSchemaMappers:
    def test_league_status_dividing_serializes_to_firestore_value(self):
        assert LeagueStatusEnum.DIVIDING.value == "dividing"

    def test_to_league_maps_division_config(self):
        divided_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
        doc = {
            "name": "Athens Divisions",
            "sport": "padel",
            "status": "open",
            "ownerUid": "owner_1",
            "dividedAt": divided_at,
            "divisionConfig": {"targetSize": 8, "maxDivisions": 3},
        }

        league = to_league(doc, league_id="league_divisions")

        assert league.league_id == "league_divisions"
        assert league.division_config is not None
        assert league.division_config.target_size == 8
        assert league.division_config.max_divisions == 3
        assert league.divided_at == divided_at

    def test_to_league_division_config_defaults_target_size(self):
        doc = {
            "name": "Athens Divisions",
            "sport": "padel",
            "status": "open",
            "ownerUid": "owner_1",
            "divisionConfig": {},
        }

        league = to_league(doc, league_id="league_divisions")

        assert league.division_config is not None
        assert league.division_config.target_size == 6
        assert league.division_config.max_divisions is None

    def test_to_league_legacy_doc_without_division_config_parses(self):
        doc = {
            "name": "Legacy League",
            "sport": "tennis",
            "status": "active",
            "ownerUid": "owner_1",
        }

        league = to_league(doc, league_id="league_legacy")

        assert league.division_config is None

    def test_to_league_member_maps_division_id(self):
        joined_at = datetime.now(timezone.utc)
        doc = {
            "role": "player",
            "status": "active",
            "joinedAt": joined_at,
            "displayName": "Alice",
            "divisionId": "div-1",
        }

        member = to_league_member(doc, uid="user_alice")

        assert member.uid == "user_alice"
        assert member.division_id == "div-1"

    def test_to_league_member_legacy_doc_without_division_id_parses(self):
        joined_at = datetime.now(timezone.utc)
        doc = {
            "role": "player",
            "status": "active",
            "joinedAt": joined_at,
        }

        member = to_league_member(doc, uid="user_legacy")

        assert member.division_id is None

    def test_to_division_maps_metadata_doc(self):
        doc = {
            "name": "Division 1",
            "ordinal": 1,
            "ratingRange": {"min": 980, "max": 1400},
            "currentPlayers": 6,
            "status": "active",
        }

        division = to_division(doc, division_id="div-1")

        assert division.division_id == "div-1"
        assert division.name == "Division 1"
        assert division.ordinal == 1
        assert division.rating_range.min == 980
        assert division.rating_range.max == 1400
        assert division.current_players == 6
        assert division.status == LeagueStatusEnum.ACTIVE

    def test_to_match_maps_optional_division_id(self):
        scheduled_at = datetime.now(timezone.utc)
        doc = {
            "sport": "padel",
            "status": "scheduled",
            "matchType": "singles",
            "scheduledAt": scheduled_at,
            "leagueId": "league_1",
            "divisionId": "div-1",
            "participantUids": ["user_a", "user_b"],
        }

        match = to_match(doc, match_id="match_1")

        assert match.division_id == "div-1"


# ── to_league_browse_card ─────────────────────────────────────────────────────


class TestToLeagueBrowseCard:
    def test_to_league_browse_card_complete(self):
        """All fields including camelCase browse fields map correctly with enum coercion."""
        start = datetime(2025, 9, 1, tzinfo=timezone.utc)
        doc = {
            "name": "Athens Open",
            "sport": "tennis",
            "status": "open",
            "region": "athens",
            "tier": "gold",
            "maxPlayers": 16,
            "currentPlayers": 8,
            "startDate": start,
        }

        card = to_league_browse_card(doc, league_id="league_athens_open")

        assert card.league_id == "league_athens_open"
        assert card.name == "Athens Open"
        assert card.sport == SportEnum.TENNIS
        assert card.status.value == "open"
        assert card.region == "athens"
        assert card.tier == "gold"
        assert card.max_players == 16
        assert card.current_players == 8
        assert card.start_date == start

    def test_to_league_browse_card_minimal(self):
        """Doc with only required fields (sport + status) — all optionals are None."""
        doc = {
            "sport": "padel",
            "status": "open",
        }

        card = to_league_browse_card(doc, league_id="league_minimal")

        assert card.league_id == "league_minimal"
        assert card.name == ""
        assert card.sport == SportEnum.PADEL
        assert card.region is None
        assert card.tier is None
        assert card.max_players is None
        assert card.current_players is None
        assert card.start_date is None

    def test_to_league_browse_card_legacy_doc(self):
        """Legacy doc without any LG-1 browse fields returns None for all optionals."""
        doc = {
            "name": "Old League",
            "sport": "pickleball",
            "status": "open",
            # no region, tier, maxPlayers, currentPlayers, startDate
        }

        card = to_league_browse_card(doc, league_id="league_legacy")

        assert card.league_id == "league_legacy"
        assert card.name == "Old League"
        assert card.sport == SportEnum.PICKLEBALL
        assert card.region is None
        assert card.tier is None
        assert card.max_players is None
        assert card.current_players is None
        assert card.start_date is None
