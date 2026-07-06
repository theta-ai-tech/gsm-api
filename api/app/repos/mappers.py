from __future__ import annotations

from typing import Any, List, Optional

from pydantic import ValidationError

from app.constants import DIVISION_TARGET_SIZE
from app.models import (
    AvailabilityEnum,
    Broadcast,
    BroadcastLocation,
    BroadcastStatusEnum,
    BroadcastTypeEnum,
    CourtStatusEnum,
    CursorBundle,
    Division,
    DivisionConfig,
    GeoCoordinates,
    GeoLocation,
    JournalEntry,
    JournalEntryTypeEnum,
    JournalEntrySummary,
    JournalVisibilityEnum,
    League,
    LeagueBrowseCard,
    LeagueFormatEnum,
    LeagueMember,
    LeagueMemberStatusEnum,
    LeagueRoleEnum,
    LeagueStatusEnum,
    LeagueSummary,
    LeagueTeam,
    LeagueTeamStatusEnum,
    LevelEnum,
    Match,
    MatchOpponentSummary,
    MatchParticipant,
    MatchReflection,
    MatchResultEnum,
    MatchScore,
    MatchStatusEnum,
    MatchTypeEnum,
    Offer,
    NorthStarGoal,
    OfferStatusEnum,
    ParticipantRoleEnum,
    PerSportLevels,
    PerSportRankings,
    PointHistoryEntry,
    PointHistoryReasonEnum,
    PrivateUserProfile,
    PublicUserProfile,
    RatingRange,
    ScoutingProfile,
    ScoutingSportData,
    ScoutingTagCount,
    SetScore,
    SkillAxisData,
    SportEnum,
    SportRanking,
    SportSkillDna,
    TickerEventTypeEnum,
    TierEnum,
    TrainingFocusEnum,
    UserCompletedMatchSummary,
    UserMatchSummary,
    UserPreferences,
    VenueRef,
    VenueSummary,
)
from app.models.enums import PlatformEnum
from app.models.user import DeviceToken
from app.models.leaderboard import LeaderboardEntry, LeaderboardSnapshot, RisingStarEntry
from app.models.ticker import TickerEvent


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data or data.get(key) is None:
        raise ValueError(f"Missing required field: {key}")
    return data[key]


def _parse_sport_ranking(data: Optional[dict[str, Any]]) -> Optional[SportRanking]:
    if not data:
        return None
    sport_val = _require(data, "sport")
    tier = data.get("tier")
    reg_tier = data.get("registrationTier")
    return SportRanking(
        sport=SportEnum(sport_val),
        pts=data.get("pts", 0),
        global_ranking=data.get("globalRanking"),
        tier=TierEnum(tier) if tier else None,
        registration_tier=TierEnum(reg_tier) if reg_tier else None,
        last_updated=data.get("lastUpdated"),
        personal_best=data.get("personalBest"),
        current_streak=int(data.get("currentStreak") or 0),
        best_streak=int(data.get("bestStreak") or 0),
    )


def _parse_per_sport_rankings(data: dict[str, Any]) -> PerSportRankings:
    return PerSportRankings(
        tennis=_parse_sport_ranking(data.get("tennis")),
        padel=_parse_sport_ranking(data.get("padel")),
        pickleball=_parse_sport_ranking(data.get("pickleball")),
    )


def _parse_per_sport_levels(data: dict[str, Any]) -> PerSportLevels:
    def _lvl(val: Any) -> Optional[LevelEnum]:
        return LevelEnum(val) if val else None

    return PerSportLevels(
        tennis=_lvl(data.get("tennis")),
        padel=_lvl(data.get("padel")),
        pickleball=_lvl(data.get("pickleball")),
    )


def _parse_user_preferences(data: dict[str, Any]) -> UserPreferences:
    levels = _parse_per_sport_levels(data.get("levels", {}) or {})
    sports = [SportEnum(s) for s in data.get("sports", [])]
    return UserPreferences(
        area=data.get("area", 0),
        levels=levels,
        sports=sports,
        feed_opt_out=bool(data.get("feedOptOut", False)),
    )


def _parse_league_summary(data: dict[str, Any]) -> LeagueSummary:
    role = data.get("role")
    return LeagueSummary(
        league_id=str(_require(data, "leagueId")),
        name=data.get("name", ""),
        sport=SportEnum(_require(data, "sport")),
        status=LeagueStatusEnum(_require(data, "status")),
        role=LeagueRoleEnum(role) if role else None,
        division_id=data.get("divisionId"),
    )


