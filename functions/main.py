from firebase_admin import initialize_app
from firebase_functions import https_fn

initialize_app()


@https_fn.on_request()
def gsm_ping(_req: https_fn.Request) -> https_fn.Response:
    # Minimal deployable function; replace with trigger wiring in D-series epics.
    return https_fn.Response("ok!", status=200)
