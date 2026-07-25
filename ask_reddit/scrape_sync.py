#!/usr/bin/env python3
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : scrape-sync.py                                                                      #
# Filename   : scrape-sync.py                                                                      #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Modified   : Saturday July 25th 2026 12:02:33 pm                                                 #
# Modified   : Saturday July 25th 2026 12:02:33 pm                                                 #
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
from tqdm import tqdm

from ask_reddit.constants import DEFAULT_ERROR_TOLERANCE, MONTH_SPAN_FORMAT
from ask_reddit.model import GenAIModel
from ask_reddit.monitor import CircuitBreaker
from ask_reddit.persist import FileManager
from ask_reddit.print import Printer
from ask_reddit.scrape import BaseRedditScraper

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
        circuit_breaker (CircuitBreaker): Circuit breaker used to track failures.
        tolerance (int): Consecutive error tolerance before aborting.
        force (bool): When True, scrape the full requested window instead of
            resuming from what is already on file. Existing files are never
            overwritten either way; a rescrape is written alongside them.

    Examples:
        >>> scraper = RedditScraper(scraper=reddit, model=model, printer=printer,
        ...                        subreddit='learnpython', months=1,
        ...                        filemanager=file_manager, circuit_breaker=cb)
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
        circuit_breaker: CircuitBreaker,
        tolerance: int = DEFAULT_ERROR_TOLERANCE,    
        force: bool = False,   
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
        )
        self._circuit_breaker = circuit_breaker

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
        with a tqdm progress bar. Any exceptions increment the circuit breaker
        failure count and the loop continues until the stop condition is met.
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
                self._circuit_breaker.success()
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

            except Exception:
                error_context = {
                    "Batch": self._n_batches,
                    "Submissions": self._n_submissions,
                    "Comments": self._n_comments,
                }
                self._circuit_breaker.failure(context=error_context)

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