def _parse_match_opponents(items: list[dict[str, Any]]) -> List[MatchOpponentSummary]:
    return [MatchOpponentSummary(uid=item.get("uid", ""), name=item.get("name")) for item in items]


def _parse_user_match_summary(data: dict[str, Any]) -> UserMatchSummary:
    return UserMatchSummary(
        match_id=str(_require(data, "matchId")),
        sport=SportEnum(_require(data, "sport")),
        scheduled_at=_require(data, "scheduledAt"),
        league_id=data.get("leagueId"),
        court_id=data.get("courtId"),
        opponents=_parse_match_opponents(data.get("opponents", [])),
    )


def _parse_user_completed_match_summary(data: dict[str, Any]) -> UserCompletedMatchSummary:
    result = data.get("result")
    return UserCompletedMatchSummary(
        match_id=str(_require(data, "matchId")),
        sport=SportEnum(_require(data, "sport")),
        finished_at=_require(data, "finishedAt"),
        result=MatchResultEnum(result) if result else None,
        score_text=data.get("scoreText"),
        league_id=data.get("leagueId"),
    )


def _parse_journal_entry_summary(data: dict[str, Any]) -> JournalEntrySummary:
    sport = data.get("sport")
    entry_type = data.get("entryType")
    return JournalEntrySummary(
        entry_id=str(_require(data, "entryId")),
        created_at=_require(data, "createdAt"),
        title=data.get("title", ""),
        match_id=data.get("matchId"),
        sport=SportEnum(sport) if sport else None,
        entry_type=JournalEntryTypeEnum(entry_type) if entry_type else None,
    )


def _parse_match_reflection(data: dict[str, Any] | None) -> Optional[MatchReflection]:
    if not data:
        return None
    return MatchReflection(
        went_well=data.get("wentWell", []),
        went_wrong=data.get("wentWrong", []),
        opponent_weak=data.get("opponentWeak", []),
        opponent_strong=data.get("opponentStrong", []),
        ai_summary=data.get("aiSummary"),
        reflection_version=data.get("reflectionVersion"),
    )


def _parse_device_token(data: dict[str, Any]) -> DeviceToken:
    return DeviceToken(
        token=data["token"],
        platform=PlatformEnum(data["platform"]),
        created_at=data["createdAt"],
        last_seen_at=data["lastSeenAt"],
    )


def _parse_north_star_goal(data: dict[str, Any] | None) -> Optional[NorthStarGoal]:
    if not data:
        return None
    return NorthStarGoal(
        goal_text=data["goalText"],
        progress_pct=data.get("progressPct", 0.0),
        created_at=data["createdAt"],
        target_date=data.get("targetDate"),
    )


def _parse_skill_axis(data: dict[str, Any]) -> SkillAxisData:
    return SkillAxisData(
        positive=int(data.get("positive", 0)),
        negative=int(data.get("negative", 0)),
        score=int(data.get("score", 0)),
    )


def _parse_sport_skill_dna(data: dict[str, Any]) -> SportSkillDna:
    axes = ("serve", "power", "net_play", "stamina", "mental")
    kwargs: dict[str, Any] = {}
    for axis in axes:
        axis_data = data.get(axis)
        if isinstance(axis_data, dict):
            kwargs[axis] = _parse_skill_axis(axis_data)
    return SportSkillDna(
        totalReflections=int(data.get("totalReflections", 0)),
        lastUpdated=data.get("lastUpdated"),
        **kwargs,
    )


def _parse_skill_dna(data: dict[str, Any] | None) -> Optional[dict[str, SportSkillDna]]:
    if not data:
        return None
    result = {
        sport: _parse_sport_skill_dna(sport_data)
        for sport, sport_data in data.items()
        if isinstance(sport_data, dict)
    }
    return result or None


def _parse_cursors(data: dict[str, Any] | None) -> Optional[CursorBundle]:
    if not data:
        return None
    return CursorBundle(
        upcoming_matches=data.get("upcomingMatches"),
        completed_matches=data.get("completedMatches"),
        journal=data.get("journal"),
    )


