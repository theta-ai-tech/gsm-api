from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, Sequence, TypeVar, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.constants import DIVISION_TARGET_SIZE, PARTNER_INVITE_UID_PREFIX
from app.models import (
    Division,
    League,
    LeagueMember,
    LeagueTeam,
    LeagueTeamPartnerInvite,
    RatingRange,
    StandingsEntry,
)
from app.models.enums import (
    LeagueFormatEnum,
    LeagueMemberStatusEnum,
    LeagueRoleEnum,
    LeagueStatusEnum,
    LeagueTeamStatusEnum,
    PlayNotificationIntentTypeEnum,
)
from app.models.notification import PlayNotificationIntent
from app.repos.divisions_repo import DivisionsRepo
from app.repos.leagues_repo import LeaguesRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.notification_intent_repo import NotificationIntentRepo
from app.repos.users_repo import UsersRepo
from app.utils.contact import normalize_email, partner_placeholder_uid

logger = logging.getLogger(__name__)


class LeagueKickoffError(ValueError):
    pass


class LeagueKickoffNotFoundError(LeagueKickoffError):
    pass


class LeagueKickoffConflictError(LeagueKickoffError):
    pass


class LeagueTeamError(ValueError):
    """Base error for doubles-team join lifecycle operations."""


class LeagueTeamValidationError(LeagueTeamError):
    """Invalid request (→ 400)."""


class LeagueTeamForbiddenError(LeagueTeamError):
    """Caller is not authorized for this team action (→ 403)."""


class LeagueTeamNotFoundError(LeagueTeamError):
    """League, team, or partner does not exist (→ 404)."""


class LeagueTeamConflictError(LeagueTeamError):
    """State conflict — already member/teamed, wrong status, full (→ 409)."""


@dataclass(frozen=True)
class RankedLeagueMember:
    member: LeagueMember
    pts: int


@dataclass(frozen=True)
class RankedLeagueTeam:
    """A doubles team ranked for division seeding.

    ``pts`` is the integer mean of the two partners' per-sport ranking points —
    the documented team-rating rule for doubles division seeding.
    """

    team: LeagueTeam
    pts: int


RankedT = TypeVar("RankedT", RankedLeagueMember, RankedLeagueTeam)


@dataclass(frozen=True)
class DivisionSplit(Generic[RankedT]):
    division_id: str
    name: str
    ordinal: int
    members: list[RankedT]
    rating_min: int
    rating_max: int


@dataclass(frozen=True)
class LeagueKickoffResult:
    league_id: str
    divisions: list[Division]
    already_kicked_off: bool = False


def split_into_divisions(
    sorted_members: Sequence[RankedT],
    target_size: int = DIVISION_TARGET_SIZE,
    max_divisions: int | None = None,
) -> list[DivisionSplit[RankedT]]:
    """Split a pre-sorted list of ranked units into contiguous divisions.

    The unit is a member for singles leagues and a whole team for doubles —
    teammates are never split across divisions because the team is the unit.
    """
    members = list(sorted_members)
    if not members:
        return []
    if target_size <= 0:
        raise ValueError("target_size must be positive")

    if len(members) < 5:
        division_count = 1
    else:
        division_count = max(1, round(len(members) / target_size))
    if max_divisions is not None and max_divisions > 0:
        division_count = min(division_count, max_divisions)

    base_size, remainder = divmod(len(members), division_count)
    splits: list[DivisionSplit[RankedT]] = []
    offset = 0
    for index in range(division_count):
        chunk_size = base_size + (1 if index < remainder else 0)
        chunk = members[offset : offset + chunk_size]
        offset += chunk_size
        ordinal = index + 1
        pts_values = [item.pts for item in chunk]
        splits.append(
            DivisionSplit(
                division_id=f"div-{ordinal}",
                name=f"Division {ordinal}",
                ordinal=ordinal,
                members=chunk,
                rating_min=min(pts_values),
                rating_max=max(pts_values),
            )
        )
    return splits


