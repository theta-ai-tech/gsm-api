import os
import pytest
from google.cloud import firestore

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session", autouse=True)
def _require_emulator():
    assert os.environ.get("FIRESTORE_EMULATOR_HOST"), (
        "Set FIRESTORE_EMULATOR_HOST for integration tests"
    )


@pytest.fixture(scope="session")
def db():
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "gsm-dev-fake")
    return firestore.Client(project=project)


@pytest.fixture(autouse=True)
def _cleanup(db):
    # runs before/after each test (adjust to your needs)
    yield
    # cleanup collections you touch in integration tests
    # e.g., delete test docs from users collection
    for doc in db.collection("users").stream():
        db.collection("users").document(doc.id).delete()