def to_public_user_profile(doc: dict[str, Any]) -> PublicUserProfile:
    rankings = _parse_per_sport_rankings(doc.get("rankings", {}) or {})

    def _league_summary_list(key: str) -> List[LeagueSummary]:
        return [_parse_league_summary(item) for item in doc.get(key, [])]

    return PublicUserProfile(
        uid=str(doc.get("uid") or doc.get("id") or ""),
        name=doc.get("name", ""),
        profile_url=doc.get("profileUrl"),
        rankings=rankings,
        leagues_active=_league_summary_list("leaguesActive"),
        leagues_completed=_league_summary_list("leaguesCompleted"),
        skill_dna=_parse_skill_dna(doc.get("skillDna")),
        is_pro=bool(doc.get("isPro", False)),
    )


def to_private_user_profile(doc: dict[str, Any]) -> PrivateUserProfile:
    public = to_public_user_profile(doc)

    def _list_or_empty(key: str) -> list[Any]:
        return doc.get(key, []) or []

    return PrivateUserProfile(
        **public.model_dump(),
        email=doc.get("email", ""),
        phone=doc.get("phone"),
        preferences=_parse_user_preferences(doc.get("preferences", {}) or {}),
        upcoming_matches=[
            _parse_user_match_summary(item) for item in _list_or_empty("upcomingMatches")
        ],
        completed_matches=[
            _parse_user_completed_match_summary(item) for item in _list_or_empty("completedMatches")
        ],
        journal_recent=[
            _parse_journal_entry_summary(item) for item in _list_or_empty("journalRecent")
        ],
        cursors=_parse_cursors(doc.get("cursors")),
        north_star_goal=_parse_north_star_goal(doc.get("northStarGoal")),
        device_tokens=[_parse_device_token(t) for t in (doc.get("deviceTokens") or [])],
    )


def _parse_participant(data: dict[str, Any]) -> MatchParticipant:
    role = data.get("role")
    result = data.get("result")
    team = data.get("team")
    # Coerce legacy integer team values (1/2) written before DBL-2.
    if isinstance(team, int):
        team = "A" if team == 1 else "B" if team == 2 else None
    return MatchParticipant(
        uid=str(data.get("uid", "")),
        team=team,
        role=ParticipantRoleEnum(role) if role else ParticipantRoleEnum.PLAYER,
        result=MatchResultEnum(result) if result else None,
        display_name=data.get("displayName") or data.get("display_name"),
    )


def _parse_score(score: dict[str, Any]) -> Optional[MatchScore]:
    if not score:
        return None
    sets_raw = score.get("sets", []) or []
    sets = [
        SetScore(
            p1_games=item.get("p1Games", 0),
            p2_games=item.get("p2Games", 0),
            tiebreak_score=item.get("tiebreakScore"),
        )
        for item in sets_raw
    ]
    return MatchScore(
        sets=sets,
        winner_uid=score.get("winnerUid"),
        winner_team=score.get("winnerTeam"),
        retired=score.get("retired", False),
    )


