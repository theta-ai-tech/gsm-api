import pytest
from pydantic import ValidationError

from app.models.common import GeoCoordinates, ParticipantEntry, VenueRef


class TestGeoCoordinates:
    def test_valid_construction(self) -> None:
        geo = GeoCoordinates(lat=37.9838, lng=23.7275)
        assert geo.lat == 37.9838
        assert geo.lng == 23.7275

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GeoCoordinates(lat=0.0, lng=0.0, altitude=10.0)  # type: ignore[call-arg]

    def test_accepts_integer_like_floats(self) -> None:
        geo = GeoCoordinates(lat=0, lng=0)  # type: ignore[arg-type]
        assert geo.lat == 0.0
        assert geo.lng == 0.0

    def test_rejects_lat_above_90(self) -> None:
        with pytest.raises(ValidationError):
            GeoCoordinates(lat=91.0, lng=0.0)

    def test_rejects_lat_below_minus_90(self) -> None:
        with pytest.raises(ValidationError):
            GeoCoordinates(lat=-91.0, lng=0.0)

    def test_rejects_lng_above_180(self) -> None:
        with pytest.raises(ValidationError):
            GeoCoordinates(lat=0.0, lng=181.0)

    def test_rejects_lng_below_minus_180(self) -> None:
        with pytest.raises(ValidationError):
            GeoCoordinates(lat=0.0, lng=-181.0)

    def test_accepts_boundary_values(self) -> None:
        geo = GeoCoordinates(lat=90.0, lng=180.0)
        assert geo.lat == 90.0
        assert geo.lng == 180.0


class TestVenueRef:
    def _coords(self) -> GeoCoordinates:
        return GeoCoordinates(lat=37.9838, lng=23.7275)

    def test_valid_with_venue_id_only(self) -> None:
        venue = VenueRef(
            venue_id="venue_athens_padel_glyfada",
            name="Athens Padel Glyfada",
            coordinates=self._coords(),
        )
        assert venue.venue_id == "venue_athens_padel_glyfada"
        assert venue.place_id is None
        assert venue.name == "Athens Padel Glyfada"
        assert venue.coordinates.lat == 37.9838

    def test_valid_with_place_id_only(self) -> None:
        venue = VenueRef(
            place_id="ChIJN1t_tDeuEmsRUsoyG83frY4",
            name="Some Google Place",
            coordinates=self._coords(),
        )
        assert venue.venue_id is None
        assert venue.place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4"

    def test_valid_with_both_ids(self) -> None:
        venue = VenueRef(
            venue_id="venue_athens_padel_glyfada",
            place_id="ChIJN1t_tDeuEmsRUsoyG83frY4",
            name="Athens Padel Glyfada",
            coordinates=self._coords(),
        )
        assert venue.venue_id == "venue_athens_padel_glyfada"
        assert venue.place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4"

    def test_rejects_when_both_ids_missing(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            VenueRef(
                name="No ID Venue",
                coordinates=self._coords(),
            )
        assert "venue_id" in str(exc_info.value) or "place_id" in str(exc_info.value)

    def test_rejects_when_both_ids_none_explicit(self) -> None:
        with pytest.raises(ValidationError):
            VenueRef(
                venue_id=None,
                place_id=None,
                name="No ID Venue",
                coordinates=self._coords(),
            )

    def test_empty_string_ids_treated_as_none(self) -> None:
        with pytest.raises(ValidationError):
            VenueRef(
                venue_id="",
                place_id="",
                name="Empty",
                coordinates=self._coords(),
            )

    def test_empty_string_venue_id_with_valid_place_id(self) -> None:
        venue = VenueRef(
            venue_id="",
            place_id="ChIJN1t_tDeuEmsRUsoyG83frY4",
            name="Empty venue_id",
            coordinates=self._coords(),
        )
        assert venue.venue_id is None
        assert venue.place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4"

    def test_name_required(self) -> None:
        with pytest.raises(ValidationError):
            VenueRef(
                venue_id="venue_x",
                coordinates=self._coords(),
            )  # type: ignore[call-arg]

    def test_coordinates_required(self) -> None:
        with pytest.raises(ValidationError):
            VenueRef(
                venue_id="venue_x",
                name="Some Venue",
            )  # type: ignore[call-arg]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VenueRef(
                venue_id="venue_x",
                name="Some Venue",
                coordinates=self._coords(),
                city="Athens",  # type: ignore[call-arg]
            )

    def test_camel_case_alias_deserialization(self) -> None:
        venue = VenueRef.model_validate(
            {
                "venueId": "venue_athens_padel_glyfada",
                "placeId": None,
                "name": "Athens Padel Glyfada",
                "coordinates": {"lat": 37.9838, "lng": 23.7275},
            }
        )
        assert venue.venue_id == "venue_athens_padel_glyfada"
        assert venue.place_id is None
        assert venue.name == "Athens Padel Glyfada"
        assert venue.coordinates.lat == 37.9838

    def test_camel_case_alias_serialization(self) -> None:
        venue = VenueRef(
            venue_id="venue_athens_padel_glyfada",
            name="Athens Padel Glyfada",
            coordinates=GeoCoordinates(lat=37.9838, lng=23.7275),
        )
        dumped = venue.model_dump(by_alias=True)
        assert "venueId" in dumped
        assert "placeId" in dumped
        assert dumped["venueId"] == "venue_athens_padel_glyfada"
        assert dumped["placeId"] is None
        assert dumped["name"] == "Athens Padel Glyfada"
        assert dumped["coordinates"] == {"lat": 37.9838, "lng": 23.7275}

    def test_snake_case_serialization_default(self) -> None:
        venue = VenueRef(
            venue_id="venue_athens_padel_glyfada",
            name="Athens Padel Glyfada",
            coordinates=GeoCoordinates(lat=37.9838, lng=23.7275),
        )
        dumped = venue.model_dump()
        assert "venue_id" in dumped
        assert "place_id" in dumped
        assert dumped["venue_id"] == "venue_athens_padel_glyfada"

    def test_camel_case_with_place_id_round_trip(self) -> None:
        original = VenueRef(
            place_id="ChIJN1t_tDeuEmsRUsoyG83frY4",
            name="Google Place Venue",
            coordinates=GeoCoordinates(lat=40.7128, lng=-74.0060),
        )
        dumped = original.model_dump(by_alias=True)
        rehydrated = VenueRef.model_validate(dumped)
        assert rehydrated.place_id == original.place_id
        assert rehydrated.venue_id is None
        assert rehydrated.name == original.name
        assert rehydrated.coordinates.lat == original.coordinates.lat
        assert rehydrated.coordinates.lng == original.coordinates.lng


