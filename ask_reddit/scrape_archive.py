#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/scrape_archive.py                                                       #
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
"""Archive Scrape Module.

A third engine alongside :mod:`ask_reddit.scrape_sync` and :mod:`ask_reddit.scrape_async`,
reading from the Arctic Shift archive rather than from Reddit itself. It exists because the
other two cannot reach the data: every Reddit listing endpoint is capped at roughly 1000
items, so ``subreddit.new(limit=None)`` returns about a week of a busy subreddit no matter
how many months are requested. The archive is queried by time range and has no such cap.

The shape of the work is inverted relative to the live engines. Those walk one listing
newest-first and discover each batch boundary as they go; here the span boundaries are known
up front, so each needed month is fetched directly and no walk is required.

Two properties of the archive drive the rest of the design:

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
import sys
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, MutableMapping, Optional, Tuple

import aiohttp
from tqdm import tqdm

from ask_reddit.constants import (
    ARCHIVE_BASE_URL,
    ARCHIVE_MAX_BACKOFF,
    ARCHIVE_PAGE_LIMIT,
    ARCHIVE_THROTTLE_STATUS,
    ARCHIVE_WINDOW_HOURS,
    DEFAULT_ARCHIVE_CONCURRENCY,
    DEFAULT_COMMENT_GRACE_DAYS,
    DEFAULT_ERROR_TOLERANCE,
    DEFAULT_MAX_RETRIES,
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

# Authors and bodies the archive records as removed. The live engines skip these implicitly,
# since PRAW reports a deleted author as None; here they arrive as literal strings.
REMOVED_MARKERS = frozenset({"[deleted]", "[removed]"})


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


class ArchiveRedditScraper(BaseRedditScraper[aiohttp.ClientSession]):
    """Scrape submissions and comments for a subreddit from the Arctic Shift archive.

    Output is identical in schema and batching to the live engines, so files written here
    are interchangeable with theirs. What differs is reach: the live engines are bounded by
    Reddit's listing cap and request quota, while this one is bounded only by what the
    archive holds.

    The archive trails the live site by roughly an hour, so the current month is still
    better served by the async engine. Everything behind it is only reachable here.

    Args:
        scraper (aiohttp.ClientSession): Open HTTP session used for archive requests. The
            caller owns the session and is responsible for closing it.
        model (GenAIModel): Generative AI helper used for token accounting.
        printer (Printer): Printer instance for formatted summaries.
        subreddit (str): Subreddit name to scrape (e.g., 'ChatGPT').
        months (int): Number of past months to include in the scrape.
        filemanager (FileManager): FileManager used to persist batches.
        tolerance (int): Consecutive span failures tolerated before the run aborts.
        force (bool): When True, scrape the full requested window instead of resuming
            from what is already on file.
        verbose (bool): When True, progress and summary output is written to the console.
        concurrency (int): Maximum concurrent archive requests.
        max_retries (int): Number of attempts for a retriable request.
        retry_backoff (float): Base backoff seconds used when throttled.
        comment_grace_days (int): Days past the end of a span to keep collecting comments,
            so late replies still reach their submission.
        window_hours (int): Size of the time slices a span is cut into. Pagination is
            serial within a slice, so this is what bounds how much of ``concurrency``
            can actually be used.

    Examples:
        >>> async with aiohttp.ClientSession() as session:
        ...     scraper = ArchiveRedditScraper(scraper=session, model=model, printer=printer,
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
        tolerance: int = DEFAULT_ERROR_TOLERANCE,
        force: bool = False,
        verbose: bool = False,
        *,
        concurrency: int = DEFAULT_ARCHIVE_CONCURRENCY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
        comment_grace_days: int = DEFAULT_COMMENT_GRACE_DAYS,
        window_hours: int = ARCHIVE_WINDOW_HOURS,
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
        self._sem = asyncio.Semaphore(concurrency)
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
        self._n_throttled = 0
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
            "Source": "Arctic Shift archive",
            "Concurrency": self._concurrency,
            "Window": f"{self._window_hours}h",
        }

    async def scrape(self) -> None:
        """Fetch every needed span from the archive and persist each as a batch."""
        self._startup()
        pbar = tqdm(total=None, desc="\t\tProcessing...", disable=not self._verbose)

        # Newest span first, matching the order the live engines walk their listing, so a
        # run interrupted partway leaves behind the same spans either engine would have.
        for n in range(1, self._months + 1):
            span = DateTime.get_month_st(n)
            if span not in self._needed_spans:
                self._log.info(f"Skipping span '{span}': already complete on file.")
                continue

            throttled_before = self._n_throttled

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
                throttled = self._n_throttled - throttled_before
                if throttled:
                    self._log.warning(
                        f"Span '{span}': {throttled} request(s) throttled and retried. "
                        f"Lower --concurrency if this is frequent."
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
            # the batch is correct regardless of whether the archive treats `before` as
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
            pbar.update(len(batch))

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
        """Return every mapped record the archive holds in ``[start, end)``.

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
                    "limit": str(ARCHIVE_PAGE_LIMIT),
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
            if len(page) < ARCHIVE_PAGE_LIMIT:
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
                    f"More than {ARCHIVE_PAGE_LIMIT} records share created_utc={last_ts} "
                    f"in r/{self._subreddit}; stepping past it, so some are not captured."
                )
                after = last_ts

    # -------------------------------------------------------------------------------------------- #
    async def _request(self, path: str, params: Dict[str, str]) -> List[Dict]:
        """Perform one archive request, retrying only what is worth retrying.

        A 5xx is a transient server fault and a 429 is ordinary throttling. The archive
        also answers with 422 and ``"Timeout. Maybe slow down a bit"`` when too many
        requests are open at once, so that status means back off here rather than carrying
        its usual sense of a malformed request. Every other 4xx really is malformed and
        would fail identically however often it were repeated, so it is raised at once
        rather than burning the retry budget.
        """
        url = f"{ARCHIVE_BASE_URL}/{path}"
        retriable = {ARCHIVE_THROTTLE_STATUS, 429}
        for attempt in range(1, self._max_retries + 1):
            # Exponential rather than linear: under a sustained 429 every in-flight
            # request retries together, and a linear ramp has them all arrive again while
            # the limit is still tripped, burning the whole budget in seconds.
            wait = min(self._retry_backoff * 2 ** (attempt - 1), ARCHIVE_MAX_BACKOFF)
            try:
                async with self._sem:
                    async with self._scraper.get(url, params=params) as response:
                        if response.status not in retriable and response.status < 500:
                            response.raise_for_status()
                            payload = await response.json()
                            return payload.get("data", [])
                        if attempt == self._max_retries:
                            response.raise_for_status()
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            wait = float(retry_after)
                        self._n_throttled += 1
                        self._log.debug(
                            f"Archive returned {response.status} for {path}; sleeping "
                            f"{wait:.1f}s before retry {attempt}/{self._max_retries - 1}."
                        )
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                if attempt == self._max_retries:
                    raise
                self._log.debug(
                    f"Archive request to {path} failed ({type(e).__name__}: {e}); sleeping "
                    f"{wait:.1f}s before retry {attempt}/{self._max_retries - 1}."
                )
            # Slept outside the semaphore so a backing-off request does not hold a slot
            # that a healthy one could be using.
            await asyncio.sleep(wait)

        return []

    # -------------------------------------------------------------------------------------------- #
    def _build_submission(self, raw: Dict[str, Any]) -> Dict:
        """Map an archive submission onto the schema the live engines emit.

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
        """Map an archive comment to its ``(link_id, record)`` pair, or None if unusable.

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
            f"on disk. Lower --concurrency if this was throttling."
        )
        self._log.error(message)
        # Also on stderr, for the same reason a missing subreddit is: a run that captured
        # nothing must be visible in quiet mode, and must not be mistaken for the
        # successful run whose summary looks just like it. The level and the subreddit are
        # spelled out only here, since stderr carries neither a level nor the log tag.
        print(f"WARNING: r/{self._subreddit}: {message}", file=sys.stderr)
