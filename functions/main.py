from firebase_admin import initialize_app
from firebase_functions import https_fn
from firebase_functions.firestore_fn import (
    Event,
    DocumentSnapshot,
    on_document_created,
)
from google.cloud import firestore  # type: ignore[import-untyped]

from functions.notification_triggers.on_notification_intent import (
    deliver_notification_intent,
)

initialize_app()


@https_fn.on_request()
def gsm_ping(_req: https_fn.Request) -> https_fn.Response:
    # Minimal deployable function; replace with trigger wiring in D-series epics.
    return https_fn.Response("ok!", status=200)


@on_document_created(document="users/{uid}/notificationIntents/{intentId}")
def on_notification_intent_created(event: Event[DocumentSnapshot | None]) -> None:
    # PUSH-4: deliver a freshly created notification intent via FCM (best-effort).
    snapshot = event.data
    if snapshot is None:
        return
    intent = snapshot.to_dict() or {}
    deliver_notification_intent(
        client=firestore.Client(),
        uid=event.params["uid"],
        intent_id=event.params["intentId"],
        intent=intent,
    )
