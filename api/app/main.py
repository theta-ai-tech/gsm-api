import json
import logging
import secrets
import time
from fastapi import Depends, FastAPI, Path, status, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError

from app.deps import get_current_user
from app.deps import get_firestore_client
from app.observability import (
    bodies_logging_enabled,
    log_error_response,
    log_request_response_bodies,
)
from app.routers.account import router as account_router
from app.routers.clubhouse import router as clubhouse_router
from app.routers.device_tokens import router as device_tokens_router
from app.routers.improve import router as improve_router
from app.routers.lab import router as lab_router
from app.routers.matches import router as matches_router
from app.routers.onboarding import router as onboarding_router
from app.routers.play import router as play_router
from app.routers.leagues import router as leagues_router
from app.routers.players import router as players_router
from app.routers.venues import router as venues_router
from app.security import CurrentUser, require_self
from app.settings import get_settings, sanitize_cors_origins
from app.telemetry import setup_cloud_logging
from app.dependencies.repos import get_users_repo

# Ensure app-level loggers (including log_analytics_event) write to stdout.
# Uvicorn configures only its own loggers; without this the root logger has
# no handler and logger.info() calls are silently dropped in all environments.
logging.basicConfig(level=logging.INFO, force=True)

# In production (Cloud Run), route logs through Cloud Logging so ERROR entries
# with tracebacks surface in Error Reporting. No-op in tests/local (gated).
setup_cloud_logging()

app = FastAPI(title="GSM API", version="0.1.0")

# Include routers
app.include_router(onboarding_router)
app.include_router(play_router)
app.include_router(improve_router)
app.include_router(lab_router)
app.include_router(matches_router)
app.include_router(clubhouse_router)
app.include_router(venues_router)
app.include_router(leagues_router)
app.include_router(players_router)
app.include_router(device_tokens_router)
app.include_router(account_router)

settings = get_settings()
logger = logging.getLogger("gsm-api")
SLOW_REQUEST_THRESHOLD_MS = 500

# CORS is locked to an explicit allow-list. The iOS client is not a browser and
# needs no CORS; origins are only for browser tooling (e.g. an internal dashboard).
# A wildcard is never allowed — it is stripped and logged.
_cors_origins, _cors_wildcard_stripped = sanitize_cors_origins(settings.cors_origins)
if _cors_wildcard_stripped:
    logger.warning(
        json.dumps(
            {
                "event": "cors_wildcard_stripped",
                "detail": "'*' origin ignored; set explicit origins",
            }
        )
    )
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.middleware("http")
async def body_logging_middleware(request: Request, call_next):
    if not bodies_logging_enabled():
        return await call_next(request)

    request_body = await request.body()

    # Replay the consumed body for downstream handlers: BaseHTTPMiddleware's
    # call_next re-reads from the receive channel, which is now exhausted.
    async def receive() -> dict:
        return {"type": "http.request", "body": request_body, "more_body": False}

    request = Request(request.scope, receive)

    response = await call_next(request)

    response_body = b"".join([chunk async for chunk in response.body_iterator])
    log_request_response_bodies(
        request,
        request_body,
        response_body,
        response.status_code,
        response.headers.get("content-type", ""),
    )
    return Response(
        content=response_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers["Server"] = "gsm-api"
    return response


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or secrets.token_hex(8)
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000

    if duration_ms >= SLOW_REQUEST_THRESHOLD_MS:
        logger.warning(
            "slow_request",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "threshold_ms": SLOW_REQUEST_THRESHOLD_MS,
                "request_id": getattr(request.state, "request_id", None),
            },
        )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    log_error_response(request, exc.status_code, exc.detail)
    detail = exc.detail
    if isinstance(detail, dict):
        payload = detail
    else:
        payload = {"detail": detail}
    # Forward response headers set on the exception (e.g. Retry-After on a 429,
    # WWW-Authenticate on a 401). Without this they would be silently dropped.
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    def _sanitize(obj):
        """Recursively convert Exception objects to strings so the payload is JSON-safe.

        Pydantic v2 model_validator errors embed the raw ValueError in
        ctx["error"], which is not JSON-serializable. This handles that case
        (and any future nesting) regardless of the exact error structure.
        """
        if isinstance(obj, Exception):
            return str(obj)
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_sanitize(v) for v in obj]
        return obj

    details = [_sanitize(err) for err in exc.errors()]
    logged_details = [{k: err.get(k) for k in ("loc", "msg", "type")} for err in details]
    log_error_response(request, status.HTTP_422_UNPROCESSABLE_CONTENT, logged_details)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": "validation_error",
            "message": "Invalid request",
            "details": details,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log_error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        f"unhandled_exception: {type(exc).__name__}",
        exc=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal_error", "message": "Something went wrong"},
    )


@app.get("/health", openapi_extra={"security": []})
def health():
    return {"status": "ok", "service": "gsm-api", "version": app.version, "ok": True}


@app.get("/ready", openapi_extra={"security": []})
def ready(request: Request):
    try:
        db = get_firestore_client()
        db.collection("ready").limit(1).get()
    except Exception as exc:  # pragma: no cover - exercised via tests
        logger.error(
            "readiness_failure",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "detail": "firestore_unavailable",
            },
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "degraded",
                "firestore": "error",
                "detail": "firestore_unavailable",
                "message": str(exc),
            },
        )

    return {"status": "ok", "firestore": "ok", "service": "gsm-api", "version": app.version}


@app.get("/users/{uid}")
def get_user(
    uid: str = Path(..., min_length=1),
    current_user: CurrentUser = Depends(get_current_user),
    users_repo=Depends(get_users_repo),
):
    require_self(current_user, uid)
    profile = users_repo.get_private_profile(uid)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return profile


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description,
    )
    # Add bearer scheme so Swagger shows Authorize button/lock icons for protected routes.
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {}).update(
        {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Firebase ID token (Authorization: Bearer <token>)",
            }
        }
    )
    # Set global security requirement so protected routes show lock + Authorize button.
    openapi_schema.setdefault("security", [{"bearerAuth": []}])

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[assignment]
