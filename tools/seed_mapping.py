from typing import Any, Dict

from app.models import (
    CursorBundle,
    JournalEntry,
    JournalEntrySummary,
    League,
    LeagueMember,
    LeagueSummary,
    Match,
    MatchParticipant,
    MatchReflection,
    MatchScore,
    PerSportLevels,
    PerSportRankings,
    PointHistoryEntry,
    PrivateUserProfile,
    SetScore,
    SportRanking,
    TierConfig,
    TierThreshold,
    UserCompletedMatchSummary,
    UserMatchSummary,
)


def _sport_ranking_to_dict(ranking: SportRanking) -> Dict[str, Any]:
    return {
        "sport": ranking.sport.value,
        "pts": ranking.pts,
        "globalRanking": ranking.global_ranking,
        "tier": ranking.tier.value if ranking.tier else None,
        "registrationTier": (
            ranking.registration_tier.value if ranking.registration_tier else None
        ),
        "lastUpdated": ranking.last_updated,
    }


def _per_sport_rankings_to_dict(rankings: PerSportRankings) -> Dict[str, Any]:
    return {
        "tennis": _sport_ranking_to_dict(rankings.tennis) if rankings.tennis else None,
        "padel": _sport_ranking_to_dict(rankings.padel) if rankings.padel else None,
        "pickleball": _sport_ranking_to_dict(rankings.pickleball) if rankings.pickleball else None,
    }


def _per_sport_levels_to_dict(levels: PerSportLevels) -> Dict[str, Any]:
    return {
        "tennis": levels.tennis.value if levels.tennis else None,
        "padel": levels.padel.value if levels.padel else None,
        "pickleball": levels.pickleball.value if levels.pickleball else None,
    }


def _league_summary_to_dict(summary: LeagueSummary) -> Dict[str, Any]:
    return {
        "leagueId": summary.league_id,
        "name": summary.name,
        "sport": summary.sport.value,
        "status": summary.status.value,
        "role": summary.role.value if summary.role else None,
    }


def _user_match_summary_to_dict(summary: UserMatchSummary) -> Dict[str, Any]:
    return {
        "matchId": summary.match_id,
        "sport": summary.sport.value,
        "scheduledAt": summary.scheduled_at,
        "leagueId": summary.league_id,
        "courtId": summary.court_id,
        "opponents": [{"uid": opp.uid, "name": opp.name} for opp in summary.opponents],
    }


def _user_completed_match_summary_to_dict(summary: UserCompletedMatchSummary) -> Dict[str, Any]:
    return {
        "matchId": summary.match_id,
        "sport": summary.sport.value,
        "finishedAt": summary.finished_at,
        "result": summary.result.value if summary.result else None,
        "scoreText": summary.score_text,
        "leagueId": summary.league_id,
    }


def _journal_entry_summary_to_dict(summary: JournalEntrySummary) -> Dict[str, Any]:
    return {
        "entryId": summary.entry_id,
        "createdAt": summary.created_at,
        "title": summary.title,
        "matchId": summary.match_id,
        "sport": summary.sport.value if summary.sport else None,
        "entryType": summary.entry_type.value if summary.entry_type else None,
    }


def _cursors_to_dict(cursors: CursorBundle | None) -> Dict[str, Any] | None:
    if cursors is None:
        return None
    return {
        "upcomingMatches": cursors.upcoming_matches,
        "completedMatches": cursors.completed_matches,
        "journal": cursors.journal,
    }


def user_to_firestore_doc(user: PrivateUserProfile) -> Dict[str, Any]:
    return {
        "uid": user.uid,
        "name": user.name,
        "email": user.email,
        "profileUrl": str(user.profile_url) if user.profile_url else None,
        "phone": user.phone,
        "rankings": _per_sport_rankings_to_dict(user.rankings),
        "preferences": {
            "area": user.preferences.area,
            "levels": _per_sport_levels_to_dict(user.preferences.levels),
            "sports": [sport.value for sport in user.preferences.sports],
        },
        "leaguesActive": [_league_summary_to_dict(l) for l in user.leagues_active],
        "leaguesCompleted": [_league_summary_to_dict(l) for l in user.leagues_completed],
        "upcomingMatches": [_user_match_summary_to_dict(m) for m in user.upcoming_matches],
        "completedMatches": [_user_completed_match_summary_to_dict(m) for m in user.completed_matches],
        "journalRecent": [_journal_entry_summary_to_dict(j) for j in user.journal_recent],
        "cursors": _cursors_to_dict(user.cursors),
    }


