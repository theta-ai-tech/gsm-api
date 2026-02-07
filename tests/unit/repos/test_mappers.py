from datetime import datetime, timedelta, timezone


from app.models.enums import (
    SportEnum,
    BroadcastStatusEnum,
    AvailabilityEnum,
    CourtStatusEnum,
    OfferStatusEnum,
)
from app.repos.mappers import (
    to_broadcast,
    to_offer,
    _parse_geo_location,
    _parse_broadcast_location,
)


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
