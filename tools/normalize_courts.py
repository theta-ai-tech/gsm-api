"""Normalise raw OSM court candidates into a ``VenueSummary`` review checkpoint.

This is the normalisation step of the venue-seeding epic. It reads the raw
Overpass candidates written by ``tools/fetch_courts_osm.py`` (from #385) at
``tools/data/osm_courts_raw.json`` and emits a human-readable, hand-editable
**review-checkpoint JSON** at ``tools/data/venue_checkpoint.json``. Downstream
ingest (#387) consumes the *approved* checkpoint — nothing here writes to
Firestore.

Review → edit → approve flow
----------------------------
1. ``tools/fetch_courts_osm.py`` pulls raw candidates → ``osm_courts_raw.json``.
2. ``tools/normalize_courts.py`` (this module) normalises them →
   ``venue_checkpoint.json`` (one row per venue, deterministic ``venueId``,
   ``area`` = metro string, ``sports[]`` collapsed).
3. A human **reviews** the checkpoint JSON: it is indented and sorted by
   ``venueId`` so diffs are stable. They may edit field values (fix a name,
   set ``courtCount``/``indoor``, correct ``area``) or delete whole rows. The
   file is plain JSON — no code changes required to curate it.
4. Once approved, the downstream ingest step (#387) reads the checkpoint and
   upserts ``venues/{venueId}`` documents.

Import safety
-------------
Importing this module performs **no** I/O. All file reads/writes live inside
``main()`` (guarded by ``if __name__ == "__main__":``). The normalisation
functions are pure and unit-tested with fixture dicts — no network, no files.

Mapping rules
-------------
- ``area`` is the metro whose bounding box (``METRO_BBOXES`` from #385) contains
  the candidate's coordinates — one of ``athens``/``thessaloniki``/``patras``.
- OSM ``sport`` values are filtered to the supported ``SportEnum`` members
  (``tennis``/``padel``/``pickleball``); unknown values are ignored.
- Multi-sport venues collapse into a single row with a ``sports[]`` array.
- ``courtCount`` comes from the OSM ``courts`` tag (else null); ``indoor`` is
  inferred from an explicit ``indoor`` tag or a ``building`` tag (else null).
- ``placeId`` is null on every row (Places enrichment is deferred).
- ``venueId`` is the deterministic id from ``tools/venue_ids.py`` (#385).
- Rows missing a name, missing coordinates, falling outside every metro box, or
  carrying no supported sport are dropped with a logged reason.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from app.models.common import GeoCoordinates
from app.models.enums import SportEnum
from app.models.venue import VenueSummary

from tools.fetch_courts_osm import METRO_BBOXES
from tools.venue_ids import VenueIdRegistry, venue_id_for_manual, venue_id_for_osm

logger = logging.getLogger("normalize_courts")

# Raw candidates written by the #385 fetch step.
DEFAULT_INPUT_PATH = Path(__file__).resolve().parent / "data" / "osm_courts_raw.json"

# Human-review checkpoint this module emits.
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "data" / "venue_checkpoint.json"

# Supported sports, keyed by their OSM ``sport`` tag value.
_SUPPORTED_SPORTS: dict[str, SportEnum] = {sport.value: sport for sport in SportEnum}

# Truthy/falsy string values seen in OSM boolean-ish tags.
_TRUE_VALUES = frozenset({"yes", "true", "1", "indoor", "covered"})
_FALSE_VALUES = frozenset({"no", "false", "0", "outdoor"})


def metro_for_coords(
    lat: float,
    lng: float,
    bboxes: dict[str, tuple[float, float, float, float]] = METRO_BBOXES,
) -> str | None:
    """Return the metro whose bounding box contains ``(lat, lng)``, else None.

    ``bboxes`` values are Overpass-order tuples ``(south, west, north, east)`` =
    ``(min_lat, min_lng, max_lat, max_lng)``.
    """
    for metro, (south, west, north, east) in bboxes.items():
        if south <= lat <= north and west <= lng <= east:
            return metro
    return None


def sports_from_osm(raw_sports: list[str] | None) -> list[SportEnum]:
    """Map raw OSM sport values to supported ``SportEnum`` members.

    Unknown/unsupported values are ignored. Order is preserved and duplicates
    are collapsed so a multi-sport venue yields one entry per distinct sport.
    """
    result: list[SportEnum] = []
    for value in raw_sports or []:
        sport = _SUPPORTED_SPORTS.get(str(value).strip().lower())
        if sport is not None and sport not in result:
            result.append(sport)
    return result


def _parse_court_count(raw: dict[str, Any]) -> int | None:
    """Parse the OSM ``courts`` tag into an int, or None when absent/invalid."""
    value = raw.get("courts")
    if value is None:
        return None
    text = str(value).strip()
    if not (text.isascii() and text.isdigit()):
        return None
    count = int(text)
    return count if count > 0 else None


def _parse_indoor(raw: dict[str, Any]) -> bool | None:
    """Infer ``indoor`` from OSM tags, or None when there is no signal.

    An explicit ``indoor`` tag wins. Failing that, a ``building`` tag implies a
    covered (indoor) facility. Anything ambiguous stays null for human review.
    """
    explicit = raw.get("indoor")
    if explicit is not None:
        text = str(explicit).strip().lower()
        if text in _TRUE_VALUES:
            return True
        if text in _FALSE_VALUES:
            return False
    building = raw.get("building")
    if building is not None:
        text = str(building).strip().lower()
        if text and text not in _FALSE_VALUES:
            return True
    return None


def _venue_id_for(raw: dict[str, Any], name: str, metro: str) -> str:
    """Derive the deterministic ``venueId`` for a candidate.

    Prefers the OSM element type + id (globally unique, stable across re-runs);
    falls back to the name+metro manual scheme when OSM identifiers are absent.
    """
    osm_type = raw.get("osm_type")
    osm_id = raw.get("osm_id")
    if osm_type and osm_id is not None:
        return venue_id_for_osm(str(osm_type), osm_id)
    return venue_id_for_manual(name, metro)


def normalize_candidate(
    raw: dict[str, Any],
    registry: VenueIdRegistry,
) -> VenueSummary | None:
    """Normalise one raw candidate to a ``VenueSummary`` row, or drop it.

    Returns None (and logs the reason) when the candidate is missing a name,
    missing coordinates, falls outside every metro box, or carries no supported
    sport. Registers the derived ``venueId`` with ``registry`` so two distinct
    venues that derive the same id raise ``VenueIdCollisionError``.
    """
    name = raw.get("name")
    if not name or not str(name).strip():
        logger.info("Dropping candidate %s: missing name", raw.get("osm_id"))
        return None

    lat = raw.get("lat")
    lng = raw.get("lng")
    if lat is None or lng is None:
        logger.info("Dropping candidate %r: missing coordinates", name)
        return None

    metro = metro_for_coords(float(lat), float(lng))
    if metro is None:
        logger.info(
            "Dropping candidate %r: coordinates (%s, %s) outside every metro box",
            name,
            lat,
            lng,
        )
        return None

    sports = sports_from_osm(raw.get("sports"))
    if not sports:
        logger.info(
            "Dropping candidate %r: no supported sports in %r", name, raw.get("sports")
        )
        return None

    clean_name = str(name).strip()
    venue = VenueSummary(
        venue_id=_venue_id_for(raw, clean_name, metro),
        name=clean_name,
        coordinates=GeoCoordinates(lat=float(lat), lng=float(lng)),
        area=metro,
        sports=sports,
        court_count=_parse_court_count(raw),
        indoor=_parse_indoor(raw),
        place_id=None,
    )
    registry.register(venue.venue_id, venue.model_dump(by_alias=True, mode="json"))
    return venue


def normalize_candidates(raw_candidates: list[dict[str, Any]]) -> list[VenueSummary]:
    """Normalise a list of raw candidates into deduplicated ``VenueSummary`` rows.

    Rows are sorted by ``venueId`` for stable diffs. Candidates that derive an
    id already emitted (an identical venue seen twice, e.g. matched by two sport
    statements) are collapsed into one row; distinct venues sharing an id raise.
    """
    registry = VenueIdRegistry()
    venues: dict[str, VenueSummary] = {}
    for raw in raw_candidates:
        venue = normalize_candidate(raw, registry)
        if venue is None:
            continue
        venues.setdefault(venue.venue_id, venue)
    return [venues[venue_id] for venue_id in sorted(venues)]


def read_raw_candidates(input_path: Path) -> list[dict[str, Any]]:
    """Read the raw OSM candidate list written by the fetch step."""
    data: list[dict[str, Any]] = json.loads(input_path.read_text(encoding="utf-8"))
    return data


def write_checkpoint(venues: list[VenueSummary], output_path: Path) -> None:
    """Write the review checkpoint as indented, hand-editable JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [venue.model_dump(by_alias=True, mode="json") for venue in venues]
    output_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalise raw OSM court candidates into a VenueSummary checkpoint."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Raw OSM candidate JSON (default: tools/data/osm_courts_raw.json).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write the review checkpoint (default: tools/data/venue_checkpoint.json).",
    )
    return parser.parse_args()


def main() -> None:
    """Read raw candidates, normalise them, and write the review checkpoint."""
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = _parse_args()
    raw_candidates = read_raw_candidates(args.input)
    venues = normalize_candidates(raw_candidates)
    write_checkpoint(venues, args.output)
    logger.info(
        "Normalised %d raw candidates into %d venue rows at %s",
        len(raw_candidates),
        len(venues),
        args.output,
    )


if __name__ == "__main__":
    main()
