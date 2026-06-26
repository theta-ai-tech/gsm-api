import logging
import secrets
import time
from fastapi import Depends, FastAPI, Path, status, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.deps import get_current_user
from app.deps import get_firestore_client
from app.routers.clubhouse import router as clubhouse_router
from app.routers.device_tokens import router as device_tokens_router
from app.routers.improve import router as improve_router
from app.routers.lab import router as lab_router
from app.routers.matches import router as matches_router
from app.routers.onboarding import router as onboarding_router
from app.routers.play import router as play_router
from app.routers.leagues import router as leagues_router
from app.routers.venues import router as venues_router
from app.security import CurrentUser, require_self
from app.settings import get_settings
from app.dependencies.repos import get_users_repo

# Ensure app-level loggers (including log_analytics_event) write to stdout.
# Uvicorn configures only its own loggers; without this the root logger has
# no handler and logger.info() calls are silently dropped in all environments.
logging.basicConfig(level=logging.INFO, force=True)

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
app.include_router(device_tokens_router)

settings = get_settings()
logger = logging.getLogger("gsm-api")
SLOW_REQUEST_THRESHOLD_MS = 500

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
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
    detail = exc.detail
    if isinstance(detail, dict):
        payload = detail
    else:
        payload = {"detail": detail}
    return JSONResponse(status_code=exc.status_code, content=payload)


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
