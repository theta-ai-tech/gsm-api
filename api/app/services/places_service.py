from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

import httpx

from app.constants import (
    VENUE_SEARCH_CACHE_MAX_SIZE,
    VENUE_SEARCH_LOCATION_BIAS_RADIUS_M,
    VENUE_SEARCH_MAX_RESULTS,
)
from app.models.common import GeoCoordinates, VenueRef

logger = logging.getLogger(__name__)

PLACES_AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


class PlacesUpstreamError(Exception):
    """Raised when the Google Places API returns an error or is unreachable."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class PlacesService:
    """Proxy for the Google Places Autocomplete + Details APIs.

    Keeps the API key server-side and applies an in-memory LRU cache to
    reduce cost for repeated queries.
    """

    def __init__(self, api_key: str, http_client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._http = http_client or httpx.Client(timeout=5.0)

    def autocomplete(
        self,
        query: str,
        lat: float | None = None,
        lng: float | None = None,
    ) -> list[VenueRef]:
        """Return up to ``VENUE_SEARCH_MAX_RESULTS`` venue references from
        Google Places Autocomplete, enriched with coordinates via Place Details.
        """
        cache_key = _cache_key(query, lat, lng)
        cached = _result_cache_get(cache_key)
        if cached is not None:
            return cached

        predictions = self._fetch_autocomplete(query, lat, lng)
        results: list[VenueRef] = []
        for pred in predictions[:VENUE_SEARCH_MAX_RESULTS]:
            place_id: str = pred["place_id"]
            name: str = pred.get("structured_formatting", {}).get(
                "main_text", pred.get("description", "")
            )
            coords = self._fetch_place_coordinates(place_id)
            if coords is None:
                continue
            results.append(
                VenueRef.model_validate(
                    {
                        "place_id": place_id,
                        "name": name,
                        "coordinates": {"lat": coords.lat, "lng": coords.lng},
                    }
                )
            )
        _result_cache_put(cache_key, results)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_autocomplete(
        self,
        query: str,
        lat: float | None,
        lng: float | None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "input": query,
            "types": "establishment",
            "key": self._api_key,
        }
        if lat is not None and lng is not None:
            params["location"] = f"{lat},{lng}"
            params["radius"] = str(VENUE_SEARCH_LOCATION_BIAS_RADIUS_M)

        try:
            resp = self._http.get(PLACES_AUTOCOMPLETE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.exception("Google Places Autocomplete request failed")
            raise PlacesUpstreamError("Google Places API unreachable") from exc

        api_status = data.get("status")
        if api_status == "ZERO_RESULTS":
            return []
        if api_status != "OK":
            logger.warning("Places Autocomplete status=%s", api_status)
            raise PlacesUpstreamError(f"Google Places API error: {api_status}")

        return data.get("predictions", [])

    def _fetch_place_coordinates(self, place_id: str) -> GeoCoordinates | None:
        params = {
            "place_id": place_id,
            "fields": "geometry",
            "key": self._api_key,
        }
        try:
            resp = self._http.get(PLACES_DETAILS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError:
            logger.exception("Google Places Details request failed for %s", place_id)
            return None

        if data.get("status") != "OK":
            return None

        location = data.get("result", {}).get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        if lat is None or lng is None:
            return None
        return GeoCoordinates(lat=lat, lng=lng)


# ------------------------------------------------------------------
# Module-level LRU cache (lightweight, no Redis dependency for MVP)
# ------------------------------------------------------------------

_cache: OrderedDict[str, list[VenueRef]] = OrderedDict()


def _cache_key(query: str, lat: float | None, lng: float | None) -> str:
    lat_r = round(lat, 2) if lat is not None else ""
    lng_r = round(lng, 2) if lng is not None else ""
    return f"{query.lower().strip()}|{lat_r}|{lng_r}"


def _result_cache_get(key: str) -> list[VenueRef] | None:
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    return None


def _result_cache_put(key: str, results: list[VenueRef]) -> None:
    if key in _cache:
        _cache.move_to_end(key)
        return
    if len(_cache) >= VENUE_SEARCH_CACHE_MAX_SIZE:
        _cache.popitem(last=False)
    _cache[key] = results


def clear_cache() -> None:
    """Reset the in-memory cache (useful for tests)."""
    _cache.clear()