def league_to_firestore_doc(league: League) -> Dict[str, Any]:
    return {
        "name": league.name,
        "sport": league.sport.value,
        "season": league.season,
        "status": league.status.value,
        "ownerUid": league.owner_uid,
        "meta": league.meta or {},
    }


def league_member_to_firestore_doc(member: LeagueMember) -> Dict[str, Any]:
    return {
        "uid": member.uid,
        "role": member.role.value,
        "status": member.status.value,
        "joinedAt": member.joined_at,
        "stats": member.stats or {},
    }


def _set_score_to_dict(score: SetScore) -> Dict[str, Any]:
    return {
        "p1Games": score.p1_games,
        "p2Games": score.p2_games,
        "tiebreakScore": score.tiebreak_score,
    }


def _match_score_to_dict(score: MatchScore | None) -> Dict[str, Any] | None:
    if score is None:
        return None
    return {
        "sets": [_set_score_to_dict(s) for s in score.sets],
        "winnerUid": score.winner_uid,
        "retired": score.retired,
    }


def _participant_to_dict(p: MatchParticipant) -> Dict[str, Any]:
    return {
        "uid": p.uid,
        "team": p.team,
        "role": p.role.value,
        "result": p.result.value if p.result else None,
    }


def match_to_firestore_doc(match: Match) -> Dict[str, Any]:
    return {
        "sport": match.sport.value,
        "status": match.status.value,
        "scheduledAt": match.scheduled_at,
        "finishedAt": match.finished_at,
        "leagueId": match.league_id,
        "courtId": match.court_id,
        "participants": [_participant_to_dict(p) for p in match.participants],
        "participantUids": match.participant_uids,
        "resultByUser": (
            {uid: result.value for uid, result in match.result_by_user.items()}
            if match.result_by_user
            else None
        ),
        "score": _match_score_to_dict(match.score),
    }


def _match_reflection_to_dict(reflection: MatchReflection | None) -> Dict[str, Any] | None:
    if reflection is None:
        return None
    return {
        "wentWell": reflection.went_well,
        "wentWrong": reflection.went_wrong,
        "opponentWeak": reflection.opponent_weak,
        "opponentStrong": reflection.opponent_strong,
        "aiSummary": reflection.ai_summary,
        "reflectionVersion": reflection.reflection_version,
    }


def _tier_threshold_to_dict(t: TierThreshold) -> Dict[str, Any]:
    return {
        "tier": t.tier.value,
        "minPts": t.min_pts,
        "maxPts": t.max_pts,
        "label": t.label,
        "color": t.color,
    }


def tier_config_to_firestore_doc(config: TierConfig) -> Dict[str, Any]:
    return {
        "thresholds": [_tier_threshold_to_dict(t) for t in config.thresholds],
        "version": config.version,
        "updatedAt": config.updated_at,
    }


def point_history_entry_to_firestore_doc(entry: PointHistoryEntry) -> Dict[str, Any]:
    return {
        "sport": entry.sport.value,
        "pts": entry.pts,
        "delta": entry.delta,
        "reason": entry.reason.value,
        "matchId": entry.match_id,
        "opponentUid": entry.opponent_uid,
        "opponentPtsBefore": entry.opponent_pts_before,
        "leagueId": entry.league_id,
        "createdAt": entry.created_at,
        "tierBefore": entry.tier_before.value if entry.tier_before else None,
        "tierAfter": entry.tier_after.value if entry.tier_after else None,
    }


def journal_entry_to_firestore_doc(entry: JournalEntry) -> Dict[str, Any]:
    return {
        "title": entry.title,
        "body": entry.body,
        "tags": entry.tags,
        "createdAt": entry.created_at,
        "matchId": entry.match_id,
        "sport": entry.sport.value if entry.sport else None,
        "visibility": entry.visibility.value,
        "entryType": entry.entry_type.value,
        "durationMinutes": entry.duration_minutes,
        "trainingFocus": [f.value for f in entry.training_focus],
        "reflection": _match_reflection_to_dict(entry.reflection),
        "scoreText": entry.score_text,
        "result": entry.result.value if entry.result else None,
        "clientRequestId": entry.client_request_id,
        "isDeleted": entry.is_deleted,
        "deletedAt": entry.deleted_at,
    }
