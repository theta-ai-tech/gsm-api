from typing import Annotated

import firebase_admin  # type: ignore[import-untyped]
from fastapi import Header, Depends
from firebase_admin import auth as firebase_auth  # type: ignore[import-untyped]
from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app import errors
from app.services.role_service import RoleService
from app.security import CurrentUser
from app.settings import Settings, get_settings


def _get_firebase_app(settings: Settings) -> firebase_admin.App:
    # In Cloud Run, ADC via Workload Identity provides credentials; no JSON key files required.
    try:
        return firebase_admin.get_app()
    except ValueError:
        # Lazily initialize so imports remain lightweight in tests and tooling.
        # Uses ADC/service-account credentials unless Auth emulator is set.
        options: dict[str, str] = {"projectId": settings.project_id}
        if settings.auth_emulator_host:
            # Explicit host for emulator flow; avoid None values to keep types strict.
            options["authDomain"] = settings.auth_emulator_host
        return firebase_admin.initialize_app(options=options)


def _parse_authorization_header(authorization: str | None) -> str:
    if not authorization:
        raise errors.unauthorized("Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise errors.unauthorized("Invalid Authorization header format")
    return token


def _verify_token(id_token: str, settings: Settings) -> dict:
    try:
        decoded = firebase_auth.verify_id_token(
            id_token,
            app=_get_firebase_app(settings),
            check_revoked=not bool(settings.auth_emulator_host),
        )
    except firebase_auth.InvalidIdTokenError as exc:
        raise errors.unauthorized("Invalid Firebase ID token") from exc

    if decoded.get("aud") != settings.project_id or decoded.get("iss") != settings.issuer:
        raise errors.unauthorized("Token not issued for this project")

    return decoded


def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> CurrentUser:
    settings = get_settings()
    token = _parse_authorization_header(authorization)
    decoded = _verify_token(token, settings)
    roles = decoded.get("roles") or decoded.get("role")
    if isinstance(roles, str):
        roles = [roles]
    return CurrentUser(
        uid=decoded["uid"],
        email=decoded.get("email"),
        issuer=decoded.get("iss"),
        picture=decoded.get("picture"),
        roles=roles,
        display_name=decoded.get("name"),
    )


def get_firestore_client() -> firestore.Client:
    settings = get_settings()
    # Firestore client also uses ADC in Cloud Run; no explicit key files are read here.
    return firestore.Client(project=settings.project_id)


def get_role_service(
    db: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> RoleService:
    return RoleService(db=db)
