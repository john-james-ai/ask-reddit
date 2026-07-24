#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/ascrape.py                                                              #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday July 24th 2026 12:00:00 pm                                                   #
# Modified   : Friday July 24th 2026 12:00:00 pm                                                   #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Asynchronous Scrape Module.

An async counterpart to :mod:`ask_reddit.scrape`. It uses Async PRAW, which internally
follows all of Reddit's API rate rules, so this path needs no manual rate limiting, no
sleeps, and no circuit breaker. Concurrency (fetching many submissions' comment trees at
once) is what raises throughput over the synchronous scraper; a semaphore bounds the number
of in-flight fetches for memory/politeness only.
"""
from typing import Dict, List

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import asyncpraw
from asyncpraw.models import Comment, Submission
from asyncprawcore.exceptions import TooManyRequests
from tqdm import tqdm

from ask_reddit.constants import (
    DEFAULT_CONCURRENCY,
    DEFAULT_ERROR_TOLERANCE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    BatchSpan,
)
from ask_reddit.date import DateTime
from ask_reddit.model import GenAIModel
from ask_reddit.persist import FileManager
from ask_reddit.print import Printer

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #


class ARedditScraper:
    """Asynchronously scrapes submissions and comments from a subreddit for a defined period.

    This is a drop-in, faster alternative to :class:`ask_reddit.scrape.RedditScraper`. It
    preserves the same batch-at-a-time output (newest-first ordering, span-boundary file
    grouping, identical JSON schema) but fetches each batch's comment trees concurrently.

    Async PRAW obeys Reddit's rate limits and retries transient errors internally, so no
    circuit breaker or ``sleep`` is used here.

    Attributes:
        _scraper (asyncpraw.Reddit): An authenticated Async PRAW Reddit instance.
        _subreddit (str): The name of the subreddit to scrape.
        _days (int): The number of past days to extract data for.
        _batch_span (BatchSpan): The enum member for file grouping (DAY or MONTH).
        _filemanager (FileManager): An instance of FileManager to handle writing files.
        _concurrency (int): The maximum number of submissions fetched concurrently.
        _tolerance (int): The number of consecutive errors to tolerate before stopping.
    """

    def __init__(
        self,
        scraper: asyncpraw.Reddit,
        model: GenAIModel,
        printer: Printer,
        subreddit: str,
        days: int,
        batch_span: BatchSpan,
        filemanager: FileManager,
        concurrency: int = DEFAULT_CONCURRENCY,
        tolerance: int = DEFAULT_ERROR_TOLERANCE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    ) -> None:
        self._scraper = scraper
        self._subreddit = subreddit
        self._model = model
        self._printer = printer
        self._days = days
        self._batch_span = batch_span
        self._filemanager = filemanager
        self._concurrency = concurrency
        self._tolerance = tolerance
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._sem = asyncio.Semaphore(concurrency)

        # --- State and Statistics ---
        self._n_batches = 0
        self._n_submissions = 0
        self._n_comments = 0
        self._n_tokens = 0
        self._consecutive_failures = 0
        self._current_batch_span_str = None
        self._start_dt = None

        # Set timestamp stop condition
        now_utc = datetime.now(timezone.utc)
        self._stop_utc = now_utc - timedelta(days=self._days)

    async def scrape(self) -> None:
        """Runs the main scraping loop, processing submissions and saving them in batches."""
        self._startup()
        # Holds the raw submission objects for the current batch (e.g. one month). Comment
        # trees are fetched concurrently once a batch is complete.
        current_batch: List[Submission] = []
        submission_span_str = None
        aborted = False

        pbar = tqdm(total=None, desc="\t\tProcessing...")

        subreddit = await self._scraper.subreddit(self._subreddit)
        async for submission in subreddit.new(limit=None):
            submission_dt = datetime.fromtimestamp(submission.created_utc, timezone.utc)

            # Stop Condition Check
            if submission_dt < self._stop_utc:
                logger.info("Stop condition met: Found a submission older than the target date.")
                break

            # Determine the batch span string for this submission.
            if self._batch_span:
                submission_span_str = submission_dt.strftime(self._batch_span.fmt)

            # If we've entered a new month/day, flush the previous, now-complete batch.
            if (
                submission_span_str != self._current_batch_span_str
                and self._current_batch_span_str is not None
            ):
                aborted = await self._flush_batch(current_batch, pbar)
                current_batch = []
                if aborted:
                    break

            self._current_batch_span_str = submission_span_str
            current_batch.append(submission)

        pbar.close()

        # Persist the final, partially-filled batch (unless we aborted mid-run).
        if not aborted:
            await self._flush_batch(current_batch, pbar=None)

        self._wrap_up()

    def _startup(self) -> None:
        """Initializes the scraping process."""
        print(f"\n{'='*80}")
        self._start_dt = datetime.now()
        logger.info(f"Starting async scrape for r/{self._subreddit} for the last {self._days} days.")
        title = f"Reddit Scraper (async) Started on {self._start_dt.strftime('%Y-%m-%d at %H:%M:%S')}"
        summary = {
            "Subreddit": f"r/{self._subreddit}",
            "Time Period": f"Last {self._days} days",
            "Concurrency": self._concurrency,
            "File Batch": "Month" if self._batch_span == BatchSpan.MONTH else "Day",
        }
        self._printer.print_dict(title=title, data=summary)
        print(f"{'-'*80}")

    async def _flush_batch(self, batch: List[Submission], pbar) -> bool:
        """Concurrently fetches comments for a batch, then counts tokens and writes to file.

        Returns:
            bool: True if the consecutive-failure tolerance was exceeded and the run should
                abort, otherwise False.
        """
        if not batch:
            return False

        # Fan out: fetch every submission's comment tree at once, bounded by the semaphore.
        results = await asyncio.gather(
            *(self._process_submission(submission) for submission in batch),
            return_exceptions=True,
        )

        batch_data: List[Dict] = []
        for result in results:
            if isinstance(result, Exception):
                self._consecutive_failures += 1
                logger.error(
                    f"Failed to process a submission (consecutive failures: "
                    f"{self._consecutive_failures}): {result}"
                )
                if self._consecutive_failures > self._tolerance:
                    logger.critical(
                        f"Exceeded failure tolerance of {self._tolerance}. Aborting scrape."
                    )
                    # Salvage the successes already gathered this batch (each was counted
                    # on the progress bar as it was appended above).
                    self._process_batch(batch_data)
                    return True
            else:
                self._consecutive_failures = 0
                batch_data.append(result)
                if pbar is not None:
                    pbar.update(1)

        self._process_batch(batch_data)
        return False

    def _process_batch(self, batch_data: List[Dict]) -> None:
        """Logs a new batch, counts its tokens, and saves it to file."""
        if not batch_data:
            return
        logger.info(f"Saving data for batch '{self._current_batch_span_str}'.")
        self._n_batches += 1
        self._n_tokens += self._model.count_tokens(data=batch_data)
        self._filemanager.write(data=batch_data, span=self._current_batch_span_str)

    async def _process_submission(self, submission: Submission) -> Dict:
        """Processes a single submission and its comments, returning a data dictionary."""
        async with self._sem:
            self._n_submissions += 1

            submission_data = {
                "submission_id": f"t3_{submission.id}",
                "title": submission.title,
                "author": submission.author.name if submission.author else "[deleted]",
                "selftext": submission.selftext,
                "comments": [],
            }

            await self._process_comments(submission, submission_data["comments"])
            return submission_data

    async def _process_comments(self, submission: Submission, comments_list: List) -> None:
        """Fetches all comments for a submission and appends them to a provided list."""
        # Submissions from a listing are not fully fetched: load the submission so its
        # comment forest is populated before it can be expanded. `load()` rebuilds the
        # forest, so it must be retried on its own — never re-called after `replace_more`
        # has begun (that would discard partial expansion).
        await self._with_retry(submission.load, what=f"load t3_{submission.id}")
        # Expand the full comment tree (replace every "load more comments" node). Async
        # PRAW's rate limiter is not concurrency-safe, so parallel calls can trip a 429;
        # re-calling `replace_more` safely resumes from the unexpanded nodes in the tree.
        await self._with_retry(
            lambda: submission.comments.replace_more(limit=None),
            what=f"replace_more t3_{submission.id}",
        )

        for comment in submission.comments.list():
            # Only process actual Comment objects (skip any residual MoreComments).
            if not isinstance(comment, Comment):
                continue

            if not comment.author or not comment.body:
                continue

            self._n_comments += 1
            comments_list.append(
                {
                    "comment_id": f"t1_{comment.id}",
                    "author": comment.author.name,
                    "body": comment.body,
                }
            )

    async def _with_retry(self, func, what: str):
        """Awaits ``func()`` and retries on 429 (``TooManyRequests``).

        Async PRAW obeys Reddit's rate limits for sequential requests, but its rate
        limiter is not concurrency-safe, so concurrent expansion can occasionally trip a
        429. This is reactive backoff only: it sleeps solely when Reddit returns a 429,
        honoring the ``retry-after`` header when present.

        Args:
            func: A zero-argument callable returning a fresh awaitable on each call.
            what: A short description of the operation, for logging.

        Returns:
            The awaited result of ``func()``.

        Raises:
            TooManyRequests: If the operation still fails after ``max_retries`` attempts.
        """
        for attempt in range(1, self._max_retries + 1):
            try:
                return await func()
            except TooManyRequests as e:
                if attempt == self._max_retries:
                    raise
                wait = float(e.retry_after) if e.retry_after else self._retry_backoff * attempt
                logger.warning(
                    f"Rate limited (429) during {what}; sleeping {wait:.1f}s before "
                    f"retry {attempt}/{self._max_retries - 1}."
                )
                await asyncio.sleep(wait)

    def _wrap_up(self) -> None:
        """Prints a summary of the completed job."""
        end_dt = datetime.now()
        if isinstance(self._start_dt, datetime):
            duration = end_dt - self._start_dt
            duration_sec = DateTime.get_seconds(td=duration)
            duration_str = DateTime.format_timedelta(td=duration)
        else:
            raise RuntimeError("Start time not set.")

        # Guard against division-by-zero for very fast runs.
        duration_sec = duration_sec or 1e-9

        submissions_per_min = round(self._n_submissions / duration_sec * 60, 2)
        comments_per_min = round(self._n_comments / duration_sec * 60, 2)
        tokens_per_min = round(self._n_tokens / duration_sec * 60, 2)

        summary = {
            "Days Captured": self._days,
            "Duration": duration_str,
            "Total Batches": self._n_batches,
            "Total Submissions": self._n_submissions,
            "Total Comments": self._n_comments,
            "Total Tokens": self._n_tokens,
            "Submissions per Minute": submissions_per_min,
            "Comments per Minute": comments_per_min,
            "Tokens per Minute": tokens_per_min,
        }

        print(f"{'-'*80}")
        title = f"Reddit Scraper (async) Completed on {end_dt.strftime('%Y-%m-%d at %H:%M:%S')}"
        self._printer.print_dict(data=summary, title=title)
        print(f"{'='*80}\n")

        logger.info("Async scraping job finished successfully.")
