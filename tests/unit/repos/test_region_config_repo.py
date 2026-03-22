import time
from unittest.mock import MagicMock

import pytest

from app.models.region_config import RegionConfig
from app.repos.region_config_repo import RegionConfigRepo


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset module-level cache before each test."""
    import app.repos.region_config_repo as mod

    mod._cache = None
    mod._cache_ts = 0.0
    yield
    mod._cache = None
    mod._cache_ts = 0.0


def _make_doc_snapshot(data: dict | None, exists: bool = True) -> MagicMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


class TestRegionConfigRepoGet:
    def test_returns_region_config(self):
        client = MagicMock()
        snap = _make_doc_snapshot(
            {
                "mapping": {"101": "athens", "202": "thessaloniki"},
                "version": 1,
            }
        )
        client.collection.return_value.document.return_value.get.return_value = snap

        repo = RegionConfigRepo(client)
        result = repo.get()

        assert isinstance(result, RegionConfig)
        assert result.mapping == {"101": "athens", "202": "thessaloniki"}
        assert result.version == 1
        client.collection.assert_called_with("config")
        client.collection.return_value.document.assert_called_with("regions")

    def test_raises_when_doc_missing(self):
        client = MagicMock()
        snap = _make_doc_snapshot(None, exists=False)
        client.collection.return_value.document.return_value.get.return_value = snap

        repo = RegionConfigRepo(client)
        with pytest.raises(ValueError, match="Region config not found"):
            repo.get()

    def test_caches_result(self):
        client = MagicMock()
        snap = _make_doc_snapshot({"mapping": {"101": "athens"}, "version": 1})
        client.collection.return_value.document.return_value.get.return_value = snap

        repo = RegionConfigRepo(client)
        first = repo.get()
        second = repo.get()

        assert first is second
        # Firestore should only be called once due to caching
        assert client.collection.return_value.document.return_value.get.call_count == 1

    def test_cache_expired_refetches(self):
        client = MagicMock()
        snap = _make_doc_snapshot({"mapping": {"101": "athens"}, "version": 1})
        client.collection.return_value.document.return_value.get.return_value = snap

        repo = RegionConfigRepo(client)
        repo.get()

        # Simulate cache expiration by moving the timestamp far enough into the past.
        # Using time.monotonic() ensures this works even if the monotonic clock
        # value is smaller than the TTL (e.g. in a freshly started CI container).
        import app.repos.region_config_repo as mod

        mod._cache_ts = time.monotonic() - mod._REGION_CONFIG_TTL - 1

        repo.get()
        assert client.collection.return_value.document.return_value.get.call_count == 2

    def test_defaults_version_to_1(self):
        client = MagicMock()
        snap = _make_doc_snapshot({"mapping": {"303": "london"}})
        client.collection.return_value.document.return_value.get.return_value = snap

        repo = RegionConfigRepo(client)
        result = repo.get()
        assert result.version == 1

    def test_empty_mapping(self):
        client = MagicMock()
        snap = _make_doc_snapshot({"version": 2})
        client.collection.return_value.document.return_value.get.return_value = snap

        repo = RegionConfigRepo(client)
        result = repo.get()
        assert result.mapping == {}
        assert result.version == 2
