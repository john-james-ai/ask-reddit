#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.3.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : constants.py                                                                        #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 22nd 2025 02:40:33 pm                                                 #
# Modified   : Wednesday July 29th 2026 01:05:37 am                                                #
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

# --- Arctic Shift engine ----------------------------------------------------------------------- #
# A community mirror of Reddit built on the surviving Pushshift corpus. It is not Reddit's
# API: no OAuth, no 100 req/min quota, and no ~1000-item listing ceiling, which is the only
# way to reach submissions older than the live listing can reach.
ARCTICSHIFT_BASE_URL = "https://arctic-shift.photon-reddit.com/api"
# The service rejects anything larger with a 400; this is the ceiling, not a preference.
ARCTICSHIFT_PAGE_LIMIT = 100
# Requests are unauthenticated but the service still expects an identifiable client; the
# default urllib/aiohttp agent is answered with a 403.
ARCTICSHIFT_USER_AGENT = "ask-reddit/0.1 (https://github.com/john-james-ai/ask-reddit)"
# A ceiling, not an operating value: the limiter starts below it and finds its own level.
# No fixed number can be right here, because Arctic Shift's capacity is shared, rolling, and
# published without a "remaining" count to divide.
DEFAULT_ARCTICSHIFT_CONCURRENCY = 16
# Where the limiter opens. Low enough that a depleted window is not walked straight into,
# and a clean run climbs back to the ceiling in well under a minute.
ARCTICSHIFT_INITIAL_CONCURRENCY = 4
# Clean rounds to sit still after a luff before probing upward again. The limiter
# approaches its level from below, so a luff means the last probe was one step too far and
# the step below it is the answer; the hold is what stops it from immediately re-probing.
ARCTICSHIFT_HOLD_ROUNDS = 2
# Luffing again at a level already known to luff doubles the hold, up to this. That is what
# turns the search into a settle: a level that keeps failing gets revisited ever more
# rarely, so a long run spends its time at the equilibrium rather than hunting around it.
ARCTICSHIFT_MAX_HOLD_ROUNDS = 64
# Arctic Shift signals "slow down" with 422 rather than 429, so it has to be retried like
# throttling instead of being treated as the malformed request the status usually means.
# It also has a harder limit behind that which answers with a genuine 429; concurrency of
# 32 against 2-hour windows reaches it, and 16 against 6-hour windows does not.
ARCTICSHIFT_THROTTLE_STATUS = 422
# Ceiling on the exponential retry backoff. Retries are what carry a run through a burst
# of throttling, so the ramp has to be allowed to grow well past the first few seconds.
ARCTICSHIFT_MAX_BACKOFF = 60.0
# Seconds until the rolling request window refills, sent on every response. This is the
# only exact number the service gives about its own limit, so a 429 is answered by waiting
# it out rather than by guessing at a backoff.
ARCTICSHIFT_RESET_HEADER = "x-ratelimit-reset"
# Ceiling on how long that header is trusted for. Observed values are single-digit seconds;
# anything far larger is a malformed or absolute value being read as a duration, and a run
# should fall back to its own backoff rather than park for the rest of the afternoon.
ARCTICSHIFT_MAX_RESET_WAIT = 120.0
# A paused fleet is waiting on one shared deadline, so it would otherwise wake as one and
# spend the refilled window in a single burst. Releasing across a second of jitter is what
# lets the window drain evenly instead.
ARCTICSHIFT_RESUME_JITTER = 1.0
# Higher than the live engines' budget. Arctic Shift's limit is rolling rather than
# per-request, so a run that meets a depleted one has to out-wait it; five attempts is
# about a minute of patience, which is not enough to cross it.
DEFAULT_ARCTICSHIFT_MAX_RETRIES = 10
# Deliberately generous, because "failure" here means a whole span, not one submission.
# A throttled span is transient and costs nothing to retry on the next run, so a long
# backfill should record it and carry on rather than abandon every span behind it.
DEFAULT_ARCTICSHIFT_TOLERANCE = 100
# A span's comments are collected from the span window extended by this many days, so
# replies that arrive after the month closes are still attached to their submission.
DEFAULT_COMMENT_GRACE_DAYS = 3
# Windows the span is cut into before fetching. Pagination within a window is serial (it
# follows a `created_utc` cursor), so the window count is what creates the parallelism.
#
# Every window costs at least one request whether it returns three records or three
# hundred, so cutting finer buys parallelism by spending requests. A day is the point where
# that trade stops mattering in either direction: on a dense subreddit a 24-hour window
# already holds ~49 pages, so the per-window overhead is ~2% and slicing finer saves
# nothing; on a sparse one the whole month costs ~31 requests either way. A month is also
# ~31 windows, which is more parallelism than the limiter will ever ask for.
ARCTICSHIFT_WINDOW_HOURS = 24

# Batches are always whole calendar months. This is the single definition of the
# span label used for filenames, resume checks, and batch boundaries.
MONTH_SPAN_FORMAT = "%Y-%m"

# Maximum serialized bytes sent in a single token-count request. Well under the
# API request ceiling, so a large month is counted in several passes.
DEFAULT_TOKEN_COUNT_CHUNK_BYTES = 1_000_000
