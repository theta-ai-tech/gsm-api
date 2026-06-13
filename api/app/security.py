from pydantic import BaseModel

from app import errors
from app.services.role_service import RoleService
from collections.abc import Iterable


class CurrentUser(BaseModel):
    uid: str
    email: str | None = None
    issuer: str | None = None
    picture: str | None = None
    roles: list[str] | None = None
    display_name: str | None = None


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


def require_membership(
    current_user: CurrentUser,
    league_id: str,
    role_service: RoleService,
    required_role: str | None = None,
) -> None:
    required = required_role.lower() if required_role else None
    user_roles = _normalized_roles(current_user.roles)

    if required and required in user_roles:
        return

    # Treat ownership as a shortcut; owner always passes.
    owner_uid = getattr(role_service, "get_league_owner_uid", None)
    if callable(owner_uid):
        league_owner = owner_uid(league_id)
        if league_owner and league_owner == current_user.uid:
            return

    if required:
        member_role = role_service.get_league_member_role(league_id, current_user.uid)
        if member_role and member_role.lower() == required:
            return
    else:
        if role_service.is_league_member(league_id, current_user.uid):
            return

    raise errors.forbidden("You are not allowed to access this league")


def require_league_member(required_role: str | None = None):
    from fastapi import Depends

    from app.deps import get_current_user, get_role_service

    def dependency(
        league_id: str,
        current_user: CurrentUser = Depends(get_current_user),
        role_service: RoleService = Depends(get_role_service),
    ) -> None:
        require_membership(
            current_user=current_user,
            league_id=league_id,
            role_service=role_service,
            required_role=required_role,
        )

    return dependency