class TestParticipantEntry:
    def test_singles_row_has_null_team(self) -> None:
        participant = ParticipantEntry(uid="user_ignatios", display_name="Ignatios C.")
        assert participant.uid == "user_ignatios"
        assert participant.team is None
        assert participant.display_name == "Ignatios C."

    def test_doubles_row_team_a(self) -> None:
        participant = ParticipantEntry(
            uid="user_ignatios", team="A", display_name="Ignatios C."
        )
        assert participant.uid == "user_ignatios"
        assert participant.team == "A"
        assert participant.display_name == "Ignatios C."

    def test_doubles_row_team_b(self) -> None:
        participant = ParticipantEntry(
            uid="user_alex", team="B", display_name="Alex P."
        )
        assert participant.team == "B"

    def test_uid_is_required(self) -> None:
        with pytest.raises(ValidationError):
            ParticipantEntry(display_name="Ignatios C.")  # type: ignore[call-arg]

    def test_display_name_is_required(self) -> None:
        with pytest.raises(ValidationError):
            ParticipantEntry(uid="user_ignatios")  # type: ignore[call-arg]

    def test_uid_cannot_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            ParticipantEntry(uid="", display_name="Ignatios C.")

    def test_display_name_cannot_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            ParticipantEntry(uid="user_ignatios", display_name="")

    def test_invalid_team_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ParticipantEntry(uid="user_ignatios", team="C", display_name="Ignatios C.")

    def test_invalid_team_lowercase_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ParticipantEntry(uid="user_ignatios", team="a", display_name="Ignatios C.")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ParticipantEntry(
                uid="user_ignatios",
                display_name="Ignatios C.",
                rating=1500,  # type: ignore[call-arg]
            )

    def test_round_trip_serialization_singles(self) -> None:
        original = ParticipantEntry(uid="user_ignatios", display_name="Ignatios C.")
        dumped = original.model_dump()
        rehydrated = ParticipantEntry.model_validate(dumped)
        assert rehydrated.uid == original.uid
        assert rehydrated.team is None
        assert rehydrated.display_name == original.display_name

    def test_round_trip_serialization_doubles(self) -> None:
        original = ParticipantEntry(
            uid="user_ignatios", team="A", display_name="Ignatios C."
        )
        dumped = original.model_dump()
        rehydrated = ParticipantEntry.model_validate(dumped)
        assert rehydrated.uid == original.uid
        assert rehydrated.team == "A"
        assert rehydrated.display_name == original.display_name

    def test_camel_case_alias_serialization_singles(self) -> None:
        participant = ParticipantEntry(uid="user_ignatios", display_name="Ignatios C.")
        dumped = participant.model_dump(by_alias=True)
        assert dumped["uid"] == "user_ignatios"
        assert dumped["team"] is None
        assert "displayName" in dumped
        assert dumped["displayName"] == "Ignatios C."
        assert "display_name" not in dumped

    def test_camel_case_alias_serialization_doubles(self) -> None:
        participant = ParticipantEntry(
            uid="user_ignatios", team="A", display_name="Ignatios C."
        )
        dumped = participant.model_dump(by_alias=True)
        assert dumped["uid"] == "user_ignatios"
        assert dumped["team"] == "A"
        assert "displayName" in dumped
        assert dumped["displayName"] == "Ignatios C."
        assert "display_name" not in dumped

    def test_snake_case_serialization_default(self) -> None:
        participant = ParticipantEntry(
            uid="user_ignatios", team="A", display_name="Ignatios C."
        )
        dumped = participant.model_dump()
        assert "display_name" in dumped
        assert dumped["display_name"] == "Ignatios C."
        assert "displayName" not in dumped

    def test_camel_case_alias_deserialization(self) -> None:
        participant = ParticipantEntry.model_validate(
            {"uid": "user_ignatios", "team": "A", "displayName": "Ignatios C."}
        )
        assert participant.uid == "user_ignatios"
        assert participant.team == "A"
        assert participant.display_name == "Ignatios C."

    def test_snake_case_deserialization_still_works(self) -> None:
        # populate_by_name=True means snake_case input must continue to hydrate.
        participant = ParticipantEntry.model_validate(
            {"uid": "user_ignatios", "team": "A", "display_name": "Ignatios C."}
        )
        assert participant.uid == "user_ignatios"
        assert participant.team == "A"
        assert participant.display_name == "Ignatios C."

    def test_camel_case_round_trip(self) -> None:
        original = ParticipantEntry(
            uid="user_ignatios", team="B", display_name="Ignatios C."
        )
        dumped = original.model_dump(by_alias=True)
        rehydrated = ParticipantEntry.model_validate(dumped)
        assert rehydrated.uid == original.uid
        assert rehydrated.team == original.team
        assert rehydrated.display_name == original.display_name
