#!/usr/bin/env python3
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : scrape-async.py                                                                     #
# Filename   : scrape-async.py                                                                     #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Modified   : Saturday July 25th 2026 11:57:32 am                                                 #
# Modified   : Saturday July 25th 2026 11:57:32 am                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2026 John James                                                                 #
# ================================================================================================ #
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

An async counterpart to :mod:`ask_reddit.scrape_sync`. Both engines leave request pacing
entirely to the PRAW rate limiter, which follows Reddit's API rules from the response
headers; neither sleeps on its own schedule. Concurrency (fetching many submissions'
comment trees at once) is what raises throughput over the synchronous scraper; a semaphore
bounds the number of in-flight fetches for memory and politeness.

The one place this module does sleep is :meth:`ARedditScraper._with_retry`, which backs off
only in reaction to a 429. Async PRAW's limiter is not concurrency-safe, so parallel
expansion can outrun it; the synchronous engine issues requests sequentially and needs no
such handling.
"""
import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Dict, List

import asyncpraw
from asyncpraw.models import Comment, Submission
from asyncprawcore.exceptions import Forbidden, NotFound, Redirect, TooManyRequests
from tqdm import tqdm

from ask_reddit.constants import (
    DEFAULT_CONCURRENCY,
    DEFAULT_ERROR_TOLERANCE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    MONTH_SPAN_FORMAT,
)
from ask_reddit.model import GenAIModel
from ask_reddit.persist import FileManager
from ask_reddit.print import Printer
from ask_reddit.scrape import BaseRedditScraper

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #


class ARedditScraper(BaseRedditScraper[asyncpraw.Reddit]):
    """Asynchronously scrape submissions and comments from a subreddit.

    This is a faster, async counterpart to :class:`ask_reddit.scrape.RedditScraper`.
    It maintains the same output schema and batch grouping but fetches comment
    trees concurrently to increase throughput. Async PRAW enforces Reddit's rate
    limits; this implementation bounds concurrency with a semaphore to limit
    resource usage.

    Args:
        scraper (asyncpraw.Reddit): Authenticated async PRAW Reddit client.
        model (GenAIModel): Generative AI helper used for token accounting.
        printer (Printer): Printer instance for formatted summaries.
        subreddit (str): Subreddit name to scrape (e.g., 'learnpython').
        months (int): Number of past months to include in the scrape.
        filemanager (FileManager): FileManager used to persist batches.
        tolerance (int): Consecutive failures tolerated before the run aborts.
        verbose (bool): When True, progress and summary output is written to the
            console. Errors go to stderr regardless. Logging is unaffected.
        force (bool): When True, scrape the full requested window instead of
            resuming from what is already on file. Existing files are never
            overwritten either way; a rescrape is written alongside them.
        concurrency (int): Maximum concurrent submission processors.
        max_retries (int): Number of retries for retriable operations.
        retry_backoff (float): Base backoff seconds used when rate limited.

    Examples:
        >>> scraper = ARedditScraper(scraper=reddit, model=model, printer=printer,
        ...                         subreddit='learnpython', months=1,
        ...                         filemanager=file_manager)
        >>> asyncio.run(scraper.scrape())
    """

    def __init__(
        self,
        scraper: asyncpraw.Reddit,
        model: GenAIModel,
        printer: Printer,
        subreddit: str,
        months: int,
        filemanager: FileManager,
        tolerance: int = DEFAULT_ERROR_TOLERANCE,
        force: bool = False,
        verbose: bool = False,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
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
        self._sem = asyncio.Semaphore(concurrency)
    
    @property
    def description(self) -> Dict:
        """Return a brief description of the scraping job."""
        return {
            "Subreddit": f"r/{self._subreddit}",
            "Time Period": f"Last {self._months} months",
            "Concurrency": self._concurrency,            
        }

    async def scrape(self) -> None:
        """Run the main scraping loop, processing submissions and saving batches."""
        self._startup()
        # Holds the raw submission objects for the current batch (e.g. one month). Comment
        # trees are fetched concurrently once a batch is complete.
        current_batch: List[Submission] = []
        submission_span_str = None
        aborted = False

        pbar = tqdm(total=None, desc="\t\tProcessing...", disable=not self._verbose)

        # A subreddit that is missing, private, quarantined, or misspelled fails here
        # rather than at construction, since the listing is what first contacts the API.
        # These are expected operating conditions, not defects, so they are reported as a
        # single log line instead of an unhandled traceback.
        try:
            subreddit = await self._scraper.subreddit(self._subreddit)
            async for submission in subreddit.new(limit=None):
                submission_dt = datetime.fromtimestamp(submission.created_utc, timezone.utc)

                # Stop Condition Check
                if submission_dt < self._stop_utc:
                    logger.info(
                        "Stop condition met: Found a submission older than the target date."
                    )
                    break

                # Determine the batch span string for this submission.
                submission_span_str = submission_dt.strftime(MONTH_SPAN_FORMAT)

                # Skip spans already complete on disk without fetching comment trees.
                # This must precede the batch boundary check below: leaving
                # `_current_batch_span_str` untouched for skipped spans is what keeps a
                # skipped month from triggering a flush on every one of its submissions.
                if submission_span_str not in self._needed_spans:
                    continue

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

        except (NotFound, Forbidden, Redirect) as e:
            # Not marked as aborted: whatever was collected before the failure is still
            # valid and is persisted by the final flush below.
            message = (
                f"Stopped scraping r/{self._subreddit}: {type(e).__name__}. "
                f"The subreddit may not exist, be private, or be misspelled."
            )
            logger.error(message)
            # Written to stderr rather than through the printer: a failed subreddit must
            # be visible even in quiet mode, and stderr keeps stdout clean for piping.
            print(message, file=sys.stderr)

        pbar.close()

        # Persist the final, partially-filled batch (unless we aborted mid-run).
        if not aborted:
            await self._flush_batch(current_batch, pbar=None)

        self._wrap_up()


    async def _flush_batch(self, batch: List[Submission], pbar) -> bool:
        """Fetch comments for a batch concurrently and persist the batch."""
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


    async def _process_submission(self, submission: Submission) -> Dict:
        """Process a single submission and its comments and return a data dict."""
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
        """Fetch all comments for a submission and append them to ``comments_list``."""
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
        """Await ``func()`` with retry/backoff when rate limited (429)."""
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
