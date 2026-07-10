"""Deterministic venue-ID derivation for the venue-seeding epic.

Every downstream step (normalisation, enrichment, Firestore writes) depends on a
single, stable contract for turning a candidate venue into a ``venueId``. This
module is pure and has no I/O.

ID derivation rules
--------------------
OSM-sourced venue
    ``osm_{element_type}_{osm_id}`` — e.g. an OSM way ``123456`` becomes
    ``osm_way_123456``. ``element_type`` is one of ``node``/``way``/``relation``
    (lower-cased); ``osm_id`` is the integer OSM element id. This is stable
    because the OSM element type + id pair is globally unique and never reused
    for a different feature, so re-running the pull always yields the same id.

Hand-added venue (no OSM id)
    ``manual_{metro_slug}_{name_slug}`` — e.g. name ``"Ten Twenty Club"`` in
    metro ``"Athens"`` becomes ``manual_athens_ten_twenty_club``. The slug is a
    lower-cased, ASCII, hyphen/space-collapsed-to-underscore transform of the
    input. Two venues with the same name in the same metro are treated as the
    same venue; different metros keep them distinct.

Collision safety
    ``VenueIdRegistry`` tracks which payload each derived id was assigned to. If
    two *distinct* venues derive the same id, ``register`` raises
    ``VenueIdCollisionError`` instead of silently overwriting. Registering the
    same id with an equal payload is idempotent and allowed.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# OSM element types we accept. Overpass returns these lower-cased in the
# ``type`` field of each element.
_VALID_OSM_ELEMENT_TYPES = frozenset({"node", "way", "relation"})


class VenueIdCollisionError(ValueError):
    """Raised when two distinct venues derive the same ``venueId``."""


def slugify(value: str) -> str:
    """Return a lower-cased ASCII slug using underscores as the separator.

    Accents are stripped (``Glyfáda`` -> ``glyfada``), any run of
    non-alphanumeric characters collapses to a single underscore, and leading or
    trailing underscores are trimmed.
    """
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    collapsed = re.sub(r"[^a-z0-9]+", "_", lowered)
    return collapsed.strip("_")


def venue_id_for_osm(element_type: str, osm_id: int | str) -> str:
    """Derive a stable ``venueId`` from an OSM element type and id.

    ``element_type`` must be one of ``node``/``way``/``relation`` (case
    insensitive). ``osm_id`` may be an int or a numeric string.
    """
    normalized_type = element_type.strip().lower()
    if normalized_type not in _VALID_OSM_ELEMENT_TYPES:
        raise ValueError(
            f"Unsupported OSM element type {element_type!r}; "
            f"expected one of {sorted(_VALID_OSM_ELEMENT_TYPES)}."
        )
    osm_id_str = str(osm_id).strip()
    if not osm_id_str.isdigit():
        raise ValueError(f"OSM id must be a positive integer, got {osm_id!r}.")
    return f"osm_{normalized_type}_{osm_id_str}"


def venue_id_for_manual(name: str, metro: str) -> str:
    """Derive a stable ``venueId`` for a hand-added venue from name + metro."""
    name_slug = slugify(name)
    metro_slug = slugify(metro)
    if not name_slug:
        raise ValueError(f"Venue name {name!r} produced an empty slug.")
    if not metro_slug:
        raise ValueError(f"Metro {metro!r} produced an empty slug.")
    return f"manual_{metro_slug}_{name_slug}"


class VenueIdRegistry:
    """Track assigned venue ids and reject collisions between distinct venues.

    Registering the same id with an equal payload is a no-op; registering it with
    a *different* payload raises :class:`VenueIdCollisionError`.
    """

    def __init__(self) -> None:
        self._assignments: dict[str, Any] = {}

    def register(self, venue_id: str, payload: Any) -> str:
        """Assign ``venue_id`` to ``payload``; raise on a conflicting payload."""
        if venue_id in self._assignments:
            existing = self._assignments[venue_id]
            if existing != payload:
                raise VenueIdCollisionError(
                    f"venueId {venue_id!r} already assigned to a different venue: "
                    f"{existing!r} vs {payload!r}."
                )
            return venue_id
        self._assignments[venue_id] = payload
        return venue_id

    def __contains__(self, venue_id: object) -> bool:
        return venue_id in self._assignments

    def __len__(self) -> int:
        return len(self._assignments)

    @property
    def assignments(self) -> dict[str, Any]:
        """Return a shallow copy of the current id -> payload assignments."""
        return dict(self._assignments)