def to_match(doc: dict[str, Any], match_id: str | None = None) -> Match:
    participant_uids = list(doc.get("participantUids", []) or [])
    raw_participants = doc.get("participants")
    is_legacy = "matchType" not in doc
    if raw_participants:
        participants = [_parse_participant(p) for p in raw_participants]
        if is_legacy:
            # Legacy singles documents may have stored ``team: 1`` / ``team: 2``
            # as a 1-per-side label. Without a ``matchType`` field we treat
            # them as singles and clear the team labels so the model
            # validator (singles requires team=None) accepts them.
            participants = [
                MatchParticipant(
                    uid=p.uid,
                    team=None,
                    role=p.role,
                    result=p.result,
                    display_name=p.display_name,
                )
                for p in participants
            ]
    else:
        # Compute-on-read default for legacy documents that predate DBL-2:
        # build a participants array from the flattened ``participantUids``
        # with ``team=None`` (singles).
        participants = [
            MatchParticipant(uid=uid, team=None, role=ParticipantRoleEnum.PLAYER)
            for uid in participant_uids
        ]
    result_by_user = doc.get("resultByUser") or None
    if result_by_user:
        result_by_user = {uid: MatchResultEnum(val) for uid, val in result_by_user.items()}

    sport_val = _require(doc, "sport")
    status_val = _require(doc, "status")

    # ``matchType`` defaults to ``singles`` for legacy documents.
    match_type_val = doc.get("matchType") or MatchTypeEnum.SINGLES.value

    # ``resultSubmittedBy`` was added in DBL-2. For legacy documents that
    # already carry a ``resultByUser`` map (i.e. the score-submission paths
    # ran before this field existed), fall back to the keys of that map so
    # consumers can still tell who submitted a result without a backfill.
    raw_submitted_by = doc.get("resultSubmittedBy")
    if raw_submitted_by:
        result_submitted_by = list(raw_submitted_by)
    elif result_by_user:
        result_submitted_by = list(result_by_user.keys())
    else:
        result_submitted_by = []

    return Match(
        match_id=match_id or doc.get("match_id") or doc.get("id") or "",
        sport=SportEnum(sport_val),
        status=MatchStatusEnum(status_val),
        match_type=MatchTypeEnum(match_type_val),
        scheduled_at=doc.get("scheduledAt"),
        finished_at=doc.get("finishedAt"),
        league_id=doc.get("leagueId"),
        division_id=doc.get("divisionId"),
        court_id=doc.get("courtId"),
        venue_ref=_parse_venue_ref(doc.get("venueRef")),
        score=_parse_score(doc.get("score", {})),
        result_by_user=result_by_user,
        participants=participants,
        participant_uids=participant_uids,
        participant_pair=doc.get("participantPair"),
        result_submitted_by=result_submitted_by,
    )


def to_league(doc: dict[str, Any], league_id: str | None = None) -> League:
    sport_val = _require(doc, "sport")
    status_val = _require(doc, "status")
    return League(
        league_id=league_id or doc.get("id") or "",
        name=doc.get("name", ""),
        sport=SportEnum(sport_val),
        season=doc.get("season"),
        status=LeagueStatusEnum(status_val),
        owner_uid=doc.get("ownerUid", ""),
        format=LeagueFormatEnum(doc.get("format", "singles")),
        region=doc.get("region"),
        max_players=doc.get("maxPlayers"),
        current_players=doc.get("currentPlayers"),
        start_date=doc.get("startDate"),
        end_date=doc.get("endDate"),
        divided_at=doc.get("dividedAt"),
        tier=doc.get("tier"),
        division_config=_parse_division_config(doc.get("divisionConfig")),
        meta=doc.get("meta"),
    )


def to_league_browse_card(doc: dict[str, Any], league_id: str | None = None) -> LeagueBrowseCard:
    sport_val = _require(doc, "sport")
    status_val = _require(doc, "status")
    return LeagueBrowseCard(
        league_id=league_id or doc.get("id") or "",
        name=doc.get("name", ""),
        sport=SportEnum(sport_val),
        status=LeagueStatusEnum(status_val),
        format=LeagueFormatEnum(doc.get("format", "singles")),
        region=doc.get("region"),
        tier=doc.get("tier"),
        max_players=doc.get("maxPlayers"),
        current_players=doc.get("currentPlayers"),
        start_date=doc.get("startDate"),
    )


def to_league_member(doc: dict[str, Any], uid: str | None = None) -> LeagueMember:
    role_val = _require(doc, "role")
    status_val = _require(doc, "status")
    return LeagueMember(
        uid=uid or doc.get("uid", ""),
        role=LeagueRoleEnum(role_val),
        status=LeagueMemberStatusEnum(status_val),
        joined_at=_require(doc, "joinedAt"),
        stats=doc.get("stats"),
        display_name=doc.get("displayName"),
        division_id=doc.get("divisionId"),
        team_id=doc.get("teamId"),
        partner_uid=doc.get("partnerUid"),
    )


def to_league_team(doc: dict[str, Any], team_id: str | None = None) -> LeagueTeam:
    status_val = _require(doc, "status")
    return LeagueTeam(
        team_id=team_id or doc.get("teamId") or doc.get("id") or "",
        status=LeagueTeamStatusEnum(status_val),
        captain_uid=_require(doc, "captainUid"),
        partner_uid=_require(doc, "partnerUid"),
        member_uids=list(doc.get("memberUids", []) or []),
        name=doc.get("name", ""),
        created_at=_require(doc, "createdAt"),
        accepted_at=doc.get("acceptedAt"),
        rating_avg=doc.get("ratingAvg"),
        division_id=doc.get("divisionId"),
    )


