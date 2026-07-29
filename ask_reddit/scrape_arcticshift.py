#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/scrape_arcticshift.py                                                       #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Monday July 27th 2026 01:55:00 pm                                                   #
# Modified   : Monday July 27th 2026 01:55:00 pm                                                   #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2026 John James                                                                 #
# ================================================================================================ #
"""Arctic Shift Scrape Module.

A third engine alongside :mod:`ask_reddit.scrape_sync` and :mod:`ask_reddit.scrape_async`,
reading from the Arctic Shift rather than from Reddit itself. It exists because the
other two cannot reach the data: every Reddit listing endpoint is capped at roughly 1000
items, so ``subreddit.new(limit=None)`` returns about a week of a busy subreddit no matter
how many months are requested. Arctic Shift is queried by time range and has no such cap.

The shape of the work is inverted relative to the live engines. Those walk one listing
newest-first and discover each batch boundary as they go; here the span boundaries are known
up front, so each needed month is fetched directly and no walk is required.

Two properties of Arctic Shift drive the rest of the design:

Comments arrive as a flat stream keyed by ``link_id`` rather than as a tree, so there is no
"load more comments" node and nothing corresponding to ``replace_more``. Whole windows of
comments are fetched at once and grouped onto their submissions afterwards, costing about
one request per hundred comments instead of at least one per submission.

Pagination follows a ``created_utc`` cursor and is therefore serial within any one time
range. Concurrency comes from cutting a span into windows and paginating those in parallel,
bounded by a semaphore. There is no per-account quota to cooperate with, so unlike the async
engine the semaphore is the only thing pacing the run.
"""
import asyncio
import logging
import random
import sys
from contextlib import asynccontextmanager
from collections import Counter
from datetime import datetime, timedelta
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Tuple,
)

import aiohttp
from tqdm.auto import tqdm

from ask_reddit.constants import (
    ARCTICSHIFT_HOLD_ROUNDS,
    ARCTICSHIFT_MAX_HOLD_ROUNDS,
    ARCTICSHIFT_BASE_URL,
    ARCTICSHIFT_INITIAL_CONCURRENCY,
    ARCTICSHIFT_MAX_BACKOFF,
    ARCTICSHIFT_MAX_RESET_WAIT,
    ARCTICSHIFT_PAGE_LIMIT,
    ARCTICSHIFT_RESET_HEADER,
    ARCTICSHIFT_RESUME_JITTER,
    ARCTICSHIFT_THROTTLE_STATUS,
    ARCTICSHIFT_WINDOW_HOURS,
    DEFAULT_ARCTICSHIFT_CONCURRENCY,
    DEFAULT_ARCTICSHIFT_MAX_RETRIES,
    DEFAULT_ARCTICSHIFT_TOLERANCE,
    DEFAULT_COMMENT_GRACE_DAYS,
    DEFAULT_RETRY_BACKOFF,
)
from ask_reddit.date import DateTime
from ask_reddit.model import GenAIModel
from ask_reddit.persist import FileManager
from ask_reddit.print import Printer
from ask_reddit.scrape import BaseRedditScraper

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #

# Authors and bodies Arctic Shift records as removed. The live engines skip these implicitly,
# since PRAW reports a deleted author as None; here they arrive as literal strings.
REMOVED_MARKERS = frozenset({"[deleted]", "[removed]"})


