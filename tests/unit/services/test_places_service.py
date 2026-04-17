"""Unit tests for PlacesService.

Uses a mocked httpx.Client to avoid real Google API calls.
"""

from __future__ import annotations

from unittest.mock import Mock

import httpx
import pytest

from app.services.places_service import (
    PlacesService,
    PlacesUpstreamError,
    _result_cache_get,
    _result_cache_put,
    clear_cache,
)


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

    def test_error_status_raises_upstream_error(self):
        http = _mock_http(autocomplete_json={"status": "REQUEST_DENIED"})
        svc = PlacesService(api_key="test-key", http_client=http)
        with pytest.raises(PlacesUpstreamError, match="REQUEST_DENIED"):
            svc.autocomplete("padel")

    def test_http_error_raises_upstream_error(self):
        http = Mock()
        http.get = Mock(side_effect=httpx.ConnectError("connection refused"))
        svc = PlacesService(api_key="test-key", http_client=http)
        with pytest.raises(PlacesUpstreamError, match="unreachable"):
            svc.autocomplete("padel")

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

    def test_all_details_fail_raises_upstream_error(self):
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
        with pytest.raises(PlacesUpstreamError, match="all predictions"):
            svc.autocomplete("padel")

    def test_partial_details_failure_returns_successful_results(self):
        """When some detail lookups fail, return the ones that succeeded."""
        client = Mock()
        ac_resp = Mock()
        ac_resp.json.return_value = {
            "status": "OK",
            "predictions": [
                {"place_id": "ChIJ_ok", "structured_formatting": {"main_text": "Good"}},
                {"place_id": "ChIJ_bad", "structured_formatting": {"main_text": "Bad"}},
            ],
        }
        ac_resp.raise_for_status = Mock()

        ok_det = Mock()
        ok_det.json.return_value = {
            "status": "OK",
            "result": {"geometry": {"location": {"lat": 37.93, "lng": 23.68}}},
        }
        ok_det.raise_for_status = Mock()

        bad_det = Mock()
        bad_det.json.return_value = {"status": "NOT_FOUND"}
        bad_det.raise_for_status = Mock()

        call_count = {"n": 0}

        def _route(url: str, **kwargs):
            if "autocomplete" in url:
                return ac_resp
            call_count["n"] += 1
            return ok_det if call_count["n"] == 1 else bad_det

        client.get = Mock(side_effect=_route)
        svc = PlacesService(api_key="test-key", http_client=client)
        results = svc.autocomplete("test")
        assert len(results) == 1
        assert results[0].place_id == "ChIJ_ok"

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


class TestLRUCache:
    def test_cache_hit_refreshes_recency(self):
        """Accessing a cached key should move it to the end (most recent)."""
        _result_cache_put("a", [])
        _result_cache_put("b", [])
        # Access "a" to refresh its recency
        _result_cache_get("a")
        _result_cache_put("c", [])
        # If cache size were 3, all three should still be present
        assert _result_cache_get("a") is not None
        assert _result_cache_get("b") is not None
        assert _result_cache_get("c") is not None

    def test_lru_eviction_order(self):
        """Least recently used key should be evicted first."""

        # Fill cache to max size
        from app.constants import VENUE_SEARCH_CACHE_MAX_SIZE

        for i in range(VENUE_SEARCH_CACHE_MAX_SIZE):
            _result_cache_put(f"key_{i}", [])

        # Access key_0 to make it most recently used
        _result_cache_get("key_0")

        # Insert one more — should evict key_1 (least recently used), not key_0
        _result_cache_put("new_key", [])

        assert _result_cache_get("key_0") is not None  # refreshed, still present
        assert _result_cache_get("key_1") is None  # evicted (was LRU)
        assert _result_cache_get("new_key") is not None  # just inserted