class LeagueService:
    def __init__(
        self,
        leagues_repo: LeaguesRepo,
        firestore_client: firestore.Client,
        users_repo: UsersRepo | None = None,
        divisions_repo: DivisionsRepo | None = None,
        notification_intent_repo: NotificationIntentRepo | None = None,
        matches_repo: MatchesRepo | None = None,
    ):
        self.leagues_repo = leagues_repo
        self.client = firestore_client
        self.users_repo = users_repo or UsersRepo(firestore_client)
        self.divisions_repo = divisions_repo or DivisionsRepo(firestore_client)
        self.notification_intent_repo = notification_intent_repo
        self.matches_repo = matches_repo or MatchesRepo(firestore_client)

    def _emit_notification_intent(self, intent: PlayNotificationIntent) -> None:
        if self.notification_intent_repo is None:
            return
        try:
            self.notification_intent_repo.add_intent(intent)
        except Exception:
            logger.exception("Failed to write league notification intent (non-fatal)")

    def _user_display_name(self, uid: str, fallback: str | None = None) -> str:
        user_doc = self.users_repo.get_user_doc(uid) or {}
        return self._display_name_from_doc(user_doc, uid, fallback)

    @staticmethod
    def _display_name_from_doc(user_doc: dict, uid: str, fallback: str | None = None) -> str:
        name = user_doc.get("name")
        if isinstance(name, str) and name.strip():
            return name
        return fallback or uid

    def _transition_pending_team(
        self, league_id: str, team_id: str, new_status: LeagueTeamStatusEnum, action: str
    ) -> None:
        """Transactionally move a PENDING team to a terminal status.

        The status re-check inside the transaction guards against a racing
        accept: without it, a blind update could stomp `status` on a team the
        partner just accepted, leaving orphaned active members and an inflated
        `currentPlayers` count.
        """
        team_ref = (
            self.client.collection("leagues")
            .document(league_id)
            .collection("teams")
            .document(team_id)
        )
        transaction = self.client.transaction()

        @firestore.transactional
        def _transition_txn(txn: firestore.Transaction) -> None:
            team_doc = cast(firestore.DocumentSnapshot, team_ref.get(transaction=txn))
            if not team_doc.exists:
                raise LeagueTeamNotFoundError(f"Team {team_id!r} not found in league {league_id!r}")
            status_val = (team_doc.to_dict() or {}).get("status")
            if status_val != LeagueTeamStatusEnum.PENDING.value:
                raise LeagueTeamConflictError(f"Team {team_id!r} is not pending; cannot {action}")
            txn.update(team_ref, {"status": new_status.value})

        _transition_txn(transaction)

    def join_league(
        self, league_id: str, uid: str, display_name: str | None = None
    ) -> LeagueMember:
        # Fast pre-checks (non-transactional — stable data)
        league = self.leagues_repo.get_by_id(league_id)
        if league is None:
            raise ValueError(f"League {league_id!r} not found")

        if league.status not in (LeagueStatusEnum.OPEN, LeagueStatusEnum.UPCOMING):
            raise ValueError(
                f"Cannot join league with status {league.status!r}; must be OPEN or UPCOMING"
            )

        now = datetime.now(timezone.utc)
        member_data: dict = {
            "uid": uid,
            "role": LeagueRoleEnum.PLAYER.value,
            "status": LeagueMemberStatusEnum.ACTIVE.value,
            "joinedAt": now,
            "stats": None,
            "divisionId": None,
        }
        if display_name is not None:
            member_data["displayName"] = display_name

        transaction = self.client.transaction()

        @firestore.transactional
        def _join_txn(txn: firestore.Transaction) -> None:
            member_ref = (
                self.client.collection("leagues")
                .document(league_id)
                .collection("members")
                .document(uid)
            )
            league_ref = self.client.collection("leagues").document(league_id)

            # Reads must come before writes in a Firestore transaction
            member_doc = member_ref.get(transaction=txn)
            league_doc = cast(firestore.DocumentSnapshot, league_ref.get(transaction=txn))

            if member_doc.exists:
                raise ValueError(f"User {uid!r} is already a member of league {league_id!r}")

            if league_doc.exists:
                data = league_doc.to_dict() or {}
                status_val = data.get("status")
                if status_val not in (LeagueStatusEnum.OPEN.value, LeagueStatusEnum.UPCOMING.value):
                    raise ValueError(
                        f"Cannot join league with status {status_val!r}; must be OPEN or UPCOMING"
                    )
                current = data.get("currentPlayers")
                max_p = data.get("maxPlayers")
                if current is not None and max_p is not None and current >= max_p:
                    raise ValueError(f"League {league_id!r} is at full capacity")

            txn.set(member_ref, member_data)
            txn.update(league_ref, {"currentPlayers": firestore.Increment(1)})

        _join_txn(transaction)

        return LeagueMember(
            uid=uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=now,
            stats=None,
            display_name=display_name,
            division_id=None,
        )

    def invite_team(
        self,
        league_id: str,
        captain_uid: str,
        partner_uid: str,
        captain_display_name: str | None = None,
    ) -> LeagueTeam:
        # Fast pre-checks (non-transactional — stable data).
        league = self.leagues_repo.get_by_id(league_id)
        if league is None:
            raise LeagueTeamNotFoundError(f"League {league_id!r} not found")
        if league.format != LeagueFormatEnum.DOUBLES:
            raise LeagueTeamValidationError(f"League {league_id!r} is not a doubles league")
        if league.status not in (LeagueStatusEnum.OPEN, LeagueStatusEnum.UPCOMING):
            raise LeagueTeamConflictError(
                f"Cannot join league with status {league.status!r}; must be OPEN or UPCOMING"
            )
        if partner_uid == captain_uid:
            raise LeagueTeamValidationError("Cannot invite yourself as a partner")

        partner_doc = self.users_repo.get_user_doc(partner_uid)
        if partner_doc is None:
            raise LeagueTeamNotFoundError(f"Partner {partner_uid!r} not found")

        for uid in (captain_uid, partner_uid):
            if self.leagues_repo.get_member(league_id, uid) is not None:
                raise LeagueTeamConflictError(
                    f"User {uid!r} is already a member of league {league_id!r}"
                )
            # Non-transactional check for one-team-per-user: Firestore's Python
            # client cannot run queries inside a transaction, so team-duplication
            # is enforced here in the pre-check only.
            existing_teams = self.leagues_repo.find_teams_for_user(
                league_id,
                uid,
                [LeagueTeamStatusEnum.PENDING, LeagueTeamStatusEnum.ACTIVE],
            )
            if existing_teams:
                raise LeagueTeamConflictError(
                    f"User {uid!r} is already in a team in league {league_id!r}"
                )

        captain_name = self._user_display_name(captain_uid, captain_display_name)
        # Reuse the partner doc fetched for the existence check above.
        partner_name = self._display_name_from_doc(partner_doc, partner_uid)
        team_name = f"{captain_name} / {partner_name}"

        team_ref = (
            self.client.collection("leagues").document(league_id).collection("teams").document()
        )
        team_id = team_ref.id
        now = datetime.now(timezone.utc)
        team_data: dict[str, Any] = {
            "status": LeagueTeamStatusEnum.PENDING.value,
            "captainUid": captain_uid,
            "partnerUid": partner_uid,
            "memberUids": [captain_uid, partner_uid],
            "name": team_name,
            "createdAt": now,
        }

        transaction = self.client.transaction()

        @firestore.transactional
        def _invite_txn(txn: firestore.Transaction) -> None:
            league_ref = self.client.collection("leagues").document(league_id)
            members_col = league_ref.collection("members")
            captain_member_ref = members_col.document(captain_uid)
            partner_member_ref = members_col.document(partner_uid)

            # Reads must come before writes.
            league_doc = cast(firestore.DocumentSnapshot, league_ref.get(transaction=txn))
            captain_member_doc = captain_member_ref.get(transaction=txn)
            partner_member_doc = partner_member_ref.get(transaction=txn)

            if league_doc.exists:
                status_val = (league_doc.to_dict() or {}).get("status")
                if status_val not in (
                    LeagueStatusEnum.OPEN.value,
                    LeagueStatusEnum.UPCOMING.value,
                ):
                    raise LeagueTeamConflictError(
                        f"Cannot join league with status {status_val!r}; must be OPEN or UPCOMING"
                    )
            if captain_member_doc.exists:
                raise LeagueTeamConflictError(
                    f"User {captain_uid!r} is already a member of league {league_id!r}"
                )
            if partner_member_doc.exists:
                raise LeagueTeamConflictError(
                    f"User {partner_uid!r} is already a member of league {league_id!r}"
                )

            txn.set(team_ref, team_data)

        _invite_txn(transaction)

        self._emit_notification_intent(
            PlayNotificationIntent(
                type=PlayNotificationIntentTypeEnum.LEAGUE_TEAM_INVITE,
                target_uid=partner_uid,
                title="League team invite",
                body=f"{captain_name} invited you to team up in {league.name}",
                dedupe_key=f"league_team_invite:{league_id}:{team_id}",
                created_at=now,
            )
        )

        return LeagueTeam(
            team_id=team_id,
            status=LeagueTeamStatusEnum.PENDING,
            captain_uid=captain_uid,
            partner_uid=partner_uid,
            member_uids=[captain_uid, partner_uid],
            name=team_name,
            created_at=now,
        )

    def invite_placeholder_team(
        self,
        league_id: str,
        captain_uid: str,
        partner_name: str,
        partner_email: str,
        partner_phone: str | None = None,
        captain_display_name: str | None = None,
    ) -> LeagueTeam:
        """Form a doubles team with an UNREGISTERED partner (email placeholder).

        The team goes ACTIVE immediately (no accept gate) and consumes 2 capacity
        slots. The normalized email is the durable match key: if someone later
        registers with it, ``claim_partner_invites`` backfills the real uid.
        """
        # Fast pre-checks (non-transactional — stable data).
        league = self.leagues_repo.get_by_id(league_id)
        if league is None:
            raise LeagueTeamNotFoundError(f"League {league_id!r} not found")
        if league.format != LeagueFormatEnum.DOUBLES:
            raise LeagueTeamValidationError(f"League {league_id!r} is not a doubles league")
        if league.status not in (LeagueStatusEnum.OPEN, LeagueStatusEnum.UPCOMING):
            raise LeagueTeamConflictError(
                f"Cannot join league with status {league.status!r}; must be OPEN or UPCOMING"
            )

        invite_name = partner_name.strip()
        if not invite_name:
            raise LeagueTeamValidationError("Partner name is required")
        email_norm = normalize_email(partner_email)
        if not email_norm:
            raise LeagueTeamValidationError("Partner email is required")

        captain_doc = self.users_repo.get_user_doc(captain_uid) or {}
        captain_email = captain_doc.get("email")
        if isinstance(captain_email, str) and normalize_email(captain_email) == email_norm:
            raise LeagueTeamValidationError("Cannot invite yourself as a partner")

        registered_uid = self.users_repo.find_uid_by_email(email_norm)
        if registered_uid is not None:
            raise LeagueTeamConflictError(
                "A registered user already has this email; use partner_uid instead"
            )

        # Captain must not already be a member or in another team in this league.
        if self.leagues_repo.get_member(league_id, captain_uid) is not None:
            raise LeagueTeamConflictError(
                f"User {captain_uid!r} is already a member of league {league_id!r}"
            )
        existing_teams = self.leagues_repo.find_teams_for_user(
            league_id,
            captain_uid,
            [LeagueTeamStatusEnum.PENDING, LeagueTeamStatusEnum.ACTIVE],
        )
        if existing_teams:
            raise LeagueTeamConflictError(
                f"User {captain_uid!r} is already in a team in league {league_id!r}"
            )

        placeholder_uid = partner_placeholder_uid(email_norm)
        captain_name = self._display_name_from_doc(captain_doc, captain_uid, captain_display_name)
        team_name = f"{captain_name} / {invite_name}"

        team_ref = (
            self.client.collection("leagues").document(league_id).collection("teams").document()
        )
        team_id = team_ref.id
        now = datetime.now(timezone.utc)
        invite_map: dict[str, Any] = {
            "name": invite_name,
            "emailNormalized": email_norm,
            "phone": partner_phone,
            "invitedAt": now,
        }
        team_data: dict[str, Any] = {
            "status": LeagueTeamStatusEnum.ACTIVE.value,
            "captainUid": captain_uid,
            "partnerUid": None,
            "partnerPlaceholderUid": placeholder_uid,
            "partnerInvite": invite_map,
            "memberUids": [captain_uid, placeholder_uid],
            "name": team_name,
            "createdAt": now,
            "acceptedAt": now,
        }

        lookup_id = f"{placeholder_uid}__{league_id}"
        lookup_ref = self.client.collection("partnerInvites").document(lookup_id)

        transaction = self.client.transaction()

        @firestore.transactional
        def _invite_txn(txn: firestore.Transaction) -> None:
            league_ref = self.client.collection("leagues").document(league_id)
            members_col = league_ref.collection("members")
            captain_member_ref = members_col.document(captain_uid)
            placeholder_member_ref = members_col.document(placeholder_uid)

            # Reads before writes.
            league_doc = cast(firestore.DocumentSnapshot, league_ref.get(transaction=txn))
            captain_member_doc = captain_member_ref.get(transaction=txn)
            placeholder_member_doc = placeholder_member_ref.get(transaction=txn)
            lookup_doc = lookup_ref.get(transaction=txn)

            if not league_doc.exists:
                raise LeagueTeamNotFoundError(f"League {league_id!r} not found")
            league_data = league_doc.to_dict() or {}
            status_val = league_data.get("status")
            if status_val not in (
                LeagueStatusEnum.OPEN.value,
                LeagueStatusEnum.UPCOMING.value,
            ):
                raise LeagueTeamConflictError(
                    f"Cannot join league with status {status_val!r}; must be OPEN or UPCOMING"
                )
            current = league_data.get("currentPlayers")
            max_p = league_data.get("maxPlayers")
            if current is not None and max_p is not None and current + 2 > max_p:
                raise LeagueTeamConflictError(f"League {league_id!r} is at full capacity")

            if captain_member_doc.exists:
                raise LeagueTeamConflictError(
                    f"User {captain_uid!r} is already a member of league {league_id!r}"
                )
            if placeholder_member_doc.exists or lookup_doc.exists:
                raise LeagueTeamConflictError(
                    f"An invite for {invite_name!r} already exists in league {league_id!r}"
                )

            txn.set(team_ref, team_data)
            txn.set(
                captain_member_ref,
                {
                    "uid": captain_uid,
                    "role": LeagueRoleEnum.PLAYER.value,
                    "status": LeagueMemberStatusEnum.ACTIVE.value,
                    "joinedAt": now,
                    "stats": None,
                    "displayName": captain_name,
                    "divisionId": None,
                    "teamId": team_id,
                    "partnerUid": placeholder_uid,
                },
            )
            txn.set(
                placeholder_member_ref,
                {
                    "uid": placeholder_uid,
                    "role": LeagueRoleEnum.PLAYER.value,
                    "status": LeagueMemberStatusEnum.ACTIVE.value,
                    "joinedAt": now,
                    "stats": None,
                    "displayName": invite_name,
                    "divisionId": None,
                    "teamId": team_id,
                    "partnerUid": captain_uid,
                },
            )
            txn.set(
                lookup_ref,
                {
                    "emailNormalized": email_norm,
                    "leagueId": league_id,
                    "teamId": team_id,
                    "placeholderUid": placeholder_uid,
                    "captainUid": captain_uid,
                    "inviteName": invite_name,
                    "phone": partner_phone,
                    "createdAt": now,
                },
            )
            txn.update(league_ref, {"currentPlayers": firestore.Increment(2)})

        _invite_txn(transaction)

        return LeagueTeam(
            team_id=team_id,
            status=LeagueTeamStatusEnum.ACTIVE,
            captain_uid=captain_uid,
            partner_uid=None,
            member_uids=[captain_uid, placeholder_uid],
            name=team_name,
            created_at=now,
            accepted_at=now,
            partner_placeholder_uid=placeholder_uid,
            partner_invite=LeagueTeamPartnerInvite(name=invite_name, phone=partner_phone),
        )

    def claim_partner_invites(self, uid: str, email: str) -> None:
        """Backfill every outstanding placeholder invite for ``email`` to ``uid``.

        Called from onboarding after the user doc is created. Idempotent per
        lookup doc and best-effort overall — a partial failure never blocks
        registration (the caller wraps this non-fatally).
        """
        email_norm = normalize_email(email)
        if not email_norm:
            return
        invites = self.leagues_repo.list_partner_invites_by_email(email_norm)
        for invite in invites:
            try:
                self._claim_single_invite(uid, invite)
            except Exception:
                logger.exception(
                    "Failed to claim partner invite %s for uid %s (non-fatal)",
                    invite.get("id"),
                    uid,
                )

    def _claim_single_invite(self, uid: str, invite: dict[str, Any]) -> None:
        lookup_id = invite.get("id")
        league_id = invite.get("leagueId")
        team_id = invite.get("teamId")
        placeholder_uid = invite.get("placeholderUid")
        captain_uid = invite.get("captainUid")
        if not (lookup_id and league_id and team_id and placeholder_uid):
            return

        claimant_name = self._user_display_name(uid)
        league = self.leagues_repo.get_by_id(league_id)
        league_name = league.name if league is not None else ""

        league_ref = self.client.collection("leagues").document(league_id)
        team_ref = league_ref.collection("teams").document(team_id)
        members_col = league_ref.collection("members")
        placeholder_member_ref = members_col.document(placeholder_uid)
        real_member_ref = members_col.document(uid)
        lookup_ref = self.client.collection("partnerInvites").document(lookup_id)

        transaction = self.client.transaction()
        claimed: dict[str, bool] = {"did_claim": False}

        @firestore.transactional
        def _claim_txn(txn: firestore.Transaction) -> None:
            team_doc = cast(firestore.DocumentSnapshot, team_ref.get(transaction=txn))
            placeholder_member_doc = placeholder_member_ref.get(transaction=txn)
            existing_real_member_doc = real_member_ref.get(transaction=txn)

            # Idempotent: if the team is gone or already claimed, just drop the
            # lookup doc and move on.
            if not team_doc.exists:
                txn.delete(lookup_ref)
                return
            team_data = team_doc.to_dict() or {}
            if team_data.get("partnerPlaceholderUid") != placeholder_uid:
                txn.delete(lookup_ref)
                return

            captain_member_ref = members_col.document(team_data.get("captainUid") or captain_uid)

            new_member_uids = [
                uid if u == placeholder_uid else u for u in team_data.get("memberUids", [])
            ]
            captain_name = (team_data.get("name") or "").split(" / ")[0]
            new_team_name = f"{captain_name} / {claimant_name}" if captain_name else claimant_name

            placeholder_data = placeholder_member_doc.to_dict() or {}
            new_member_data = {
                "uid": uid,
                "role": placeholder_data.get("role", LeagueRoleEnum.PLAYER.value),
                "status": placeholder_data.get("status", LeagueMemberStatusEnum.ACTIVE.value),
                "joinedAt": placeholder_data.get("joinedAt", datetime.now(timezone.utc)),
                "stats": placeholder_data.get("stats"),
                "displayName": claimant_name,
                "divisionId": placeholder_data.get("divisionId"),
                "teamId": team_id,
                "partnerUid": team_data.get("captainUid") or captain_uid,
            }

            txn.update(
                team_ref,
                {
                    "partnerUid": uid,
                    "memberUids": new_member_uids,
                    "name": new_team_name,
                    "partnerInvite": firestore.DELETE_FIELD,
                    "partnerPlaceholderUid": firestore.DELETE_FIELD,
                },
            )
            if not existing_real_member_doc.exists:
                txn.set(real_member_ref, new_member_data)
            txn.update(captain_member_ref, {"partnerUid": uid})
            txn.delete(placeholder_member_ref)
            txn.delete(lookup_ref)
            claimed["did_claim"] = True

        _claim_txn(transaction)

        if not claimed["did_claim"]:
            return

        self._rewrite_matches_for_claimed_partner(placeholder_uid, uid)

        if captain_uid:
            self._emit_notification_intent(
                PlayNotificationIntent(
                    type=PlayNotificationIntentTypeEnum.LEAGUE_TEAM_INVITE_ACCEPTED,
                    target_uid=captain_uid,
                    title="Team invite accepted",
                    body=f"{claimant_name} joined your team in {league_name}".rstrip(),
                    dedupe_key=f"league_team_invite_accepted:{league_id}:{team_id}",
                    created_at=datetime.now(timezone.utc),
                )
            )

    def _rewrite_matches_for_claimed_partner(self, placeholder_uid: str, uid: str) -> None:
        """Best-effort: swap the placeholder uid for the real uid on any matches.

        Expected to be a no-op today (placeholder uids never enter matches), so
        failures are logged and swallowed.
        """
        try:
            matches = self.matches_repo.list_for_participant(placeholder_uid)
        except Exception:
            logger.exception(
                "Failed to list matches for placeholder %s (non-fatal)", placeholder_uid
            )
            return
        if not matches:
            return
        batch = self.client.batch()
        for match in matches:
            match_ref = self.client.collection("matches").document(match.match_id)
            new_participants = [uid if p == placeholder_uid else p for p in match.participant_uids]
            batch.update(match_ref, {"participantUids": new_participants})
        try:
            batch.commit()
        except Exception:
            logger.exception("Failed to rewrite matches for claimed partner (non-fatal)")

    def accept_team(self, league_id: str, team_id: str, caller_uid: str) -> LeagueTeam:
        team = self.leagues_repo.get_team(league_id, team_id)
        if team is None:
            raise LeagueTeamNotFoundError(f"Team {team_id!r} not found in league {league_id!r}")
        if caller_uid != team.partner_uid:
            raise LeagueTeamForbiddenError("Only the invited partner can accept this invite")

        captain_uid = team.captain_uid
        partner_uid = team.partner_uid
        captain_name = self._user_display_name(captain_uid)
        partner_name = self._user_display_name(partner_uid)
        now = datetime.now(timezone.utc)

        league_name = ""
        league = self.leagues_repo.get_by_id(league_id)
        if league is not None:
            league_name = league.name

        transaction = self.client.transaction()

        @firestore.transactional
        def _accept_txn(txn: firestore.Transaction) -> None:
            league_ref = self.client.collection("leagues").document(league_id)
            team_ref = league_ref.collection("teams").document(team_id)
            members_col = league_ref.collection("members")
            captain_member_ref = members_col.document(captain_uid)
            partner_member_ref = members_col.document(partner_uid)

            # Reads before writes.
            team_doc = cast(firestore.DocumentSnapshot, team_ref.get(transaction=txn))
            league_doc = cast(firestore.DocumentSnapshot, league_ref.get(transaction=txn))
            captain_member_doc = captain_member_ref.get(transaction=txn)
            partner_member_doc = partner_member_ref.get(transaction=txn)

            if not team_doc.exists:
                raise LeagueTeamNotFoundError(f"Team {team_id!r} not found in league {league_id!r}")
            team_data = team_doc.to_dict() or {}
            if team_data.get("partnerUid") != caller_uid:
                raise LeagueTeamForbiddenError("Only the invited partner can accept this invite")
            if team_data.get("status") != LeagueTeamStatusEnum.PENDING.value:
                raise LeagueTeamConflictError(f"Team {team_id!r} is not pending; cannot accept")

            if not league_doc.exists:
                raise LeagueTeamNotFoundError(f"League {league_id!r} not found")
            league_data = league_doc.to_dict() or {}
            status_val = league_data.get("status")
            if status_val not in (
                LeagueStatusEnum.OPEN.value,
                LeagueStatusEnum.UPCOMING.value,
            ):
                raise LeagueTeamConflictError(
                    f"Cannot join league with status {status_val!r}; must be OPEN or UPCOMING"
                )
            current = league_data.get("currentPlayers")
            max_p = league_data.get("maxPlayers")
            if current is not None and max_p is not None and current + 2 > max_p:
                raise LeagueTeamConflictError(f"League {league_id!r} is at full capacity")

            if captain_member_doc.exists:
                raise LeagueTeamConflictError(
                    f"User {captain_uid!r} is already a member of league {league_id!r}"
                )
            if partner_member_doc.exists:
                raise LeagueTeamConflictError(
                    f"User {partner_uid!r} is already a member of league {league_id!r}"
                )

            txn.update(
                team_ref,
                {"status": LeagueTeamStatusEnum.ACTIVE.value, "acceptedAt": now},
            )
            txn.set(
                captain_member_ref,
                {
                    "uid": captain_uid,
                    "role": LeagueRoleEnum.PLAYER.value,
                    "status": LeagueMemberStatusEnum.ACTIVE.value,
                    "joinedAt": now,
                    "stats": None,
                    "displayName": captain_name,
                    "divisionId": None,
                    "teamId": team_id,
                    "partnerUid": partner_uid,
                },
            )
            txn.set(
                partner_member_ref,
                {
                    "uid": partner_uid,
                    "role": LeagueRoleEnum.PLAYER.value,
                    "status": LeagueMemberStatusEnum.ACTIVE.value,
                    "joinedAt": now,
                    "stats": None,
                    "displayName": partner_name,
                    "divisionId": None,
                    "teamId": team_id,
                    "partnerUid": captain_uid,
                },
            )
            txn.update(league_ref, {"currentPlayers": firestore.Increment(2)})

        _accept_txn(transaction)

        self._emit_notification_intent(
            PlayNotificationIntent(
                type=PlayNotificationIntentTypeEnum.LEAGUE_TEAM_INVITE_ACCEPTED,
                target_uid=captain_uid,
                title="Team invite accepted",
                body=f"{partner_name} accepted your team invite in {league_name}".rstrip(),
                dedupe_key=f"league_team_invite_accepted:{league_id}:{team_id}",
                created_at=now,
            )
        )

        return LeagueTeam(
            team_id=team_id,
            status=LeagueTeamStatusEnum.ACTIVE,
            captain_uid=captain_uid,
            partner_uid=partner_uid,
            member_uids=[captain_uid, partner_uid],
            name=team.name,
            created_at=team.created_at,
            accepted_at=now,
        )

    def decline_team(self, league_id: str, team_id: str, caller_uid: str) -> LeagueTeam:
        team = self.leagues_repo.get_team(league_id, team_id)
        if team is None:
            raise LeagueTeamNotFoundError(f"Team {team_id!r} not found in league {league_id!r}")
        if caller_uid != team.partner_uid:
            raise LeagueTeamForbiddenError("Only the invited partner can decline this invite")
        if team.status != LeagueTeamStatusEnum.PENDING:
            raise LeagueTeamConflictError(f"Team {team_id!r} is not pending; cannot decline")

        now = datetime.now(timezone.utc)
        self._transition_pending_team(league_id, team_id, LeagueTeamStatusEnum.DECLINED, "decline")

        partner_name = self._user_display_name(team.partner_uid)
        league = self.leagues_repo.get_by_id(league_id)
        league_name = league.name if league is not None else ""
        self._emit_notification_intent(
            PlayNotificationIntent(
                type=PlayNotificationIntentTypeEnum.LEAGUE_TEAM_INVITE_DECLINED,
                target_uid=team.captain_uid,
                title="Team invite declined",
                body=f"{partner_name} declined your team invite in {league_name}".rstrip(),
                dedupe_key=f"league_team_invite_declined:{league_id}:{team_id}",
                created_at=now,
            )
        )

        return LeagueTeam(
            team_id=team.team_id,
            status=LeagueTeamStatusEnum.DECLINED,
            captain_uid=team.captain_uid,
            partner_uid=team.partner_uid,
            member_uids=team.member_uids,
            name=team.name,
            created_at=team.created_at,
            accepted_at=team.accepted_at,
        )

    def cancel_team(self, league_id: str, team_id: str, caller_uid: str) -> LeagueTeam:
        team = self.leagues_repo.get_team(league_id, team_id)
        if team is None:
            raise LeagueTeamNotFoundError(f"Team {team_id!r} not found in league {league_id!r}")
        if caller_uid != team.captain_uid:
            raise LeagueTeamForbiddenError("Only the captain can cancel this invite")
        if team.status != LeagueTeamStatusEnum.PENDING:
            raise LeagueTeamConflictError(f"Team {team_id!r} is not pending; cannot cancel")

        self._transition_pending_team(league_id, team_id, LeagueTeamStatusEnum.CANCELLED, "cancel")

        return LeagueTeam(
            team_id=team.team_id,
            status=LeagueTeamStatusEnum.CANCELLED,
            captain_uid=team.captain_uid,
            partner_uid=team.partner_uid,
            member_uids=team.member_uids,
            name=team.name,
            created_at=team.created_at,
            accepted_at=team.accepted_at,
        )

    def kickoff_league(self, league_id: str) -> LeagueKickoffResult:
        league = self.leagues_repo.get_by_id(league_id)
        if league is None:
            raise LeagueKickoffNotFoundError(f"League {league_id!r} not found")

        already_kicked_off = self._claim_kickoff(league_id)
        if already_kicked_off:
            return LeagueKickoffResult(
                league_id=league_id,
                divisions=self.divisions_repo.list_for_league(league_id),
                already_kicked_off=True,
            )

        if league.format == LeagueFormatEnum.DOUBLES:
            divisions = self._kickoff_doubles(league_id, league)
        else:
            divisions = self._kickoff_singles(league_id, league)

        self.client.collection("leagues").document(league_id).update(
            {
                "status": LeagueStatusEnum.ACTIVE.value,
                "dividedAt": datetime.now(timezone.utc),
            }
        )
        return LeagueKickoffResult(league_id=league_id, divisions=divisions)

    def _kickoff_singles(self, league_id: str, league: League) -> list[Division]:
        members = [
            member
            for member in self.leagues_repo.list_members(league_id, limit=None)
            if member.status == LeagueMemberStatusEnum.ACTIVE
        ]
        if not members:
            self.client.collection("leagues").document(league_id).update(
                {"status": LeagueStatusEnum.OPEN.value}
            )
            raise LeagueKickoffConflictError(f"League {league_id!r} has no active members")

        ranked_members = [
            RankedLeagueMember(member=member, pts=self._member_pts(member.uid, league.sport.value))
            for member in members
        ]
        ranked_members.sort(key=lambda item: (-item.pts, item.member.uid))

        splits = split_into_divisions(ranked_members, **self._division_split_kwargs(league))
        divisions = [
            self._split_to_division(split, current_players=len(split.members)) for split in splits
        ]
        self._write_divisions_and_assignments(league_id, divisions, splits)
        return divisions

    def _kickoff_doubles(self, league_id: str, league: League) -> list[Division]:
        """Division seeding for doubles leagues: the unit is the team.

        Team rating is the integer mean of the two partners' per-sport ranking
        points; teammates always land in the same division. Division
        ``currentPlayers`` counts players (2× teams), consistent with league
        capacity semantics.
        """
        teams = self.leagues_repo.list_teams(league_id, status=LeagueTeamStatusEnum.ACTIVE)
        if not teams:
            self.client.collection("leagues").document(league_id).update(
                {"status": LeagueStatusEnum.OPEN.value}
            )
            raise LeagueKickoffConflictError(f"League {league_id!r} has no active teams")

        ranked_teams = [
            RankedLeagueTeam(team=team, pts=self._team_pts(team, league.sport.value))
            for team in teams
        ]
        ranked_teams.sort(key=lambda item: (-item.pts, item.team.team_id))

        splits = split_into_divisions(ranked_teams, **self._division_split_kwargs(league))
        divisions = [
            self._split_to_division(split, current_players=2 * len(split.members))
            for split in splits
        ]
        self._write_divisions_and_team_assignments(league_id, divisions, splits)
        return divisions

    @staticmethod
    def _division_split_kwargs(league: League) -> dict[str, Any]:
        division_config = league.division_config
        return {
            "target_size": division_config.target_size if division_config else DIVISION_TARGET_SIZE,
            "max_divisions": division_config.max_divisions if division_config else None,
        }

    @staticmethod
    def _split_to_division(split: DivisionSplit, current_players: int) -> Division:
        return Division(
            division_id=split.division_id,
            name=split.name,
            ordinal=split.ordinal,
            rating_range=RatingRange(min=split.rating_min, max=split.rating_max),
            current_players=current_players,
            status=LeagueStatusEnum.ACTIVE,
        )

    def _team_pts(self, team: LeagueTeam, sport: str) -> int:
        # Skip placeholder (unregistered) partners: they have no user doc, so
        # _member_pts would return 0 and halve the team rating. Seed on the
        # captain-only mean until the partner registers and backfills.
        pts = [
            self._member_pts(uid, sport)
            for uid in team.member_uids
            if not uid.startswith(PARTNER_INVITE_UID_PREFIX)
        ]
        if not pts:
            return 0
        return sum(pts) // len(pts)

    def _claim_kickoff(self, league_id: str) -> bool:
        league_ref = self.client.collection("leagues").document(league_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def _claim_txn(txn: firestore.Transaction) -> bool:
            league_doc = cast(firestore.DocumentSnapshot, league_ref.get(transaction=txn))
            if not league_doc.exists:
                raise LeagueKickoffNotFoundError(f"League {league_id!r} not found")
            data = league_doc.to_dict() or {}
            status_val = data.get("status")
            divided_at = data.get("dividedAt")
            if status_val == LeagueStatusEnum.OPEN.value:
                txn.update(league_ref, {"status": LeagueStatusEnum.DIVIDING.value})
                return False
            if status_val == LeagueStatusEnum.DIVIDING.value:
                raise LeagueKickoffConflictError(
                    f"League {league_id!r} kickoff already in progress"
                )
            if status_val == LeagueStatusEnum.ACTIVE.value and divided_at is not None:
                return True
            raise LeagueKickoffConflictError(f"League {league_id!r} already kicked off")

        return bool(_claim_txn(transaction))

    def _member_pts(self, uid: str, sport: str) -> int:
        user_doc = self.users_repo.get_user_doc(uid) or {}
        ranking = (user_doc.get("rankings") or {}).get(sport) or {}
        return int(ranking.get("pts") or 0)

    def _write_divisions_and_assignments(
        self, league_id: str, divisions: list[Division], splits: list[DivisionSplit]
    ) -> None:
        league_ref = self.client.collection("leagues").document(league_id)
        pending_writes: list[tuple[Any, dict[str, Any]]] = []
        for division in divisions:
            pending_writes.append(
                (
                    league_ref.collection("divisions").document(division.division_id),
                    {
                        "name": division.name,
                        "ordinal": division.ordinal,
                        "ratingRange": {
                            "min": division.rating_range.min,
                            "max": division.rating_range.max,
                        },
                        "currentPlayers": division.current_players,
                        "status": division.status.value,
                    },
                )
            )
        for split in splits:
            for ranked_member in split.members:
                if ranked_member.member.division_id is None:
                    member_ref = league_ref.collection("members").document(ranked_member.member.uid)
                    pending_writes.append((member_ref, {"divisionId": split.division_id}))

        self._commit_batched(pending_writes)

    def _write_divisions_and_team_assignments(
        self,
        league_id: str,
        divisions: list[Division],
        splits: list[DivisionSplit[RankedLeagueTeam]],
    ) -> None:
        """Doubles variant: stamp divisionId on the team doc AND both member docs."""
        league_ref = self.client.collection("leagues").document(league_id)
        pending_writes: list[tuple[Any, dict[str, Any]]] = []
        for division in divisions:
            pending_writes.append(
                (
                    league_ref.collection("divisions").document(division.division_id),
                    {
                        "name": division.name,
                        "ordinal": division.ordinal,
                        "ratingRange": {
                            "min": division.rating_range.min,
                            "max": division.rating_range.max,
                        },
                        "currentPlayers": division.current_players,
                        "status": division.status.value,
                    },
                )
            )
        for split in splits:
            for ranked_team in split.members:
                team = ranked_team.team
                if team.division_id is not None:
                    continue
                team_ref = league_ref.collection("teams").document(team.team_id)
                pending_writes.append((team_ref, {"divisionId": split.division_id}))
                for uid in team.member_uids:
                    member_ref = league_ref.collection("members").document(uid)
                    pending_writes.append((member_ref, {"divisionId": split.division_id}))

        self._commit_batched(pending_writes)

    def _commit_batched(self, pending_writes: list[tuple[Any, dict[str, Any]]]) -> None:
        for offset in range(0, len(pending_writes), 500):
            batch = self.client.batch()
            for doc_ref, data in pending_writes[offset : offset + 500]:
                if "divisionId" in data:
                    batch.update(doc_ref, data)
                else:
                    batch.set(doc_ref, data)
            batch.commit()

    def _rank_members(self, members: list[LeagueMember]) -> list[StandingsEntry]:
        # Build sortable rows: (wins, losses, display_name, uid)
        # display_name falls back to uid when not stored in member doc
        rows: list[tuple[int, int, str, str]] = []
        for m in members:
            stats = m.stats or {}
            wins = int(stats.get("wins", 0))
            losses = int(stats.get("losses", 0))
            rows.append((wins, losses, m.display_name or m.uid, m.uid))

        # Sort: wins DESC, losses ASC, (wins-losses) DESC, display_name ASC
        rows.sort(key=lambda r: (-r[0], r[1], -(r[0] - r[1]), r[2]))

        # Dense ranking: tied (wins, losses) share the same rank; next rank is +1 not +gap
        result: list[StandingsEntry] = []
        rank = 0
        prev_key: tuple[int, int] | None = None
        for wins, losses, display_name, uid in rows:
            key = (wins, losses)
            if key != prev_key:
                rank += 1
                prev_key = key
            result.append(
                StandingsEntry(
                    rank=rank,
                    uid=uid,
                    display_name=display_name,
                    wins=wins,
                    losses=losses,
                    tier_ring=None,
                )
            )

        return result

    def _rank_teams(self, league_id: str, teams: list[LeagueTeam]) -> list[StandingsEntry]:
        """Doubles standings: one row per ACTIVE team.

        Wins/losses come from the captain's member stats — partners always
        share identical league match participation, so captain stats == team
        stats for MVP (falls back to the partner's stats if the captain doc is
        missing). ``uid`` carries the captain uid as the stable row key;
        ``display_name`` is the team name ("Captain / Partner").
        """
        members_by_uid = {
            member.uid: member for member in self.leagues_repo.list_members(league_id, limit=None)
        }
        rows: list[tuple[int, int, str, LeagueTeam]] = []
        for team in teams:
            source = members_by_uid.get(team.captain_uid)
            if source is None and team.partner_uid is not None:
                source = members_by_uid.get(team.partner_uid)
            stats = (source.stats if source else None) or {}
            wins = int(stats.get("wins", 0))
            losses = int(stats.get("losses", 0))
            rows.append((wins, losses, team.name or team.team_id, team))

        # Sort: wins DESC, losses ASC, (wins-losses) DESC, team name ASC
        rows.sort(key=lambda r: (-r[0], r[1], -(r[0] - r[1]), r[2]))

        # Dense ranking, same semantics as _rank_members
        result: list[StandingsEntry] = []
        rank = 0
        prev_key: tuple[int, int] | None = None
        for wins, losses, name, team in rows:
            key = (wins, losses)
            if key != prev_key:
                rank += 1
                prev_key = key
            result.append(
                StandingsEntry(
                    rank=rank,
                    uid=team.captain_uid,
                    display_name=name,
                    wins=wins,
                    losses=losses,
                    tier_ring=None,
                    team_id=team.team_id,
                    member_uids=list(team.member_uids),
                )
            )
        return result

    def _active_teams(self, league_id: str) -> list[LeagueTeam]:
        return self.leagues_repo.list_teams(league_id, status=LeagueTeamStatusEnum.ACTIVE)

    def get_standings(self, league_id: str) -> list[StandingsEntry]:
        league = self.leagues_repo.get_by_id(league_id)
        if league is not None and league.format == LeagueFormatEnum.DOUBLES:
            return self._rank_teams(league_id, self._active_teams(league_id))
        return self._rank_members(self.leagues_repo.list_members(league_id))

    def get_division_standings(self, league_id: str, division_id: str) -> list[StandingsEntry]:
        league = self.leagues_repo.get_by_id(league_id)
        if league is not None and league.format == LeagueFormatEnum.DOUBLES:
            teams = [
                team for team in self._active_teams(league_id) if team.division_id == division_id
            ]
            return self._rank_teams(league_id, teams)
        members = [
            member
            for member in self.leagues_repo.list_members(league_id, limit=None)
            if member.division_id == division_id
        ]
        return self._rank_members(members)