class EquilibriumLimiter:
    """Search for the number of in-flight requests Arctic Shift will sustain, then hold it.

    Arctic Shift publishes ``x-ratelimit-reset`` but no remaining count, so there is no
    budget to divide and no safe concurrency to compute ahead of time. Capacity is shared
    with every other user and moves minute to minute, so it has to be found by feel.

    The rule is the sailor's, easing a headsail downwind: let it out gently until the luff
    shows, pull in one notch, and cleat it. Check again later by easing out one more notch;
    if it luffs again, come back and sit longer before the next check. Each repeat luff at a
    level already known to be too far doubles the wait, so the limiter converges on the
    equilibrium and stays there instead of hunting around it.

    This is deliberately not AIMD. Congestion control halves on loss and climbs again
    forever, because its goal is to keep yielding so competing flows get a fair share. There
    is nothing to be fair to here and no reason to keep giving ground: the goal is to find
    one level and work at it. Approaching from below is what makes the gentle step correct,
    since the limiter is never wildly over and never needs a violent correction.

    Only the 422 "slow down" narrows the limit. A 429 says the rolling request budget is
    spent, which is a fact about a clock rather than about how many connections the service
    wants open: inside a depleted window every request fails however few are in flight, so
    reading those as luffs walks the limit to the floor for something width cannot fix.
    Those are answered by ``pause`` instead, which stops the whole fleet until the window
    refills and leaves the settled width alone.

    Args:
        ceiling (int): Never exceed this many in flight. The user's ``--concurrency``.
        initial (int): Where the limiter opens, below any plausible equilibrium.
        floor (int): Never drop below this, so a run cannot stall entirely.
    """

    def __init__(self, ceiling: int, initial: int, floor: int = 1) -> None:
        self._ceiling = max(1, ceiling)
        self._floor = max(1, min(floor, self._ceiling))
        self._limit = max(self._floor, min(initial, self._ceiling))
        self._in_flight = 0
        self._successes = 0
        # Clean rounds still owed before the next upward probe.
        self._hold_remaining = 0
        self._hold_rounds = ARCTICSHIFT_HOLD_ROUNDS
        # The limit that was in force at the last luff, so a repeat at the same level can
        # be told from a luff at a new one.
        self._last_luff_at: Optional[int] = None
        # Bumped on every decrease. A request carries the epoch it was issued under, so a
        # failure reported by a request that was already in flight when the cut happened
        # can be ignored. Without it one luff fails every in-flight request at once and
        # steps down once per failure, walking the limit to the floor for a single event.
        self._epoch = 0
        self._cond = asyncio.Condition()
        # Loop time before which no new request may be issued, set when the service reports
        # its request window is spent. Zero whenever the window is believed to be open.
        self._resume_at = 0.0
        # Reported per span, so a run can say where it settled and how hard it looked.
        self.luffs = 0
        self.pauses = 0
        self.paused_seconds = 0.0
        self.low_water = self._limit
        self.high_water = self._limit

    @property
    def limit(self) -> int:
        """The current in-flight ceiling."""
        return self._limit

    def reset_marks(self) -> None:
        """Zero the per-span counters, leaving the settled limit alone.

        The limit itself carries across spans deliberately: what the service sustained a
        minute ago is the best starting guess for the next span. Only the reporting resets,
        so a span's line describes that span rather than the whole run.
        """
        self.luffs = 0
        self.pauses = 0
        self.paused_seconds = 0.0
        self.low_water = self._limit
        self.high_water = self._limit

    @property
    def holding(self) -> bool:
        """True while the limiter is cleated and not probing upward."""
        return self._hold_remaining > 0

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[int]:
        """Hold one in-flight slot, yielding the epoch the request is issued under.

        Waits out any pause before taking a slot rather than after, so a paused fleet holds
        no slots at all and the width is free for whoever is first through the gate.
        """
        loop = asyncio.get_running_loop()
        while (delay := self._resume_at - loop.time()) > 0:
            # Jittered past the deadline, because the pause is one instant shared by the
            # whole fleet: without it they wake together and re-trip the window as one.
            await asyncio.sleep(delay + random.uniform(0, ARCTICSHIFT_RESUME_JITTER))
        async with self._cond:
            while self._in_flight >= self._limit:
                await self._cond.wait()
            self._in_flight += 1
            epoch = self._epoch
        try:
            yield epoch
        finally:
            async with self._cond:
                self._in_flight -= 1
                self._cond.notify()

    async def on_success(self) -> None:
        """Record a clean response; ease out by one once the hold has been served."""
        async with self._cond:
            self._successes += 1
            if self._successes < self._limit:
                return
            # A full round at the current width came back clean.
            self._successes = 0
            if self._hold_remaining > 0:
                self._hold_remaining -= 1
                return
            if self._limit < self._ceiling:
                self._limit += 1
                self.high_water = max(self.high_water, self._limit)
                self._cond.notify()

    def pause(self, seconds: float) -> float:
        """Hold every new request for ``seconds``, without touching the settled width.

        Concurrent 429s all report the same window, so the deadlines they ask for are the
        same deadline seen from slightly different moments. Extending rather than replacing
        keeps the last, longest one instead of letting a straggler's shorter view of it cut
        the wait short.

        Args:
            seconds (float): How long the service says its window needs to refill.

        Returns:
            float: Seconds actually added to the pause; zero if one already ran longer.
        """
        if seconds <= 0:
            return 0.0
        now = asyncio.get_running_loop().time()
        deadline = now + seconds
        if deadline <= self._resume_at:
            return 0.0
        added = deadline - max(self._resume_at, now)
        self._resume_at = deadline
        self.pauses += 1
        self.paused_seconds += added
        return added

    async def on_throttle(self, epoch: int) -> None:
        """Record a luff: come in one notch and cleat, at most once per epoch."""
        async with self._cond:
            # Issued before the last cut, so this failure is already accounted for.
            if epoch != self._epoch:
                return
            self.luffs += 1
            if self._last_luff_at == self._limit:
                # Already known to be too far. Sit twice as long before looking again.
                self._hold_rounds = min(self._hold_rounds * 2, ARCTICSHIFT_MAX_HOLD_ROUNDS)
            else:
                self._hold_rounds = ARCTICSHIFT_HOLD_ROUNDS
            self._last_luff_at = self._limit
            self._hold_remaining = self._hold_rounds
            self._limit = max(self._floor, self._limit - 1)
            self.low_water = min(self.low_water, self._limit)
            self._successes = 0
            self._epoch += 1


