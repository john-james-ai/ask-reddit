#!/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /scraper/scrape.py                                                                  #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.com                                                           #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday June 21st 2025 02:29:04 pm                                                 #
# Modified   : Sunday June 22nd 2025 07:23:15 am                                                   #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
from typing import Dict, List

import logging
from datetime import datetime, timedelta, timezone

import praw
from tqdm import tqdm

from scraper.constants import BatchSpan
from scraper.date import DateTime
from scraper.model import GenAIModel
from scraper.monitor import CircuitBreaker
from scraper.persist import FileManager
from scraper.print import Printer

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #


class RedditScraper:
    """Scrapes submissions and comments from a specified subreddit for a defined period.

    This class is designed for a single, complete scraping job. It orchestrates
    the process of fetching data via the PRAW API, processing submissions and
    comments, and saving the results in batchs using a FileManager.

    Attributes:
        _scraper (praw.Reddit): An authenticated PRAW Reddit instance.
        _subreddit (str): The name of the subreddit to scrape.
        _days (int): The number of past days to extract data for.
        _batch_span (BatchSpan): The enum member for file grouping (DAY or MONTH).
        _filemanager (FileManager): An instance of FileManager to handle writing files.
        _tolerance (int): The number of consecutive errors to tolerate before stopping.
    """

    def __init__(
        self,
        scraper: praw.Reddit,
        model: GenAIModel,
        printer: Printer,
        circuit_breaker: CircuitBreaker,
        subreddit: str,
        days: int,
        batch_span: BatchSpan,
        filemanager: FileManager,
        rate_limit_per_minute: int = 85,
        tolerance: int = 5,
    ) -> None:
        self._scraper = scraper
        self._subreddit = subreddit
        self._model = model
        self._printer = printer
        self._circuit_breaker = circuit_breaker
        self._days = days
        self._batch_span = batch_span
        self._filemanager = filemanager
        self._tolerance = tolerance

        # --- State and Statistics ---
        self._n_batches = 0
        self._n_submissions = 0
        self._n_comments = 0
        self._n_tokens = 0
        self._current_batch_span_str = ""
        self._start_dt = None

        # Set timestamp stop condition
        now_utc = datetime.now(timezone.utc)
        self._stop_utc = now_utc - timedelta(days=self._days)

    def scrape(self) -> None:
        """
        Runs the main scraping loop, processing submissions and saving them in batchs.
        """
        self._startup()
        # This list will hold the data ONLY for the current batch (e.g., one month).
        current_batch_data = []

        # This 'for' loop is the only control loop needed. PRAW handles the pagination
        # of submissions automatically. The loop is terminated by 'break' when the
        # stop condition is met.
        pbar = tqdm(total=None, desc=f"\t\tProcessing...")
        for submission in self._scraper.subreddit(self._subreddit).new(limit=None):
            try:
                self._circuit_breaker.success()
                submission_dt = datetime.fromtimestamp(submission.created_utc, timezone.utc)

                # Stop Condition Check
                # This check happens inside the loop, as you correctly pointed out.
                if submission_dt < self._stop_utc:
                    logger.info(
                        "Stop condition met: Found a submission older than the target date."
                    )
                    break  # Exit the for loop cleanly.

                # Batch Processing Logic
                # This logic ensures data is saved and cleared correctly for each batch.
                submission_span_str = submission_dt.strftime(self._batch_span.fmt)

                # If we've entered a new month/day, save the previous batch's data
                # The check `self._current_batch_span_str != ""` ensures we don't write an empty file on the first run.
                if (
                    submission_span_str != self._current_batch_span_str
                    and self._current_batch_span_str != ""
                ):
                    self._process_batch(current_batch_data=current_batch_data)
                    current_batch_data.clear()  # Reset the list for the new batch.

                self._current_batch_span_str = submission_span_str

                # Process the submission
                submission_data = self._process_submission(submission)
                current_batch_data.append(submission_data)

                # Update the progress bar
                pbar.update(1)

            except Exception as e:
                error_context = {
                    "Batch": self._n_batches,
                    "Submissions": self._n_submissions,
                    "Comments": self._n_comments,
                }
                self._circuit_breaker.failure(context=error_context)

        # Close the progress bar
        pbar.close()
        # This call ensures the final, partially-filled batch is saved.
        self._wrap_up(final_batch_data=current_batch_data)

    def _startup(self) -> None:
        """Initializes the scraping process."""
        print(f"\n{'='*80}")
        self._start_dt = datetime.now()
        logger.info(f"Starting scrape for r/{self._subreddit} for the last {self._days} days.")
        # Print summary information
        title = f"Reddit Scraper Started on {self._start_dt.strftime('%Y-%m-%d at %H:%M:%S')}"
        summary = {
            "Subreddit": f"r/{self._subreddit}",
            "Time Period": f"Last {self._days} days",
            "File Batch": "Month" if self._batch_span == BatchSpan.MONTH else "Day",
        }
        self._printer.print_dict(title=title, data=summary)
        print(f"{'-'*80}")

    def _process_batch(self, current_batch_data: List) -> None:
        """Logs new batch, counts tokens in batch and saves to file."""

        logger.info(f"New batch detected. Saving data for '{self._current_batch_span_str}'.")
        self._n_batches += 1
        # Count number of tokens
        self._n_tokens += self._model.count_tokens(data=current_batch_data)
        # Persist the batch to file.
        self._filemanager.write(data=current_batch_data, span=self._current_batch_span_str)

    def _process_submission(self, submission: praw.models.Submission) -> Dict:
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

    def _process_comments(self, submission: praw.models.Submission, comments_list: List) -> None:
        """Fetches all comments for a submission and appends them to a provided list."""
        submission.comments.replace_more(limit=None)

        for comment in submission.comments.list():
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

    def _wrap_up(self, final_batch_data: List) -> None:
        """Saves the final data batch and prints a summary of the job."""
        # Obtain duration as string and as seconds.
        end_dt = datetime.now()
        duration = end_dt - self._start_dt
        duration_sec = DateTime.get_seconds(td=duration)
        duration_str = DateTime.format_timedelta(td=duration)

        # Save the final batch and update the token count
        if final_batch_data:
            self._n_batches += 1
            self._filemanager.write(data=final_batch_data, span=self._current_batch_span_str)
            # Count number of tokens in final batch and add to token count
            self._n_tokens += self._model.count_tokens(data=final_batch_data)

        # Compute Statistics
        submissions_per_min = round(self._n_submissions / duration_sec * 60, 2)
        comments_per_min = round(self._n_comments / duration_sec * 60, 2)
        tokens_per_min = round(self._n_tokens / duration_sec * 60, 2)

        # Format Summary
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

        # Print Summary
        print(f"{'-'*80}")
        title = f"Reddit Scraper Completed on {end_dt.strftime('%Y-%m-%d at %H:%M:%S')}"
        self._printer.print_dict(data=summary, title=title)
        print(f"{'='*80}\n")

        logger.info("Scraping job finished successfully.")
