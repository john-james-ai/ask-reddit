#!/usr/bin/env python3
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : scrape_sync.py                                                                      #
# Filename   : scrape_sync.py                                                                      #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Modified   : Wednesday July 29th 2026 12:15:57 am                                                #
# Modified   : Wednesday July 29th 2026 12:15:57 am                                                #
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
# Filename   : /ask_reddit/scrape.py                                                               #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 22nd 2025 02:40:33 pm                                                 #
# Modified   : Monday December 29th 2025 12:18:43 pm                                               #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Scrape Module"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

import praw
from praw.models import Comment, Submission
from tqdm.auto import tqdm

from ask.constants import DEFAULT_ERROR_TOLERANCE, MONTH_SPAN_FORMAT
from ask.model import GenAIModel
from ask.persist import FileManager
from ask.print import Printer
from ask.scrape import BaseRedditScraper

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #


class RedditScraper(BaseRedditScraper[praw.Reddit]):
    """Scrape submissions and comments from a subreddit using synchronous PRAW.

    This class performs a single, full scraping job using the blocking PRAW
    client. It iterates over new submissions from a subreddit, processes each
    submission and its comments, groups results into time-based batches, and
    persists batches via :class:`ask_reddit.persist.FileManager`.

    Args:
        scraper (praw.Reddit): Authenticated PRAW Reddit client.
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

    Examples:
        >>> scraper = RedditScraper(scraper=reddit, model=model, printer=printer,
        ...                        subreddit='learnpython', months=1,
        ...                        filemanager=file_manager)
        >>> scraper.scrape()
    """

    def __init__(
        self,
        scraper: praw.Reddit,
        model: GenAIModel,
        printer: Printer,
        subreddit: str,
        months: int,        
        filemanager: FileManager,
        tolerance: int = DEFAULT_ERROR_TOLERANCE,
        force: bool = False,
        verbose: bool = False,
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

    @property
    def description(self) -> Dict:
        """Return a short summary of the scraping job."""
        return {
            "Subreddit": f"r/{self._subreddit}",
            "Time Period": f"Last {self._months} months",
        }

    def scrape(self) -> None:
        """Run the main scraping loop, processing submissions and persisting batches.

        The method iterates over subreddit submissions (newest first), groups
        submissions into monthly batches, processes each submission and its
        comments, and writes completed batches to disk. Progress is displayed
        with a tqdm progress bar. A failed submission is logged and skipped; the run
        aborts once ``tolerance`` consecutive failures accumulate. Request pacing is
        left entirely to PRAW's own rate limiter.
        """
        self._startup()
        # This list will hold the data ONLY for the current batch (e.g., one month).
        current_batch_data = []
        # This will hold the current submission batch span
        submission_span_str = None

        # This 'for' loop is the only control loop needed. PRAW handles the pagination
        # of submissions automatically. The loop is terminated by 'break' when the
        # stop condition is met.
        pbar = tqdm(total=None, desc="\t\tProcessing...")

        for submission in self._scraper.subreddit(self._subreddit).new(limit=None):
            try:
                submission_dt = datetime.fromtimestamp(submission.created_utc, timezone.utc)

                # Stop Condition Check
                if submission_dt < self._stop_utc:
                    logger.info(
                        "Stop condition met: Found a submission older than the target date."
                    )
                    break  # Exit the for loop cleanly.

                # Batch Processing Logic
                # This logic ensures data is saved and cleared correctly for each batch.
                submission_span_str = submission_dt.strftime(MONTH_SPAN_FORMAT)

                # Skip spans already complete on disk without fetching comment trees.
                # This must precede the batch boundary check below: leaving
                # `_current_batch_span_str` untouched for skipped spans is what keeps a
                # skipped month from triggering a flush on every one of its submissions.
                if submission_span_str not in self._needed_spans:
                    continue

                # If we've entered a new month/day, save the previous batch's data
                # The check `self._current_batch_span_str != ""` ensures we don't write an empty file on the first run.
                if (
                    submission_span_str != self._current_batch_span_str
                    and self._current_batch_span_str is not None
                ):
                    self._process_batch(current_batch_data=current_batch_data)
                    current_batch_data.clear()  # Reset the list for the new batch.

                self._current_batch_span_str = submission_span_str

                # Process the submission
                submission_data = self._process_submission(submission)
                current_batch_data.append(submission_data)

                # Update the progress bar
                pbar.update(1)

                # Reset only once the submission has actually succeeded.
                self._consecutive_failures = 0

            except Exception as e:
                self._consecutive_failures += 1
                logger.error(
                    f"Failed to process a submission (consecutive failures: "
                    f"{self._consecutive_failures}): {e}"
                )
                if self._consecutive_failures > self._tolerance:
                    logger.critical(
                        f"Exceeded failure tolerance of {self._tolerance}. Aborting scrape."
                    )
                    break

        # Close the progress bar
        pbar.close()

        # Persist the final, partially-filled batch through the same path as every
        # other batch. The guard keeps an empty tail from writing a phantom file.
        if current_batch_data:
            self._process_batch(current_batch_data=current_batch_data)

        self._wrap_up()

    # -------------------------------------------------------------------------------------------- #
    def _process_submission(self, submission: Submission) -> Any:
        """Processes a single submission and its comments, returning a data dictionary."""
        self._n_submissions += 1

        submission_data = {
            "submission_id": f"t3_{submission.id}",
            "title": submission.title,
            "author": submission.author.name if submission.author else "[deleted]",
            "selftext": submission.selftext,
            "comments": [],
        }

        # This populates the "comments" list within the dictionary
        self._process_comments(submission, submission_data["comments"])
        return submission_data

    # -------------------------------------------------------------------------------------------- #
    def _process_comments(self, submission: Submission, comments_list: List) -> None:
        """Fetches all comments for a submission and appends them to a provided list."""
        # Replace every "load more comments" node with the actual comments.
        submission.comments.replace_more(limit=None)

        for comment in submission.comments.list():
            # Skip any residual MoreComments objects.
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