def reset_wait(headers: Mapping[str, str], fallback: float) -> float:
    """Read how long until Arctic Shift's request window refills.

    ``x-ratelimit-reset`` is seconds until the rolling window is whole again, and it is the
    only exact statement the service makes about its own limit, so it beats any backoff
    guessed from the outside. ``Retry-After`` is honoured behind it for the ordinary case
    where a proxy in front answers instead.

    Args:
        headers (Mapping[str, str]): Response headers from the throttled request.
        fallback (float): Wait to use when no header is present or one cannot be believed.

    Returns:
        float: Seconds to wait before issuing anything further.
    """
    raw = headers.get(ARCTICSHIFT_RESET_HEADER) or headers.get("Retry-After")
    if raw is None:
        return fallback
    try:
        seconds = float(raw)
    except ValueError:
        # Retry-After also comes as an HTTP date, and the absolute companion header
        # ``x-ratelimit-reset-at`` is epoch milliseconds. Neither is a duration.
        return fallback
    # Observed resets are single-digit seconds. A wildly larger one is a different unit or
    # a different meaning being read as a duration, and parking the run on it would cost
    # more than the backoff it replaced.
    if seconds <= 0 or seconds > ARCTICSHIFT_MAX_RESET_WAIT:
        return fallback
    return seconds


class _SubredditLog(logging.LoggerAdapter):
    """Tag every message with the subreddit it came from.

    A batch runs many subreddits through one log file in sequence, and a bare
    "Failed to fetch span '2026-06'" cannot be attributed to any of them afterwards.
    """

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> Tuple[str, MutableMapping[str, Any]]:
        # `extra` is Optional on the base class, so it is read defensively rather than
        # subscripted; an adapter built without it still logs, just untagged.
        subreddit = (self.extra or {}).get("subreddit", "?")
        return f"[r/{subreddit}] {msg}", kwargs


