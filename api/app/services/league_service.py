from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.constants import DIVISION_TARGET_SIZE
from app.models import Division, LeagueMember, RatingRange, StandingsEntry
from app.models.enums import LeagueMemberStatusEnum, LeagueRoleEnum, LeagueStatusEnum
from app.repos.divisions_repo import DivisionsRepo
from app.repos.leagues_repo import LeaguesRepo
from app.repos.users_repo import UsersRepo


class LeagueKickoffError(ValueError):
    pass


class LeagueKickoffNotFoundError(LeagueKickoffError):
    pass


class LeagueKickoffConflictError(LeagueKickoffError):
    pass


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
    ):
        self.leagues_repo = leagues_repo
        self.client = firestore_client
        self.users_repo = users_repo or UsersRepo(firestore_client)
        self.divisions_repo = divisions_repo or DivisionsRepo(firestore_client)

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

    def get_standings(self, league_id: str) -> list[StandingsEntry]:
        members = self.leagues_repo.list_members(league_id)

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
