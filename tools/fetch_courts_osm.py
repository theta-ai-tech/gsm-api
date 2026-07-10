"""Fetch raw tennis/padel/pickleball court candidates from the Overpass API.

This is the raw-pull step of the venue-seeding epic: it queries OpenStreetMap
(via Overpass) for court-like features across three Greek metro areas and three
sports, then writes the raw candidates to ``tools/data/osm_courts_raw.json`` for
human review. No normalisation, no Firestore writes happen here.

Import safety
-------------
Importing this module performs **no** network I/O. All HTTP calls live inside
``main()``, guarded by ``if __name__ == "__main__":``. Query construction
(``build_overpass_query``) and response parsing (``parse_overpass_response``) are
pure functions so they can be unit-tested with fixture dicts — no network
mocking required.

Metro bounding boxes
--------------------
Bounds live in ``METRO_BBOXES`` below, in one documented place so they can be
adjusted or extended. Each bbox is an Overpass-order tuple
``(south, west, north, east)`` in WGS84 decimal degrees (i.e.
``(min_lat, min_lng, max_lat, max_lng)``) — this is the order Overpass expects
inside a ``(bbox)`` filter. Boxes are generous rectangles around each metro area,
sourced from OSM/Google map inspection; widen them here to extend coverage.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("fetch_courts_osm")

# Public Overpass endpoint. Overridable via CLI for a mirror.
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Where the raw candidates are written for human review.
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "data" / "osm_courts_raw.json"

# Metro bounding boxes in Overpass order: (south, west, north, east) =
# (min_lat, min_lng, max_lat, max_lng), WGS84 decimal degrees. Edit here to
# adjust or extend coverage.
METRO_BBOXES: dict[str, tuple[float, float, float, float]] = {
    # Attica basin around Athens (incl. southern coast + northern suburbs).
    "athens": (37.80, 23.55, 38.15, 23.95),
    # Thessaloniki metro along the Thermaic Gulf.
    "thessaloniki": (40.55, 22.85, 40.70, 23.05),
    # Patras metro on the northern Peloponnese coast.
    "patras": (38.20, 21.68, 38.30, 21.80),
}

# Sports we pull, matched against the OSM ``sport=*`` tag.
SPORTS: tuple[str, ...] = ("tennis", "padel", "pickleball")

# Overpass request timeout (seconds) embedded in the QL ``[timeout:...]`` header.
OVERPASS_QL_TIMEOUT_SECONDS = 90

# httpx client timeout (seconds); slightly larger than the QL timeout so the
# server-side timeout surfaces before the client aborts.
HTTP_TIMEOUT_SECONDS = 120.0


def build_overpass_query(
    bboxes: dict[str, tuple[float, float, float, float]] = METRO_BBOXES,
    sports: tuple[str, ...] = SPORTS,
    ql_timeout: int = OVERPASS_QL_TIMEOUT_SECONDS,
) -> str:
    """Build a single Overpass QL query covering every metro x sport.

    For each metro bbox and each sport we emit statements matching court-like
    features on ``leisure=pitch``, ``leisure=sports_centre`` and ``club=sport``,
    for nodes, ways and relations. ``out center;`` is used so ways/relations come
    back with a computed centroid (``center.lat``/``center.lon``).
    """
    lines: list[str] = [
        f"[out:json][timeout:{ql_timeout}];",
        "(",
    ]
    for metro, bbox in bboxes.items():
        south, west, north, east = bbox
        bbox_str = f"{south},{west},{north},{east}"
        lines.append(f"  // {metro}")
        for sport in sports:
            for tag in ("leisure=pitch", "leisure=sports_centre", "club=sport"):
                key, value = tag.split("=", 1)
                for element in ("node", "way", "relation"):
                    lines.append(
                        f'  {element}["{key}"="{value}"]'
                        f'["sport"~"(^|;){sport}($|;)"]({bbox_str});'
                    )
    lines.append(");")
    # `out center` prints geometry: nodes keep lat/lon, ways/relations gain a
    # centroid. `out center tags` would drop node coordinates, so keep it plain.
    lines.append("out center;")
    return "\n".join(lines)


def _element_coordinates(element: dict[str, Any]) -> tuple[float | None, float | None]:
    """Return (lat, lng) for an element.

    Nodes carry ``lat``/``lon`` directly. Ways and relations carry a computed
    ``center`` object (from ``out center``) with ``lat``/``lon`` inside it.
    """
    if "lat" in element and "lon" in element:
        return element["lat"], element["lon"]
    center = element.get("center")
    if isinstance(center, dict) and "lat" in center and "lon" in center:
        return center["lat"], center["lon"]
    return None, None


def _split_sport_tag(sport_value: str) -> list[str]:
    """Split an OSM ``sport`` tag value into its individual sports.

    OSM encodes multi-sport features as semicolon-separated values, e.g.
    ``"tennis;padel"``.
    """
    return [part.strip() for part in sport_value.split(";") if part.strip()]


def parse_overpass_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse an Overpass JSON response into raw venue candidates.

    Each candidate carries: ``name``, ``lat``, ``lng``, ``sports`` (list),
    ``osm_type``, ``osm_id``, and the ``courts``/``surface``/``building`` tags
    when present. Elements without resolvable coordinates are skipped.
    """
    candidates: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {}) or {}
        lat, lng = _element_coordinates(element)
        if lat is None or lng is None:
            logger.debug(
                "Skipping %s/%s: no resolvable coordinates",
                element.get("type"),
                element.get("id"),
            )
            continue
        sport_value = tags.get("sport", "")
        candidates.append(
            {
                "name": tags.get("name"),
                "lat": lat,
                "lng": lng,
                "sports": _split_sport_tag(sport_value),
                "osm_type": element.get("type"),
                "osm_id": element.get("id"),
                "courts": tags.get("courts"),
                "surface": tags.get("surface"),
                "building": tags.get("building"),
            }
        )
    return candidates


def fetch_overpass(query: str, url: str = DEFAULT_OVERPASS_URL) -> dict[str, Any]:
    """POST the Overpass QL query and return the parsed JSON response."""
    response = httpx.post(url, data={"data": query}, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def write_candidates(candidates: list[dict[str, Any]], output_path: Path) -> None:
    """Write candidates to ``output_path`` as pretty-printed JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch raw OSM court candidates for the venue-seeding epic."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_OVERPASS_URL,
        help="Overpass API endpoint (default: public instance).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write the raw candidate JSON.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the full pull: build query, fetch, parse, and write candidates."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args()
    query = build_overpass_query()
    logger.info(
        "Querying Overpass at %s for %d metros x %d sports",
        args.url,
        len(METRO_BBOXES),
        len(SPORTS),
    )
    payload = fetch_overpass(query, url=args.url)
    candidates = parse_overpass_response(payload)
    write_candidates(candidates, args.output)
    logger.info("Wrote %d raw candidates to %s", len(candidates), args.output)


if __name__ == "__main__":
    main()
