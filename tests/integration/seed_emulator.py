# tests/integration/seed_emulator.py
import os
from google.cloud import firestore

# Safety: ensure we're on the emulator
host = os.environ.get("FIRESTORE_EMULATOR_HOST")
assert host, (
    "FIRESTORE_EMULATOR_HOST not set. Run via `make api-dev-emu` or `make seed`."
)

project = os.environ.get("GOOGLE_CLOUD_PROJECT", "gsm-dev-fake")
db = firestore.Client(project=project)

doc = {
    "name": "Alex Padel",
    "email": "alex@example.com",
    "profileUrl": None,
    "phone": "+30 690 000 0000",
    "rankings": {"padel": {"pts": 980, "globalRanking": 120}},
    "preferences": {"area": 42, "level": {"padel": "advanced"}, "sports": ["padel"]},
    "leagueSummaries": [],
    "upcomingMatchIds": [],
    "recentCompletedMatchIds": [],
}

db.collection("users").document("abc123").set(doc)
print("✅ Seeded users/abc123")
