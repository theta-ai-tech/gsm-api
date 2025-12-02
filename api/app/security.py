from pydantic import BaseModel

from app import errors
from collections.abc import Iterable


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


def _normalized_roles(roles: Iterable[str] | None) -> set[str]:
    return {role.lower() for role in roles or []}


def require_roles(current_user: CurrentUser, roles: Iterable[str]) -> None:
    required = _normalized_roles(roles)
    if not required:
        return

    current = _normalized_roles(current_user.roles)
    if not required.issubset(current):
        raise errors.forbidden("Missing required role")


def require_any_role(current_user: CurrentUser, roles: Iterable[str]) -> None:
    required = _normalized_roles(roles)
    if not required:
        return

    current = _normalized_roles(current_user.roles)
    if not current.intersection(required):
        raise errors.forbidden("Missing required role")


def is_admin(current_user: CurrentUser) -> bool:
    admin_aliases = {"admin", "administrator", "superadmin", "super-admin"}
    return bool(_normalized_roles(current_user.roles).intersection(admin_aliases))
