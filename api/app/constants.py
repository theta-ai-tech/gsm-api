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
