"""Athens padel and tennis venue seed data.

Provides SAMPLE_VENUES (list of VenueSummary) and seed_venues() for populating
the ``venues/{venueId}`` Firestore collection from the emulator seeder.

Coordinates are validated against Google Maps.  Place IDs are included where
confirmed; leave as None and update via ``GET /venues/search`` once VEN-4 lands.
"""

from __future__ import annotations

from app.models.common import GeoCoordinates
from app.models.enums import SportEnum
from app.models.venue import VenueSummary

# ---------------------------------------------------------------------------
# Athens padel venues — Tier 1
# ---------------------------------------------------------------------------

_TEN_TWENTY = VenueSummary(
    venue_id="ten_twenty_club",
    name="Ten Twenty Club",
    coordinates=GeoCoordinates(lat=37.8362, lng=23.7627),
    area="Voula",
    sports=[SportEnum.PADEL],
    court_count=4,
    indoor=None,  # mixed indoor/outdoor
    place_id=None,
)

_FLISVOS = VenueSummary(
    venue_id="flisvos_padel_academy",
    name="Flisvos Padel Academy",
    coordinates=GeoCoordinates(lat=37.9234, lng=23.7003),
    area="Paleo Faliro",
    sports=[SportEnum.PADEL],
    court_count=3,
    indoor=False,
    place_id=None,
)

_ATHENS_PADEL_OLYMPICO = VenueSummary(
    venue_id="athens_padel_club_glyfada",
    name="Athens Padel Club (Olympico)",
    coordinates=GeoCoordinates(lat=37.8721, lng=23.7582),
    area="Glyfada",
    sports=[SportEnum.PADEL],
    court_count=3,
    indoor=True,
    place_id=None,
)

# ---------------------------------------------------------------------------
# Athens padel venues — Tier 2
# ---------------------------------------------------------------------------

_GOLDEN_POINT = VenueSummary(
    venue_id="golden_point_padel_club",
    name="Golden Point Padel Club",
    coordinates=GeoCoordinates(lat=37.9755, lng=23.7341),
    area="Central Athens",
    sports=[SportEnum.PADEL],
    court_count=None,
    indoor=None,
    place_id=None,
)

_LA_BANDEJA = VenueSummary(
    venue_id="la_bandeja_sports_club",
    name="La Bandeja Sports Club",
    coordinates=GeoCoordinates(lat=37.9102, lng=23.7185),
    area="South Athens",
    sports=[SportEnum.PADEL],
    court_count=None,
    indoor=None,
    place_id=None,
)

_HALANDRI = VenueSummary(
    venue_id="halandri_athletic_club",
    name="Halandri Athletic Club",
    coordinates=GeoCoordinates(lat=38.0218, lng=23.8014),
    area="Halandri",
    sports=[SportEnum.PADEL],
    court_count=2,
    indoor=False,
    place_id=None,
)

_ARENA_PADEL = VenueSummary(
    venue_id="arena_padel_club_marousi",
    name="Arena Padel Club",
    coordinates=GeoCoordinates(lat=38.0501, lng=23.8093),
    area="Marousi",
    sports=[SportEnum.PADEL],
    court_count=1,
    indoor=True,
    place_id=None,
)

_RENTI_ARENA = VenueSummary(
    venue_id="renti_arena_padel",
    name="Renti Arena Padel",
    coordinates=GeoCoordinates(lat=37.9613, lng=23.6942),
    area="Renti",
    sports=[SportEnum.PADEL],
    court_count=3,
    indoor=True,  # roofed
    place_id=None,
)

_GREEK_PADEL_ACADEMY = VenueSummary(
    venue_id="greek_padel_academy",
    name="Greek Padel Academy",
    coordinates=GeoCoordinates(lat=37.9072, lng=23.7274),
    area="Alimos",
    sports=[SportEnum.PADEL],
    court_count=None,
    indoor=None,
    place_id=None,
)

_NORTHPOINT = VenueSummary(
    venue_id="northpoint_padel_club",
    name="NorthPoint Padel Club",
    coordinates=GeoCoordinates(lat=38.1093, lng=23.8217),
    area="Anixi",
    sports=[SportEnum.PADEL],
    court_count=None,
    indoor=None,
    place_id=None,
)

# ---------------------------------------------------------------------------
# Athens tennis venues
# ---------------------------------------------------------------------------

_ATHENS_TENNIS_CLUB = VenueSummary(
    venue_id="athens_tennis_club",
    name="Athens Tennis Club",
    coordinates=GeoCoordinates(lat=37.9438, lng=23.6940),
    area="Neo Faliro",
    sports=[SportEnum.TENNIS],
    court_count=6,
    indoor=False,
    place_id=None,
)

_GLYFADA_TENNIS = VenueSummary(
    venue_id="glyfada_tennis_club",
    name="Glyfada Tennis Club",
    coordinates=GeoCoordinates(lat=37.8673, lng=23.7551),
    area="Glyfada",
    sports=[SportEnum.TENNIS],
    court_count=8,
    indoor=False,
    place_id=None,
)

_KIFISIA_TENNIS = VenueSummary(
    venue_id="kifisia_tennis_club",
    name="Kifisia Tennis Club",
    coordinates=GeoCoordinates(lat=38.0738, lng=23.8106),
    area="Kifisia",
    sports=[SportEnum.TENNIS],
    court_count=4,
    indoor=False,
    place_id=None,
)

_PALEO_FALIRO_TENNIS = VenueSummary(
    venue_id="paleo_faliro_tennis_club",
    name="Paleo Faliro Tennis Club",
    coordinates=GeoCoordinates(lat=37.9279, lng=23.7039),
    area="Paleo Faliro",
    sports=[SportEnum.TENNIS],
    court_count=5,
    indoor=False,
    place_id=None,
)

_MAROUSI_TENNIS = VenueSummary(
    venue_id="marousi_sports_club",
    name="Marousi Sports Club (Tennis)",
    coordinates=GeoCoordinates(lat=38.0532, lng=23.8047),
    area="Marousi",
    sports=[SportEnum.TENNIS],
    court_count=3,
    indoor=False,
    place_id=None,
)

# ---------------------------------------------------------------------------
# Venues that support both padel and tennis
# ---------------------------------------------------------------------------

_VOULA_SPORTS_COMPLEX = VenueSummary(
    venue_id="voula_sports_complex",
    name="Voula Sports Complex",
    coordinates=GeoCoordinates(lat=37.8448, lng=23.7719),
    area="Voula",
    sports=[SportEnum.TENNIS, SportEnum.PADEL],
    court_count=6,
    indoor=False,
    place_id=None,
)

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

SAMPLE_VENUES: list[VenueSummary] = [
    # Padel Tier 1
    _TEN_TWENTY,
    _FLISVOS,
    _ATHENS_PADEL_OLYMPICO,
    # Padel Tier 2
    _GOLDEN_POINT,
    _LA_BANDEJA,
    _HALANDRI,
    _ARENA_PADEL,
    _RENTI_ARENA,
    _GREEK_PADEL_ACADEMY,
    _NORTHPOINT,
    # Tennis
    _ATHENS_TENNIS_CLUB,
    _GLYFADA_TENNIS,
    _KIFISIA_TENNIS,
    _PALEO_FALIRO_TENNIS,
    _MAROUSI_TENNIS,
    # Multi-sport
    _VOULA_SPORTS_COMPLEX,
]
