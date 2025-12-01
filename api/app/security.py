from pydantic import BaseModel

from app import errors


class CurrentUser(BaseModel):
    uid: str
    email: str | None = None
    issuer: str | None = None
    picture: str | None = None
    roles: list[str] | None = None


def is_owner(current_user: CurrentUser, target_uid: str) -> bool:
    return current_user.uid == target_uid


def require_self(current_user: CurrentUser, target_uid: str) -> None:
    if not is_owner(current_user, target_uid):
        raise errors.forbidden("You do not own this resource")


def require_roles(current_user: CurrentUser, allowed_roles: set[str]) -> None:
    roles = set(current_user.roles or [])
    if not roles.intersection(allowed_roles):
        raise errors.forbidden("You are not allowed to access this resource")
