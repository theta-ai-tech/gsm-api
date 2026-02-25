import os
import sys
from pathlib import Path

import pytest
from google.cloud import firestore

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


@pytest.fixture(scope="session")
def firestore_client() -> firestore.Client:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "gsm-dev-fake")
    return firestore.Client(project=project)


@pytest.fixture
def seeded_firestore(firestore_client: firestore.Client) -> firestore.Client:
    assert os.environ.get("FIRESTORE_EMULATOR_HOST"), (
        "Set FIRESTORE_EMULATOR_HOST for integration tests"
    )
    from tools.seed_firestore import seed_all

    seed_all(firestore_client)
    return firestore_client


@pytest.fixture(autouse=True)
def _cleanup(db, request):
    if request.node.get_closest_marker("seeded"):
        yield
        return
    # runs before/after each test (adjust to your needs)
    yield
    # cleanup collections you touch in integration tests
    # e.g., delete test docs from users collection
    for doc in db.collection("users").stream():
        db.collection("users").document(doc.id).delete()
