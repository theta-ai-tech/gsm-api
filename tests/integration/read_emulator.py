import os
from google.cloud import firestore

assert os.environ.get("FIRESTORE_EMULATOR_HOST"), "Set FIRESTORE_EMULATOR_HOST"
db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT", "gsm-dev-fake"))

snap = db.collection("users").document("abc123").get()
print("Found:", snap.exists, snap.to_dict())