class ArcticShiftScraper(BaseRedditScraper[aiohttp.ClientSession]):
    """Scrape submissions and comments for a subreddit from the Arctic Shift.

    Output is identical in schema and batching to the live engines, so files written here
    are interchangeable with theirs. What differs is reach: the live engines are bounded by
    Reddit's listing cap and request quota, while this one is bounded only by what the
    archive holds.

    Arctic Shift trails the live site by roughly an hour, so the current month is still
    better served by the async engine. Everything behind it is only reachable here.

    Args:
        scraper (aiohttp.ClientSession): Open HTTP session used for Arctic Shift requests. The
            caller owns the session and is responsible for closing it.
        model (GenAIModel): Generative AI helper used for token accounting.
        printer (Printer): Printer instance for formatted summaries.
        subreddit (str): Subreddit name to scrape (e.g., 'ChatGPT').
        months (int): Number of past months to include in the scrape.
        filemanager (FileManager): FileManager used to persist batches.
        tolerance (int): Consecutive span failures tolerated before the run aborts. A
            failure here is a whole span rather than one submission, and a span costs
            nothing to retry on a later run, so this is far higher than the live engines'.
        force (bool): When True, scrape the full requested window instead of resuming
            from what is already on file.
        verbose (bool): When True, progress and summary output is written to the console.
        concurrency (int): Maximum concurrent Arctic Shift requests.
        max_retries (int): Number of attempts for a retriable request.
        retry_backoff (float): Base backoff seconds used when throttled.
        comment_grace_days (int): Days past the end of a span to keep collecting comments,
            so late replies still reach their submission.
        window_hours (int): Size of the time slices a span is cut into. Pagination is
            serial within a slice, so this is what bounds how much of ``concurrency``
            can actually be used.

    Examples:
        >>> async with aiohttp.ClientSession() as session:
        ...     scraper = ArcticShiftScraper(scraper=session, model=model, printer=printer,
        ...                                    subreddit='ChatGPT', months=18,
        ...                                    filemanager=file_manager)
        ...     await scraper.scrape()
    """

    def __init__(
        self,
        scraper: aiohttp.ClientSession,
        model: GenAIModel,
        printer: Printer,
        subreddit: str,
        months: int,
        filemanager: FileManager,
        tolerance: int = DEFAULT_ARCTICSHIFT_TOLERANCE,
        force: bool = False,
        verbose: bool = False,
        *,
        concurrency: int = DEFAULT_ARCTICSHIFT_CONCURRENCY,
        max_retries: int = DEFAULT_ARCTICSHIFT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
        comment_grace_days: int = DEFAULT_COMMENT_GRACE_DAYS,
        window_hours: int = ARCTICSHIFT_WINDOW_HOURS,
        **kwargs,
    ) -> None:
        super().__init__(
            scraper=scraper,
            model=model,
            printer=printer,
            subreddit=subreddit,
            months=months,
            filemanager=filemanager,
            tolerance=tolerance,
            force=force,
            verbose=verbose,
        )
        self._concurrency = concurrency
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._comment_grace = timedelta(days=comment_grace_days)
        self._window_hours = window_hours
        self._limiter = EquilibriumLimiter(
            ceiling=concurrency, initial=min(ARCTICSHIFT_INITIAL_CONCURRENCY, concurrency)
        )
        # Comments whose submission falls outside the span being assembled. Counted rather
        # than dropped silently, so a run can report how much it could not attach.
        self._n_orphan_comments = 0
        # Spans that were attempted and did not produce a batch. A run that throttles
        # itself to death otherwise prints the same closing summary as one that worked,
        # which is the wrong thing to hand a batch driving 121 subreddits unattended.
        self._n_spans_failed = 0
        # Throttled requests are counted and reported once per span. Logging each retry
        # produced ~14k lines from a handful of small test runs, which buries every other
        # line in the file; the count is the part worth keeping.
        self._throttles: Counter = Counter()
        self._log = _SubredditLog(logger, {"subreddit": subreddit})

    @property
    def failed(self) -> bool:
        """True when spans were attempted and none were written."""
        return self._n_spans_failed > 0 and self._n_batches == 0

    @property
    def description(self) -> Dict:
        """Return a brief description of the scraping job."""
        return {
            "Subreddit": f"r/{self._subreddit}",
            "Time Period": f"Last {self._months} months",
            "Source": "Arctic Shift",
            "Concurrency": f"{self._limiter.limit} (adaptive, max {self._concurrency})",
            "Window": f"{self._window_hours}h",
        }

    async def scrape(self) -> None:
        """Fetch every needed span from Arctic Shift and persist each as a batch."""
        self._startup()
        # Named explicitly, because the log is otherwise silent about where the data came
        # from: a clean run mentions Arctic Shift nowhere, and the URL surfaces only by
        # accident inside error messages. A corpus is worth knowing the provenance of.
        self._log.info(
            f"Source: Arctic Shift ({ARCTICSHIFT_BASE_URL}) | window {self._window_hours}h "
            f"| concurrency {self._limiter.limit} (adaptive, max {self._concurrency})"
        )
        # Newest span first, matching the order the live engines walk their listing, so a
        # run interrupted partway leaves behind the same spans either engine would have.
        # The bar advances one step per span: the span count is known up front, so this is
        # a real percentage, and the subreddit is named on it because a batch run has one
        # bar per subreddit and they are otherwise indistinguishable.
        pbar = tqdm(
            range(1, self._months + 1),
            total=self._months,
            desc=f"r/{self._subreddit}",
            unit="month",
        )
        for n in pbar:
            span = DateTime.get_month_st(n)
            pbar.set_postfix_str(span, refresh=False)
            if span not in self._needed_spans:
                self._log.info(f"Skipping span '{span}': already complete on file.")
                continue

            throttles_before = Counter(self._throttles)
            self._limiter.reset_marks()

            span_start = DateTime.get_month_dt(n)
            # get_month_dt(0) resolves to the first of next month, so this is correct for
            # the current month as well as for every closed month behind it.
            span_end = DateTime.get_month_dt(n - 1)

            try:
                batch = await self._fetch_span(span_start, span_end, pbar)
            except Exception as e:
                self._consecutive_failures += 1
                self._n_spans_failed += 1
                self._log.error(
                    f"Failed to fetch span '{span}' (consecutive failures: "
                    f"{self._consecutive_failures}): {e}"
                )
                if self._consecutive_failures > self._tolerance:
                    self._log.critical(
                        f"Exceeded failure tolerance of {self._tolerance}. Aborting scrape."
                    )
                    break
                continue
            finally:
                # One line for the span instead of one per retry. Reported even when the
                # span failed, since throttling is usually why it did.
                throttled = self._throttles - throttles_before
                if throttled:
                    breakdown = ", ".join(
                        f"{count}x{status}" for status, count in sorted(throttled.items())
                    )
                    self._log.warning(
                        f"Span '{span}': {sum(throttled.values())} throttled ({breakdown}); "
                        f"settled at concurrency {self._limiter.limit} after "
                        f"{self._limiter.luffs} luff(s) this span "
                        f"(low {self._limiter.low_water}, high {self._limiter.high_water}); "
                        f"waited out {self._limiter.pauses} spent window(s) "
                        f"({self._limiter.paused_seconds:.1f}s)."
                    )

            self._consecutive_failures = 0
            # Set before persisting: _process_batch reads it to name the file.
            self._current_batch_span_str = span
            self._process_batch(batch)

        pbar.close()
        self._wrap_up()

    # -------------------------------------------------------------------------------------------- #
    async def _fetch_span(self, start: datetime, end: datetime, pbar) -> List[Dict]:
        """Return every submission in ``[start, end)``, comments attached.

        Submissions and comments are collected independently and joined afterwards. The
        comment window runs past ``end`` by the grace period, since a reply to a submission
        posted on the last day of a month usually lands in the next one.
        """
        lo, hi = int(start.timestamp()), int(end.timestamp())

        def to_submission(raw: Dict[str, Any]) -> Optional[Dict]:
            # The window bounds are enforced here rather than trusted from the query, so
            # the batch is correct regardless of whether Arctic Shift treats `before` as
            # inclusive. Without this a post at exactly midnight could land in two files.
            created = raw.get("created_utc", 0)
            if not lo <= created < hi:
                return None
            return self._build_submission(raw)

        submissions, comments = await asyncio.gather(
            self._collect("posts/search", start, end, to_submission, f"posts {start:%Y-%m}"),
            self._collect(
                "comments/search",
                start,
                end + self._comment_grace,
                self._build_comment,
                f"comments {start:%Y-%m}",
            ),
        )

        # Index by fullname first so each comment can be matched in a single pass.
        batch: Dict[str, Dict] = {record["submission_id"]: record for record in submissions}

        for link_id, record in comments:
            parent = batch.get(link_id)
            if parent is None:
                # The submission sits outside this span. The span that owns it collects
                # this comment from its own grace window, so it is not lost overall.
                self._n_orphan_comments += 1
                continue
            parent["comments"].append(record)
            self._n_comments += 1

        self._n_submissions += len(batch)
        if pbar is not None:
            # The bar counts spans, so the running totals ride in the postfix rather than
            # in the counter.
            pbar.set_postfix_str(
                f"{start:%Y-%m} | {self._n_submissions} subs, {self._n_comments} cmts",
                refresh=False,
            )

        # Newest first, matching the order `subreddit.new()` yields for the live engines.
        return sorted(batch.values(), key=lambda r: r["created_utc"], reverse=True)

    # -------------------------------------------------------------------------------------------- #
    async def _collect(
        self,
        path: str,
        start: datetime,
        end: datetime,
        mapper: Callable[[Dict[str, Any]], Optional[Any]],
        label: str,
    ) -> List[Any]:
        """Fetch every record in ``[start, end)``, mapped and flattened.

        Pagination follows a ``created_utc`` cursor and cannot be parallelised within a
        single range, so the range is cut into fixed windows that are paginated at once.
        ``mapper`` is applied as each page arrives and anything it rejects is dropped
        immediately; a month of a busy subreddit is hundreds of megabytes of raw archive
        JSON, and only the handful of published fields is worth holding.
        """
        windows = self._windows(start, end)
        self._log.info(f"Fetching {label}: {len(windows)} windows.")
        pages = await asyncio.gather(
            *(self._paginate(path, w_start, w_end, mapper) for w_start, w_end in windows)
        )
        return [record for page in pages for record in page]

    # -------------------------------------------------------------------------------------------- #
    def _windows(self, start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
        """Cut ``[start, end)`` into consecutive windows of ``window_hours``."""
        step = timedelta(hours=self._window_hours)
        windows = []
        cursor = start
        while cursor < end:
            windows.append((cursor, min(cursor + step, end)))
            cursor += step
        return windows

    # -------------------------------------------------------------------------------------------- #
    async def _paginate(
        self,
        path: str,
        start: datetime,
        end: datetime,
        mapper: Callable[[Dict[str, Any]], Optional[Any]],
    ) -> List[Any]:
        """Return every mapped record Arctic Shift holds in ``[start, end)``.

        Both ``after`` and ``before`` are exclusive, so the window is expressed as
        ``(start - 1, end)`` to make it half-open.

        The cursor rewinds to one second *before* the last record of a page rather than
        advancing past it. Many records can share a second, and a page boundary can fall in
        the middle of one; advancing past that second would silently drop whatever remained
        in it. Re-reading the second makes overlap between pages normal, so records are
        de-duplicated by id. The rewind is only taken when it still moves the cursor
        forward, which keeps the loop terminating.
        """
        end_ts = int(end.timestamp())
        # `after` is exclusive, so start one second early to keep the range half-open.
        after = int(start.timestamp()) - 1
        seen: set = set()
        records: List[Any] = []

        while True:
            page = await self._request(
                path,
                {
                    "subreddit": self._subreddit,
                    "after": str(after),
                    "before": str(end_ts),
                    "limit": str(ARCTICSHIFT_PAGE_LIMIT),
                    "sort": "asc",
                },
            )
            if not page:
                return records

            fresh = 0
            for raw in page:
                if raw.get("id") in seen:
                    continue
                seen.add(raw["id"])
                fresh += 1
                record = mapper(raw)
                if record is not None:
                    records.append(record)

            # A short page means the window is exhausted.
            if len(page) < ARCTICSHIFT_PAGE_LIMIT:
                return records

            last_ts = page[-1]["created_utc"]
            # Rewind into the last second so nothing sharing it is skipped. When that
            # would not advance the cursor, a single second holds a full page of records
            # and re-reading it would loop forever, so the second is stepped over instead
            # and the loss is reported rather than passed off as a complete window.
            if last_ts - 1 > after:
                after = last_ts - 1
            else:
                self._log.warning(
                    f"More than {ARCTICSHIFT_PAGE_LIMIT} records share created_utc={last_ts} "
                    f"in r/{self._subreddit}; stepping past it, so some are not captured."
                )
                after = last_ts

    # -------------------------------------------------------------------------------------------- #
    async def _request(self, path: str, params: Dict[str, str]) -> List[Dict]:
        """Perform one archive request, retrying only what is worth retrying.

        A 5xx is a transient server fault and a 429 is ordinary throttling. Arctic Shift
        also answers with 422 and ``"Timeout. Maybe slow down a bit"`` when too many
        requests are open at once, so that status means back off here rather than carrying
        its usual sense of a malformed request. Every other 4xx really is malformed and
        would fail identically however often it were repeated, so it is raised at once
        rather than burning the retry budget.
        """
        url = f"{ARCTICSHIFT_BASE_URL}/{path}"
        retriable = {ARCTICSHIFT_THROTTLE_STATUS, 429}
        for attempt in range(1, self._max_retries + 1):
            # Exponential rather than linear: under a sustained 429 every in-flight
            # request retries together, and a linear ramp has them all arrive again while
            # the limit is still tripped, burning the whole budget in seconds.
            ceiling = min(self._retry_backoff * 2 ** (attempt - 1), ARCTICSHIFT_MAX_BACKOFF)
            # Jittered, because a bare exponential keeps every worker in lockstep: they
            # were throttled together, so they wake together and re-trip the limit as one.
            # Spreading them across the interval is what actually lets the window drain.
            wait = random.uniform(ceiling / 2, ceiling)
            try:
                async with self._limiter.slot() as epoch:
                    async with self._scraper.get(url, params=params) as response:
                        if response.status not in retriable and response.status < 500:
                            response.raise_for_status()
                            payload = await response.json()
                            # Widening is driven from here rather than from the caller, so
                            # only responses the service actually served count as headroom.
                            await self._limiter.on_success()
                            return payload.get("data", [])
                        # Both recorded before the retry decision, so the limiter narrows
                        # and the status is counted even on the attempt that goes on to
                        # raise. 422 and 429 mean different things here -- a soft "slow
                        # down" against a hard rate limit -- and collapsing them into one
                        # total throws away the only diagnostic the aggregate carries.
                        self._throttles[response.status] += 1
                        if response.status == ARCTICSHIFT_THROTTLE_STATUS:
                            # Too many open at once, which is exactly what width controls.
                            await self._limiter.on_throttle(epoch)
                            note = f"limit now {self._limiter.limit}"
                        elif response.status >= 500:
                            # A transient fault on one request, saying nothing about the
                            # limit or the window. Retried on its own backoff, with neither
                            # the width nor the rest of the fleet disturbed for it.
                            note = f"server fault, limit held at {self._limiter.limit}"
                        else:
                            # The window is spent. Width cannot buy anything back, so hold
                            # the whole fleet until the service says it has refilled and
                            # leave the settled limit where it was found. The gate in
                            # ``slot`` serves that wait, so this attempt adds none of its
                            # own on top of it.
                            self._limiter.pause(reset_wait(response.headers, wait))
                            wait = 0.0
                            note = f"paused, limit held at {self._limiter.limit}"
                        if attempt == self._max_retries:
                            response.raise_for_status()
                        self._log.debug(
                            f"Arctic Shift returned {response.status} for {path}; {note}; "
                            f"retry {attempt}/{self._max_retries - 1}."
                        )
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                if attempt == self._max_retries:
                    raise
                self._log.debug(
                    f"Arctic Shift request to {path} failed ({type(e).__name__}: {e}); sleeping "
                    f"{wait:.1f}s before retry {attempt}/{self._max_retries - 1}."
                )
            # Slept outside the limiter so a backing-off request does not hold a slot that
            # a healthy one could be using.
            await asyncio.sleep(wait)

        return []

    # -------------------------------------------------------------------------------------------- #
    def _build_submission(self, raw: Dict[str, Any]) -> Dict:
        """Map an Arctic Shift submission onto the schema the live engines emit.

        ``created_utc`` is carried alongside the published fields so the batch can be
        ordered newest-first, and is stripped again before the batch is written.
        """
        return {
            "submission_id": f"t3_{raw['id']}",
            "title": raw.get("title") or "",
            "author": raw.get("author") or "[deleted]",
            "selftext": raw.get("selftext") or "",
            "comments": [],
            "created_utc": raw.get("created_utc", 0),
        }

    # -------------------------------------------------------------------------------------------- #
    def _build_comment(self, raw: Dict[str, Any]) -> Optional[Tuple[str, Dict]]:
        """Map an Arctic Shift comment to its ``(link_id, record)`` pair, or None if unusable.

        Mirrors the live engines, which skip a comment with no author or no body. The
        archive represents those as removal markers rather than as missing values, so the
        same comments are excluded by a different test.
        """
        author = raw.get("author")
        body = raw.get("body")
        link_id = raw.get("link_id")
        if not link_id:
            return None
        if not author or author in REMOVED_MARKERS:
            return None
        if not body or body in REMOVED_MARKERS:
            return None
        return link_id, {
            "comment_id": f"t1_{raw['id']}",
            "author": author,
            "body": body,
        }

    # -------------------------------------------------------------------------------------------- #
    def _process_batch(self, current_batch_data: List) -> None:
        """Strip the sort key, then persist through the shared batch path."""
        for record in current_batch_data:
            record.pop("created_utc", None)
        super()._process_batch(current_batch_data=current_batch_data)

    # -------------------------------------------------------------------------------------------- #
    def _wrap_up(self) -> None:
        """Report orphaned comments and failed spans alongside the standard summary."""
        if self._n_orphan_comments:
            self._log.info(
                f"{self._n_orphan_comments} comments fell outside the spans scraped and "
                f"were not attached. Widen the requested window to capture them."
            )
        super()._wrap_up()

        if not self._n_spans_failed:
            return

        message = (
            f"{self._n_spans_failed} span(s) failed and were not written; "
            f"{self._n_batches} succeeded. Re-running fills only the spans with no file "
            f"on disk. Check the span warnings: 422s mean --concurrency is too high, "
            f"while 429s mean the request window was spent and only waiting helps."
        )
        self._log.error(message)
        # Also on stderr, for the same reason a missing subreddit is: a run that captured
        # nothing must be visible in quiet mode, and must not be mistaken for the
        # successful run whose summary looks just like it. The level and the subreddit are
        # spelled out only here, since stderr carries neither a level nor the log tag.
        print(f"WARNING: r/{self._subreddit}: {message}", file=sys.stderr)
