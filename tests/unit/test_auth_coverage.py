"""Guard: every API route requires Firebase auth except the explicit public set.

Walks each route's dependency tree and asserts ``get_current_user`` is present.
This catches any new endpoint (including an accidentally-shipped debug/seed route)
that forgets auth, satisfying the #377 AC: "anonymous requests get 401 everywhere
except health".
"""

from fastapi.routing import APIRoute

from app.deps import get_current_user
from app.main import app

# The only intentionally-public API routes: the liveness/readiness probes.
# (FastAPI's auto-docs endpoints — /docs, /redoc, /openapi.json — are Starlette
# Routes, not APIRoutes, so they never enter the auth walk below.)
PUBLIC_PATHS = {"/health", "/ready"}


def _dependency_calls(dependant) -> list:
    """Flatten every callable in a route's dependency subtree."""
    calls = []
    for sub in dependant.dependencies:
        if sub.call is not None:
            calls.append(sub.call)
        calls.extend(_dependency_calls(sub))
    return calls


def test_every_route_requires_auth_except_public():
    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in PUBLIC_PATHS:
            continue
        if get_current_user not in _dependency_calls(route.dependant):
            offenders.append((route.path, sorted(route.methods)))
    assert offenders == [], f"routes missing Firebase auth: {offenders}"


def test_no_unexpected_public_routes():
    """The public set is exactly what we expect — no surprise unauthenticated route."""
    public = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if get_current_user not in _dependency_calls(route.dependant):
            public.add(route.path)
    assert public == PUBLIC_PATHS, f"unexpected public routes: {public - PUBLIC_PATHS}"