def _parse_division_config(data: dict[str, Any] | None) -> DivisionConfig | None:
    if data is None:
        return None
    return DivisionConfig(
        target_size=int(data.get("targetSize") or data.get("target_size") or DIVISION_TARGET_SIZE),
        max_divisions=data.get("maxDivisions") or data.get("max_divisions"),
    )


def _parse_rating_range(data: dict[str, Any]) -> RatingRange:
    return RatingRange(min=int(_require(data, "min")), max=int(_require(data, "max")))


def to_division(doc: dict[str, Any], division_id: str | None = None) -> Division:
    status_val = _require(doc, "status")
    return Division(
        division_id=division_id or doc.get("id") or "",
        name=doc.get("name", ""),
        ordinal=int(_require(doc, "ordinal")),
        rating_range=_parse_rating_range(_require(doc, "ratingRange")),
        current_players=int(_require(doc, "currentPlayers")),
        status=LeagueStatusEnum(status_val),
    )


def to_journal_entry(
    doc: dict[str, Any], entry_id: str | None = None, uid: str | None = None
) -> JournalEntry:
    visibility = _require(doc, "visibility")
    sport = doc.get("sport")
    entry_type = doc.get("entryType")
    result = doc.get("result")
    return JournalEntry(
        entry_id=entry_id or doc.get("id") or "",
        uid=uid or doc.get("uid") or "",
        created_at=_require(doc, "createdAt"),
        title=doc.get("title", ""),
        body=doc.get("body", ""),
        tags=doc.get("tags", []),
        match_id=doc.get("matchId"),
        sport=SportEnum(sport) if sport else None,
        visibility=JournalVisibilityEnum(visibility),
        entry_type=JournalEntryTypeEnum(entry_type) if entry_type else JournalEntryTypeEnum.MATCH,
        duration_minutes=doc.get("durationMinutes"),
        training_focus=[TrainingFocusEnum(f) for f in doc.get("trainingFocus", [])],
        reflection=_parse_match_reflection(doc.get("reflection")),
        score_text=doc.get("scoreText"),
        result=MatchResultEnum(result) if result else None,
        client_request_id=doc.get("clientRequestId"),
        is_deleted=bool(doc.get("isDeleted", False)),
        deleted_at=doc.get("deletedAt"),
    )


def _parse_geo_location(data: dict[str, Any] | None) -> Optional[GeoLocation]:
    if not data:
        return None
    return GeoLocation(lat=data.get("lat", 0.0), lng=data.get("lng", 0.0))


def _parse_broadcast_location(data: dict[str, Any]) -> BroadcastLocation:
    return BroadcastLocation(
        area=data.get("area"),
        geo=_parse_geo_location(data.get("geo")),
        radius_km=data.get("radiusKm"),
    )


def _parse_venue_ref(data: dict[str, Any] | None) -> VenueRef | None:
    if not data:
        return None
    try:
        return VenueRef.model_validate(data)
    except ValidationError:
        return None


def to_broadcast(doc: dict[str, Any], broadcast_id: str | None = None) -> Broadcast:
    sport_val = _require(doc, "sport")
    availability_val = _require(doc, "availability")
    court_status_val = _require(doc, "courtStatus")
    status_val = _require(doc, "status")
    owner_ranking = _parse_sport_ranking(doc.get("ownerRanking"))

    # ``matchType`` and ``broadcastType`` were added in DBL-3. Default to
    # singles/find_opponent for legacy documents written before this change.
    match_type_val = doc.get("matchType") or MatchTypeEnum.SINGLES.value
    broadcast_type_val = doc.get("broadcastType") or BroadcastTypeEnum.FIND_OPPONENT.value

    return Broadcast(
        broadcast_id=broadcast_id or doc.get("id") or "",
        owner_uid=_require(doc, "ownerUid"),
        owner_name=doc.get("ownerName", ""),
        owner_ranking=owner_ranking,
        sport=SportEnum(sport_val),
        match_type=MatchTypeEnum(match_type_val),
        broadcast_type=BroadcastTypeEnum(broadcast_type_val),
        partner_uid=doc.get("partnerUid"),
        availability=AvailabilityEnum(availability_val),
        court_status=CourtStatusEnum(court_status_val),
        court_location=doc.get("courtLocation"),
        venue_ref=_parse_venue_ref(doc.get("venueRef")),
        status=BroadcastStatusEnum(status_val),
        expires_at=_require(doc, "expiresAt"),
        created_at=_require(doc, "createdAt"),
        location=_parse_broadcast_location(doc.get("location", {}) or {}),
    )


