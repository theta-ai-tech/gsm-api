"""Unit tests for PlacesService.

Uses a mocked httpx.Client to avoid real Google API calls.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.services.places_service import PlacesService, clear_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


def _mock_http(autocomplete_json: dict | None = None, details_json: dict | None = None):
    """Return a mock httpx.Client whose .get() returns canned responses."""
    client = Mock()

    default_ac = {"status": "OK", "predictions": []}
    default_det = {
        "status": "OK",
        "result": {"geometry": {"location": {"lat": 37.93, "lng": 23.68}}},
    }

    ac_resp = Mock()
    ac_resp.json.return_value = autocomplete_json or default_ac
    ac_resp.raise_for_status = Mock()

    det_resp = Mock()
    det_resp.json.return_value = details_json or default_det
    det_resp.raise_for_status = Mock()

    def _route(url: str, **kwargs):
        if "autocomplete" in url:
            return ac_resp
        return det_resp

    client.get = Mock(side_effect=_route)
    return client


class TestAutocomplete:
    def test_returns_venue_refs_from_predictions(self):
        http = _mock_http(
            autocomplete_json={
                "status": "OK",
                "predictions": [
                    {
                        "place_id": "ChIJ_abc",
                        "structured_formatting": {"main_text": "Flisvos Padel"},
                        "description": "Flisvos Padel Academy, Athens",
                    },
                ],
            }
        )
        svc = PlacesService(api_key="test-key", http_client=http)
        results = svc.autocomplete("padel", lat=37.9, lng=23.7)
        assert len(results) == 1
        assert results[0].place_id == "ChIJ_abc"
        assert results[0].name == "Flisvos Padel"
        assert results[0].coordinates.lat == 37.93

    def test_zero_results_returns_empty(self):
        http = _mock_http(
            autocomplete_json={"status": "ZERO_RESULTS", "predictions": []}
        )
        svc = PlacesService(api_key="test-key", http_client=http)
        results = svc.autocomplete("nonexistent")
        assert results == []

    def test_error_status_returns_empty(self):
        http = _mock_http(autocomplete_json={"status": "REQUEST_DENIED"})
        svc = PlacesService(api_key="test-key", http_client=http)
        results = svc.autocomplete("padel")
        assert results == []

    def test_max_five_results_returned(self):
        predictions = [
            {
                "place_id": f"ChIJ_{i}",
                "structured_formatting": {"main_text": f"Venue {i}"},
            }
            for i in range(10)
        ]
        http = _mock_http(
            autocomplete_json={"status": "OK", "predictions": predictions}
        )
        svc = PlacesService(api_key="test-key", http_client=http)
        results = svc.autocomplete("venue")
        assert len(results) == 5

    def test_caching_avoids_duplicate_api_call(self):
        http = _mock_http(
            autocomplete_json={
                "status": "OK",
                "predictions": [
                    {
                        "place_id": "ChIJ_abc",
                        "structured_formatting": {"main_text": "Flisvos"},
                    }
                ],
            }
        )
        svc = PlacesService(api_key="test-key", http_client=http)
        svc.autocomplete("padel", lat=37.9, lng=23.7)
        svc.autocomplete("padel", lat=37.9, lng=23.7)
        # autocomplete called once, details called once = 2 total calls
        assert http.get.call_count == 2

    def test_skips_prediction_when_details_fail(self):
        http = _mock_http(
            autocomplete_json={
                "status": "OK",
                "predictions": [
                    {
                        "place_id": "ChIJ_abc",
                        "structured_formatting": {"main_text": "Flisvos"},
                    }
                ],
            },
            details_json={"status": "NOT_FOUND"},
        )
        svc = PlacesService(api_key="test-key", http_client=http)
        results = svc.autocomplete("padel")
        assert len(results) == 0

    def test_uses_description_when_main_text_missing(self):
        http = _mock_http(
            autocomplete_json={
                "status": "OK",
                "predictions": [
                    {
                        "place_id": "ChIJ_abc",
                        "description": "Full Description Here",
                    }
                ],
            }
        )
        svc = PlacesService(api_key="test-key", http_client=http)
        results = svc.autocomplete("padel")
        assert len(results) == 1
        assert results[0].name == "Full Description Here"
