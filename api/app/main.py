import logging
import secrets
import time
from fastapi import Depends, FastAPI, Path, status, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.deps import get_current_user, get_role_service
from app.deps import get_firestore_client
from app.security import CurrentUser, require_league_member, require_self
from app.settings import get_settings
from app.dependencies.repos import get_users_repo

app = FastAPI(title="GSM API", version="0.1.0")

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
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Invalid request",
            "details": exc.errors(),
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


@app.get("/me/state")
def get_me_state(
    current_user: CurrentUser = Depends(get_current_user),
):
    # Placeholder for the aggregated "home/me state" payload.
    return {
        "uid": current_user.uid,
        "state": "placeholder",
        "message": "D6 /me/state logic is not implemented yet",
    }


@app.post(
    "/leagues/{league_id}/members",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_league_member(required_role="admin"))],
)
def add_league_member(
    league_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    # Placeholder: real implementation will add a member to the league in Firestore.
    return {"league_id": league_id, "requested_by": current_user.uid}


@app.delete(
    "/leagues/{league_id}/members/{uid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_league_member(required_role="admin"))],
)
def remove_league_member(
    league_id: str,
    uid: str,
    current_user: CurrentUser = Depends(get_current_user),
    role_service=Depends(get_role_service),
):
    # Placeholder: real implementation will remove the member document.
    return {"league_id": league_id, "removed_user": uid, "requested_by": current_user.uid}


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