def to_point_history_entry(doc: dict[str, Any], entry_id: str) -> PointHistoryEntry:
    tier_before = doc.get("tierBefore")
    tier_after = doc.get("tierAfter")
    return PointHistoryEntry(
        entry_id=entry_id,
        sport=SportEnum(_require(doc, "sport")),
        pts=_require(doc, "pts"),
        delta=_require(doc, "delta"),
        reason=PointHistoryReasonEnum(_require(doc, "reason")),
        match_id=doc.get("matchId"),
        opponent_uid=doc.get("opponentUid"),
        opponent_pts_before=doc.get("opponentPtsBefore"),
        league_id=doc.get("leagueId"),
        created_at=_require(doc, "createdAt"),
        tier_before=TierEnum(tier_before) if tier_before else None,
        tier_after=TierEnum(tier_after) if tier_after else None,
    )


def to_offer(doc: dict[str, Any], offer_id: str | None = None) -> Offer:
    sport_val = _require(doc, "sport")
    status_val = _require(doc, "status")
    from_ranking = _parse_sport_ranking(doc.get("fromRanking"))
    to_ranking = _parse_sport_ranking(doc.get("toRanking"))

    # ``matchType`` and ``partnerUid`` were added in DBL-4. Default to singles
    # for legacy documents written before this change.
    match_type_val = doc.get("matchType") or MatchTypeEnum.SINGLES.value

    return Offer(
        offer_id=offer_id or doc.get("id") or "",
        from_uid=_require(doc, "fromUid"),
        from_name=doc.get("fromName", ""),
        from_ranking=from_ranking,
        to_uid=_require(doc, "toUid"),
        to_name=doc.get("toName", ""),
        to_ranking=to_ranking,
        sport=SportEnum(sport_val),
        match_type=MatchTypeEnum(match_type_val),
        partner_uid=doc.get("partnerUid"),
        proposed_time=_require(doc, "proposedTime"),
        court_location=doc.get("courtLocation"),
        venue_ref=_parse_venue_ref(doc.get("venueRef")),
        source_broadcast_id=doc.get("sourceBroadcastId"),
        league_id=doc.get("leagueId"),
        message=doc.get("message"),
        status=OfferStatusEnum(status_val),
        expires_at=_require(doc, "expiresAt"),
        created_at=_require(doc, "createdAt"),
        match_id=doc.get("matchId"),
    )


def _parse_scouting_tag_counts(
    data: dict[str, Any] | None,
) -> dict[str, ScoutingTagCount]:
    if not data:
        return {}
    result: dict[str, ScoutingTagCount] = {}
    for tag, tag_data in data.items():
        if isinstance(tag_data, dict):
            result[tag] = ScoutingTagCount(
                count=int(tag_data.get("count", 0)),
                last_reported=tag_data.get("lastReported"),
            )
    return result


def _parse_scouting_sport_data(data: dict[str, Any] | None) -> Optional[ScoutingSportData]:
    if not data:
        return None
    return ScoutingSportData(
        weak=_parse_scouting_tag_counts(data.get("weak")),
        strong=_parse_scouting_tag_counts(data.get("strong")),
        total_reports=int(data.get("totalReports", 0)),
        unique_reporters=int(data.get("uniqueReporters", 0)),
        last_updated=data.get("lastUpdated"),
    )


def to_scouting_profile(doc: dict[str, Any]) -> ScoutingProfile:
    return ScoutingProfile(
        uid=doc.get("uid") or doc.get("id") or "",
        tennis=_parse_scouting_sport_data(doc.get("tennis")),
        padel=_parse_scouting_sport_data(doc.get("padel")),
        pickleball=_parse_scouting_sport_data(doc.get("pickleball")),
    )


def _parse_leaderboard_entry(data: dict[str, Any]) -> LeaderboardEntry:
    return LeaderboardEntry(
        uid=data.get("uid", ""),
        name=data.get("name", ""),
        pts=int(data.get("pts", 0)),
        tier=data.get("tier"),
        rank=int(data.get("rank", 0)),
        delta7d=int(data.get("delta7d", 0)),
    )


