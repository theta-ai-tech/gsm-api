from tools.seed_mapping import region_config_to_firestore_doc


class TestRegionConfigToFirestoreDoc:
    def test_basic_mapping(self):
        mapping = {"101": "athens", "202": "thessaloniki"}
        doc = region_config_to_firestore_doc(mapping)
        assert doc == {
            "mapping": {"101": "athens", "202": "thessaloniki"},
            "version": 1,
        }

    def test_custom_version(self):
        doc = region_config_to_firestore_doc({"303": "london"}, version=2)
        assert doc["version"] == 2
        assert doc["mapping"] == {"303": "london"}

    def test_empty_mapping(self):
        doc = region_config_to_firestore_doc({})
        assert doc == {"mapping": {}, "version": 1}
