from __future__ import annotations

# Journal field validation limits
JOURNAL_TITLE_MAX = 200
JOURNAL_BODY_MAX = 5000
JOURNAL_TAGS_MAX = 20
JOURNAL_CLIENT_REQUEST_ID_MAX = 128

# Improve API pagination defaults
JOURNAL_LIST_DEFAULT_LIMIT = 20
JOURNAL_LIST_MAX_LIMIT = 50

# Cached list caps
JOURNAL_RECENT_MAX = 10

# North-star validation
NORTH_STAR_GOAL_MAX = 500

# Abuse/spam guard
JOURNAL_CREATE_RATE_LIMIT_PER_HOUR = 50

# Lab API pagination defaults
LAB_PROGRESSION_DEFAULT_LIMIT = 50
LAB_PROGRESSION_MAX_LIMIT = 200
LAB_RIVALRY_DEFAULT_LIMIT = 10
LAB_RIVALRY_MAX_LIMIT = 20

# Ticker pagination defaults
TICKER_LIST_DEFAULT_LIMIT = 20
TICKER_LIST_MAX_LIMIT = 50

# Streak milestone thresholds (used for badges / notifications)
STREAK_MILESTONES: frozenset[int] = frozenset({3, 5, 10, 20})

# Discovery feed
DISCOVERY_FEED_DEFAULT_LIMIT = 25

# League divisions
DIVISION_TARGET_SIZE = 6

# Account deletion (tombstone / anonymize-in-place)
DELETED_PLAYER_NAME = "Deleted Player"

# Venue search
VENUE_SEARCH_MAX_RESULTS = 5
VENUE_SEARCH_LOCATION_BIAS_RADIUS_M = 5000
VENUE_SEARCH_CACHE_MAX_SIZE = 256
VENUE_SEARCH_RATE_LIMIT_PER_MINUTE = 10
