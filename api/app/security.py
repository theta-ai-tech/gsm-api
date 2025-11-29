from fastapi import HTTPException
from pydantic import BaseModel

from app import errors


class CurrentUser(BaseModel):
    uid: str
    email: str | None = None
    issuer: str | None = None
    picture: str | None = None
    roles: list[str] | None = None


def require_self(resource_uid: str, current_user: CurrentUser) -> None:
    if current_user.uid != resource_uid:
        raise errors.forbidden("You do not own this resource")


def require_roles(current_user: CurrentUser, allowed_roles: set[str]) -> None:
    roles = set(current_user.roles or [])
    if not roles.intersection(allowed_roles):
        raise errors.forbidden("You are not allowed to access this resource")

