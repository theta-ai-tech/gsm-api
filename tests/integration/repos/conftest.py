import os
import sys
from pathlib import Path

import pytest
from google.cloud import firestore  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytestmark = [pytest.mark.integration, pytest.mark.seeded]


@pytest.fixture(scope="session", autouse=True)
def _require_emulator():
    assert os.environ.get("FIRESTORE_EMULATOR_HOST"), (
        "FIRESTORE_EMULATOR_HOST must be set for repo tests"
    )
    assert os.environ.get("GOOGLE_CLOUD_PROJECT"), (
        "GOOGLE_CLOUD_PROJECT must be set for repo tests"
    )


@pytest.fixture(scope="session")
def firestore_client():
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "gsm-dev-f70d0")
    client = firestore.Client(project=project)
    from tools.seed_firestore import seed_all

    seed_all(client)
    return client
