#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/constants.py                                                            #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 22nd 2025 02:40:33 pm                                                 #
# Modified   : Wednesday October 1st 2025 11:14:58 pm                                              #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ #
DEFAULT_GENAI_MODEL = "gemini-2.5-flash"
DEFAULT_ERROR_TOLERANCE = 5
DEFAULT_CONCURRENCY = 10
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BACKOFF = 2.0
DEFAULT_JSON_INDENT = 2

# --- Archive engine (Arctic Shift) ------------------------------------------------------------- #
# A community mirror of Reddit built on the surviving Pushshift corpus. It is not Reddit's
# API: no OAuth, no 100 req/min quota, and no ~1000-item listing ceiling, which is the only
# way to reach submissions older than the live listing can reach.
ARCHIVE_BASE_URL = "https://arctic-shift.photon-reddit.com/api"
# The service rejects anything larger with a 400; this is the ceiling, not a preference.
ARCHIVE_PAGE_LIMIT = 100
# Requests are unauthenticated but the service still expects an identifiable client; the
# default urllib/aiohttp agent is answered with a 403.
ARCHIVE_USER_AGENT = "ask-reddit/0.1 (https://github.com/john-james-ai/ask-reddit)"
# Measured on a week of r/ChatGPT comments. Concurrency alone stops helping once it exceeds
# the window count, since a window is the unit of parallelism; the two are tuned together.
# Against 6-hour windows: 8 -> 75s, 16 -> 42s, 24 -> 25s, with no throttling at any level.
# 16 is taken rather than the fastest measured, to leave headroom for a second run sharing
# the same host and because the gain past it is inside the run-to-run noise.
DEFAULT_ARCHIVE_CONCURRENCY = 16
# The archive signals "slow down" with 422 rather than 429, so it has to be retried like
# throttling instead of being treated as the malformed request the status usually means.
# It also has a harder limit behind that which answers with a genuine 429; concurrency of
# 32 against 2-hour windows reaches it, and 16 against 6-hour windows does not.
ARCHIVE_THROTTLE_STATUS = 422
# Ceiling on the exponential retry backoff. Retries are what carry a run through a burst
# of throttling, so the ramp has to be allowed to grow well past the first few seconds.
ARCHIVE_MAX_BACKOFF = 60.0
# A span's comments are collected from the span window extended by this many days, so
# replies that arrive after the month closes are still attached to their submission.
DEFAULT_COMMENT_GRACE_DAYS = 3
# Windows the span is cut into before fetching. Pagination within a window is serial
# (it follows a `created_utc` cursor), so the window count is what creates the parallelism:
# a 24-hour window gives a month only 31 chains, which caps concurrency below its setting.
# Six hours roughly halved elapsed time in measurement; three did not improve on it further.
ARCHIVE_WINDOW_HOURS = 6

# Batches are always whole calendar months. This is the single definition of the
# span label used for filenames, resume checks, and batch boundaries.
MONTH_SPAN_FORMAT = "%Y-%m"

# Maximum serialized bytes sent in a single token-count request. Well under the
# API request ceiling, so a large month is counted in several passes.
DEFAULT_TOKEN_COUNT_CHUNK_BYTES = 1_000_000