def _parse_rising_star_entry(data: dict[str, Any]) -> RisingStarEntry:
    return RisingStarEntry(
        uid=data.get("uid", ""),
        name=data.get("name", ""),
        pts=int(data.get("pts", 0)),
        delta7d=int(data.get("delta7d", 0)),
        rank=int(data.get("rank", 0)),
    )


def to_leaderboard_snapshot(doc: dict[str, Any]) -> LeaderboardSnapshot:
    entries_raw = doc.get("entries", []) or []
    rising_raw = doc.get("risingStars", []) or []
    return LeaderboardSnapshot(
        region=doc.get("region", ""),
        sport=doc.get("sport", ""),
        entries=[_parse_leaderboard_entry(e) for e in entries_raw],
        rising_stars=[_parse_rising_star_entry(r) for r in rising_raw],
        last_updated=doc.get("lastUpdated"),
    )


def _parse_geo_coordinates(value: Any) -> GeoCoordinates:
    """Parse a Firestore GeoPoint or a plain ``{lat, lng}`` dict into
    :class:`GeoCoordinates`.

    Firestore returns native ``GeoPoint`` instances (with ``latitude`` and
    ``longitude`` attributes) for fields declared as GeoPoint in the schema.
    Tests and seed tooling tend to pass plain dicts, so we accept both.
    """
    if value is None:
        raise ValueError("Missing required field: coordinates")
    latitude = getattr(value, "latitude", None)
    longitude = getattr(value, "longitude", None)
    if latitude is not None and longitude is not None:
        try:
            return GeoCoordinates(lat=float(latitude), lng=float(longitude))
        except (TypeError, ValueError, ValidationError) as exc:
            raise ValueError(f"Invalid coordinate value in GeoPoint: {value!r}") from exc
    if isinstance(value, dict):
        if "lat" not in value or "lng" not in value:
            raise ValueError(f"Missing 'lat' or 'lng' in coordinates dict: {value!r}")
        try:
            return GeoCoordinates(
                lat=float(value["lat"]),
                lng=float(value["lng"]),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ValueError(f"Invalid coordinate value in dict: {value!r}") from exc
    raise ValueError(f"Unsupported coordinates value: {type(value)!r}")


def to_venue_summary(doc: dict[str, Any], venue_id: str | None = None) -> VenueSummary:
    resolved_id = venue_id or doc.get("id")
    if not resolved_id:
        raise ValueError("Missing required field: venue_id")
    sports_raw = _require(doc, "sports")
    sports = [SportEnum(s) for s in sports_raw]
    return VenueSummary.model_validate(
        {
            "venueId": resolved_id,
            "name": _require(doc, "name"),
            "coordinates": _parse_geo_coordinates(doc.get("coordinates")),
            "area": _require(doc, "area"),
            "sports": sports,
            "courtCount": doc.get("courtCount"),
            "indoor": doc.get("indoor"),
            "placeId": doc.get("placeId"),
        }
    )


def to_ticker_event(doc: dict[str, Any], event_id: str = "") -> TickerEvent:
    loser_tier = doc.get("loserTier")
    tier_before = doc.get("tierBefore")
    tier_after = doc.get("tierAfter")
    return TickerEvent(
        event_id=event_id or doc.get("id", ""),
        type=TickerEventTypeEnum(_require(doc, "type")),
        sport=SportEnum(_require(doc, "sport")),
        region=_require(doc, "region"),
        created_at=_require(doc, "createdAt"),
        expires_at=_require(doc, "expiresAt"),
        # upset fields
        winner_uid=doc.get("winnerUid"),
        winner_name=doc.get("winnerName"),
        loser_tier=TierEnum(loser_tier) if loser_tier else None,
        delta=int(doc.get("delta", 0)),
        # shared subject fields
        user_uid=doc.get("userUid"),
        user_name=doc.get("userName"),
        # personal_best fields
        new_pts=doc.get("newPts"),
        previous_best=doc.get("previousBest"),
        # win_streak fields
        streak=doc.get("streak"),
        # tier_crossed fields
        tier_before=TierEnum(tier_before) if tier_before else None,
        tier_after=TierEnum(tier_after) if tier_after else None,
        direction=doc.get("direction"),
    )
