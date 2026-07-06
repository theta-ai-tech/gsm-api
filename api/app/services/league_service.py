from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.constants import DIVISION_TARGET_SIZE
from app.models import Division, LeagueMember, LeagueTeam, RatingRange, StandingsEntry
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
from app.repos.notification_intent_repo import NotificationIntentRepo
from app.repos.users_repo import UsersRepo

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
class DivisionSplit:
    division_id: str
    name: str
    ordinal: int
    members: list[RankedLeagueMember]
    rating_min: int
    rating_max: int


@dataclass(frozen=True)
class LeagueKickoffResult:
    league_id: str
    divisions: list[Division]
    already_kicked_off: bool = False


def split_into_divisions(
    sorted_members: Sequence[RankedLeagueMember],
    target_size: int = DIVISION_TARGET_SIZE,
    max_divisions: int | None = None,
) -> list[DivisionSplit]:
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
    splits: list[DivisionSplit] = []
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
    ):
        self.leagues_repo = leagues_repo
        self.client = firestore_client
        self.users_repo = users_repo or UsersRepo(firestore_client)
        self.divisions_repo = divisions_repo or DivisionsRepo(firestore_client)
        self.notification_intent_repo = notification_intent_repo

    def _emit_notification_intent(self, intent: PlayNotificationIntent) -> None:
        if self.notification_intent_repo is None:
            return
        try:
            self.notification_intent_repo.add_intent(intent)
        except Exception:
            logger.exception("Failed to write league notification intent (non-fatal)")

    def _user_display_name(self, uid: str, fallback: str | None = None) -> str:
        user_doc = self.users_repo.get_user_doc(uid) or {}
        name = user_doc.get("name")
        if isinstance(name, str) and name.strip():
            return name
        return fallback or uid

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
        partner_name = self._user_display_name(partner_uid)
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

            if league_doc.exists:
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
        team_ref = (
            self.client.collection("leagues")
            .document(league_id)
            .collection("teams")
            .document(team_id)
        )
        team_ref.update({"status": LeagueTeamStatusEnum.DECLINED.value})

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

        team_ref = (
            self.client.collection("leagues")
            .document(league_id)
            .collection("teams")
            .document(team_id)
        )
        team_ref.update({"status": LeagueTeamStatusEnum.CANCELLED.value})

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

        division_config = league.division_config
        target_size = division_config.target_size if division_config else DIVISION_TARGET_SIZE
        max_divisions = division_config.max_divisions if division_config else None
        splits = split_into_divisions(
            ranked_members, target_size=target_size, max_divisions=max_divisions
        )
        divisions = [
            Division(
                division_id=split.division_id,
                name=split.name,
                ordinal=split.ordinal,
                rating_range=RatingRange(min=split.rating_min, max=split.rating_max),
                current_players=len(split.members),
                status=LeagueStatusEnum.ACTIVE,
            )
            for split in splits
        ]

        self._write_divisions_and_assignments(league_id, divisions, splits)
        self.client.collection("leagues").document(league_id).update(
            {
                "status": LeagueStatusEnum.ACTIVE.value,
                "dividedAt": datetime.now(timezone.utc),
            }
        )
        return LeagueKickoffResult(league_id=league_id, divisions=divisions)

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

    def get_standings(self, league_id: str) -> list[StandingsEntry]:
        return self._rank_members(self.leagues_repo.list_members(league_id))

    def get_division_standings(self, league_id: str, division_id: str) -> list[StandingsEntry]:
        members = [
            member
            for member in self.leagues_repo.list_members(league_id, limit=None)
            if member.division_id == division_id
        ]
        return self._rank_members(members)
