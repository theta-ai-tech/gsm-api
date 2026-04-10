import pytest
from pydantic import ValidationError

from app.models.common import GeoCoordinates, VenueRef


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
