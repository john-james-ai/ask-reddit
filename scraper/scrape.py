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
# Modified   : Saturday June 21st 2025 11:01:18 pm                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
from typing import Dict, List

import logging
import time
from datetime import datetime, timedelta, timezone

import praw

from scraper.constants import ChunkSpan
from scraper.persist import FileManager

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #

class RedditScraper:
    """Scrapes submissions and comments from a specified subreddit for a defined period.

    This class is designed for a single, complete scraping job. It orchestrates
    the process of fetching data via the PRAW API, processing submissions and
    comments, and saving the results in chunks using a FileManager.

    Attributes:
        _scraper (praw.Reddit): An authenticated PRAW Reddit instance.
        _subreddit (str): The name of the subreddit to scrape.
        _days (int): The number of past days to extract data for.
        _chunk_span (ChunkSpan): The enum member for file grouping (DAY or MONTH).
        _filemanager (FileManager): An instance of FileManager to handle writing files.
        _tolerance (int): The number of consecutive errors to tolerate before stopping.
    """

    def __init__(self, scraper: praw.Reddit, subreddit: str, days: int, chunk_span: ChunkSpan, filemanager: FileManager, rate_limit_per_minute: int = 85, tolerance: int = 5) -> None:
        self._scraper = scraper
        self._subreddit = subreddit
        self._days = days
        self._chunk_span = chunk_span
        self._filemanager = filemanager
        self._tolerance = tolerance

        # --- State and Statistics ---
        self._n_submissions = 0
        self._n_comments = 0
        self._current_chunk_span_str = ""

        # --- Configuration ---
        self._delay = 60 / rate_limit_per_minute  # e.g., 60 req/min -> 1s delay

        # Set timestamp stop condition
        now_utc = datetime.now(timezone.utc)
        self._stop_utc = now_utc - timedelta(days=self._days)

    def scrape(self) -> None:
        """
        Runs the main scraping loop, processing submissions and saving them in chunks.
        """
        n_consecutive_errors = 0
        # This list will hold the data ONLY for the current chunk (e.g., one month).
        current_chunk_data = []

        logger.info(f"Starting scrape for r/{self._subreddit} for the last {self._days} days.")

        # This 'for' loop is the only control loop needed. PRAW handles the pagination
        # of submissions automatically. The loop is terminated by 'break' when the
        # stop condition is met.
        for submission in self._scraper.subreddit(self._subreddit).new(limit=None):
            try:
                submission_dt = datetime.fromtimestamp(submission.created_utc, timezone.utc)

                # --- Stop Condition Check ---
                # This check happens inside the loop, as you correctly pointed out.
                if submission_dt < self._stop_utc:
                    logger.info("Stop condition met: Found a submission older than the target date.")
                    break  # Exit the for loop cleanly.

                # --- Chunk Processing Logic ---
                # This logic ensures data is saved and cleared correctly for each chunk.
                submission_span_str = submission_dt.strftime(self._chunk_span.fmt)

                # If we've entered a new month/day, save the previous chunk's data
                # The check `self._current_chunk_span_str != ""` ensures we don't write an empty file on the first run.
                if submission_span_str != self._current_chunk_span_str and self._current_chunk_span_str != "":
                    logger.info(f"New chunk detected. Saving data for '{self._current_chunk_span_str}'.")
                    self._filemanager.write(data=current_chunk_data, span=self._current_chunk_span_str)
                    current_chunk_data.clear() # CRITICAL: Reset the list for the new chunk.

                self._current_chunk_span_str = submission_span_str

                # --- Process the submission ---
                submission_data = self._process_submission(submission)
                current_chunk_data.append(submission_data)

                # Reset consecutive error count on a successful operation
                n_consecutive_errors = 0

                time.sleep(self._delay)

            except Exception as e:
                logger.exception(f"Failed to process submission {submission.id}. Error: {e}")
                n_consecutive_errors += 1
                if n_consecutive_errors >= self._tolerance:
                    logger.critical(f"Error tolerance of {self._tolerance} exceeded. Aborting scrape.")
                    raise  # Re-raise the exception to stop the program

        # This call ensures the final, partially-filled chunk is saved.
        self._wrap_up(final_chunk_data=current_chunk_data)

    def _process_submission(self, submission: praw.models.Submission) -> Dict:
        """Processes a single submission and its comments, returning a data dictionary."""
        self._n_submissions += 1
        logger.info(f"Processing submission #{self._n_submissions}: '{submission.title}'")

        submission_data = {
            "submission_id": f"t3_{submission.id}",
            "title": submission.title,
            "author": submission.author.name if submission.author else "[deleted]",
            "created_utc": submission.created_utc,
            "score": submission.score,
            "upvote_ratio": submission.upvote_ratio,
            "num_comments": submission.num_comments,
            "permalink": submission.permalink,
            "selftext": submission.selftext,
            "comments": []
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
            comments_list.append({
                "comment_id": f"t1_{comment.id}",
                "author": comment.author.name,
                "created_utc": comment.created_utc,
                "score": comment.score,
                "body": comment.body,
                "parent_id": comment.parent_id,
                "depth": comment.depth
            })

    def _wrap_up(self, final_chunk_data: List) -> None:
        """Saves the final data chunk and prints a summary of the job."""

        # CRITICAL: Save the final chunk of data that was in memory when the loop ended.
        if final_chunk_data:
            logger.info(f"Saving final data chunk for '{self._current_chunk_span_str}'.")
            self._filemanager.write(data=final_chunk_data, span=self._current_chunk_span_str)

        save_dt = datetime.now()
        summary = (
            f"\n{'='*80}\n"
            f"Scraping for r/{self._subreddit} completed on {save_dt.strftime('%Y-%m-%d at %H:%M:%S')}\n"
            f"Total Submissions Processed: {self._n_submissions}\n"
            f"Total Comments Processed: {self._n_comments}\n"
            f"{'='*80}"
        )
        print(summary)
        logger.info("Scraping job finished successfully.")