import pytest
from pydantic import ValidationError

from app.models.region_config import RegionConfig


class TestRegionConfig:
    def test_basic_construction(self):
        config = RegionConfig(
            mapping={"101": "athens", "202": "thessaloniki"},
            version=1,
        )
        assert config.mapping == {"101": "athens", "202": "thessaloniki"}
        assert config.version == 1

    def test_empty_mapping(self):
        config = RegionConfig(mapping={}, version=1)
        assert config.mapping == {}

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            RegionConfig(
                mapping={"101": "athens"},
                version=1,
                extra_field="not_allowed",
            )
