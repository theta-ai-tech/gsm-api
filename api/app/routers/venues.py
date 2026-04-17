from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.constants import VENUE_SEARCH_MAX_RESULTS
from app.deps import get_current_user
from app.dependencies.repos import get_venue_repo
from app.models.base import GsmBaseModel
from app.models.common import VenueRef
from app.repos.venue_repo import VenueRepo
from app.security import CurrentUser
from app.services.places_service import PlacesService, PlacesUpstreamError
from app.settings import get_settings

router = APIRouter(prefix="/venues", tags=["venues"])


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class VenueSearchResponse(GsmBaseModel):
    results: list[VenueRef]


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def get_places_service() -> PlacesService:
    settings = get_settings()
    if not settings.google_places_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Places API key not configured",
        )
    return PlacesService(api_key=settings.google_places_api_key)


# ---------------------------------------------------------------------------
# GET /venues/search
# ---------------------------------------------------------------------------


@router.get("/search", response_model=VenueSearchResponse)
def search_venues(
    q: str = Query(..., min_length=1, max_length=200),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    current_user: CurrentUser = Depends(get_current_user),
    venue_repo: VenueRepo = Depends(get_venue_repo),
) -> VenueSearchResponse:
    """Proxy Google Places Autocomplete and merge with curated venues.

    Returns up to 5 results combining Google Places results with any matching
    curated venues from the ``venues`` Firestore collection.
    """
    # Resolve PlacesService after param validation so invalid params
    # return 422 instead of 503 when the API key is missing.
    places_service = get_places_service()

    # 1. Google Places results
    try:
        google_results = places_service.autocomplete(query=q, lat=lat, lng=lng)
    except PlacesUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.detail,
        ) from exc

    # 2. Curated venue prefix search
    curated = venue_repo.search_by_name_prefix(q, limit=VENUE_SEARCH_MAX_RESULTS)

    # 3. Merge: curated venues first (they have venue_id), then Google results.
    #    Deduplicate by place_id.
    seen_place_ids: set[str] = set()
    merged: list[VenueRef] = []

    for v in curated:
        ref = VenueRef.model_validate(
            {
                "venue_id": v.venue_id,
                "place_id": v.place_id,
                "name": v.name,
                "coordinates": {"lat": v.coordinates.lat, "lng": v.coordinates.lng},
            }
        )
        if v.place_id:
            seen_place_ids.add(v.place_id)
        merged.append(ref)

    for ref in google_results:
        if ref.place_id and ref.place_id in seen_place_ids:
            continue
        if ref.place_id:
            seen_place_ids.add(ref.place_id)
        merged.append(ref)

    return VenueSearchResponse(results=merged[:VENUE_SEARCH_MAX_RESULTS])
