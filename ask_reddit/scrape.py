#!/usr/bin/env python3
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Description: Reddit Scraper.                                                                     #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filepath   : /ask_reddit                                                                         #
# Filename   : scrape.py                                                                           #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday July 25th 2026 09:04:04 am                                                 #
# Modified   : Saturday July 25th 2026 12:31:01 pm                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2026 John James                                                                 #
# ================================================================================================ #

"""Scrape Module"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Generic, List, TypeVar

import asyncpraw
import praw

from ask_reddit.constants import DEFAULT_ERROR_TOLERANCE
from ask_reddit.date import DateTime
from ask_reddit.model import GenAIModel
from ask_reddit.persist import FileManager
from ask_reddit.print import Printer

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #


# Constrained rather than bound: exactly two clients are permitted, and a bound would
# admit any common supertype of the two.
TReddit = TypeVar("TReddit", praw.Reddit, asyncpraw.Reddit)


class BaseRedditScraper(ABC, Generic[TReddit]):
    """Behavior shared by the synchronous and asynchronous scrapers.

    Holds the pieces that are independent of which Reddit client is in use: job
    configuration, the resume calculation that sets the stop boundary, run statistics,
    and batch persistence. Anything that touches library-specific submission or comment
    objects belongs in the subclass, since ``praw`` and ``asyncpraw`` expose unrelated
    types for them.

    Args:
        scraper (TReddit): An authenticated Reddit client, sync or async.
        model (GenAIModel): Model helper used to count tokens per batch.
        printer (Printer): Formatter for the startup and summary output.
        subreddit (str): Name of the subreddit to scrape.
        months (int): Number of past months requested, counting the current month.
        filemanager (FileManager): Persistence helper for the batch files.
        tolerance (int): Consecutive failures tolerated before a run aborts.
        force (bool): When True, scrape the full requested window instead of
            resuming from what is already on file. Existing files are never
            overwritten either way; a rescrape is written alongside them.
    """

    def __init__(
        self,
        scraper: TReddit,
        model: GenAIModel,
        printer: Printer,
        subreddit: str,
        months: int,
        filemanager: FileManager,
        tolerance: int = DEFAULT_ERROR_TOLERANCE,
        force: bool = False,
    ) -> None:
        self._scraper: TReddit = scraper
        self._model = model
        self._printer = printer
        self._subreddit = subreddit
        self._months = months
        self._filemanager = filemanager
        self._tolerance = tolerance
        self._force = force

        # --- State and Statistics ---
        self._n_batches = 0
        self._n_submissions = 0
        self._n_comments = 0
        self._n_tokens = 0
        self._consecutive_failures = 0
        self._current_batch_span_str = None
        self._start_dt = None      
                
        # Set timestamp stop condition
        effective_months = min(self._filemanager.get_months_since_last() or self._months, self._months) if not self._force else self._months
        self._stop_utc = DateTime.get_month_dt(n=effective_months)

    # -------------------------------------------------------------------------------------------- #
    @property
    @abstractmethod
    def description(self) -> Dict:
        """Returns a summary of the scraping job."""
        pass

    # -------------------------------------------------------------------------------------------- #
    @abstractmethod
    def scrape(self) -> None | Any:
        """Scrapes the specified subreddit for the given time period."""
        pass

    # -------------------------------------------------------------------------------------------- #
    def _startup(self) -> None:
        """Initializes the scraping process."""
        print(f"\n{'='*80}")
        self._start_dt = datetime.now()
        logger.info(f"Starting {self.__class__.__name__} for r/{self._subreddit} for the last {self._months} months.")
        # Print summary information
        title = f"{self.__class__.__name__} Started on {self._start_dt.strftime('%Y-%m-%d at %H:%M:%S')}"        

        self._printer.print_dict(title=title, data=self.description)
        print(f"{'-'*80}")

    # -------------------------------------------------------------------------------------------- #
    def _process_batch(self, current_batch_data: List) -> None:
        """Logs new batch, counts tokens in batch and saves to file."""

        logger.info(f"Saving batch for '{self._current_batch_span_str}'.")
        self._n_batches += 1
        # Count number of tokens
        self._n_tokens += self._model.count_tokens(data=current_batch_data)
        # Persist the batch to file.
        self._filemanager.write(data=current_batch_data, span=self._current_batch_span_str)

    # -------------------------------------------------------------------------------------------- #
    def _wrap_up(self) -> None:
        """Computes run statistics and prints the job summary.

        Persisting the final batch is the caller's responsibility: both scrapers flush
        it through :meth:`_process_batch` before calling this, so there is no batch
        argument to pass and no way to forget one.

        Raises:
            RuntimeError: If called before :meth:`_startup` recorded a start time.
        """
        end_dt = datetime.now()
        if not isinstance(self._start_dt, datetime):
            raise RuntimeError("Start time not set.")

        duration = end_dt - self._start_dt
        duration_sec = DateTime.get_seconds(td=duration)
        duration_str = DateTime.format_timedelta(td=duration)

        # Guard against division-by-zero for very fast runs.
        duration_sec = duration_sec or 1e-9

        summary = {
            "Months Captured": self._months,
            "Duration": duration_str,
            "Total Batches": self._n_batches,
            "Total Submissions": self._n_submissions,
            "Total Comments": self._n_comments,
            "Total Tokens": self._n_tokens,
            "Submissions per Minute": round(self._n_submissions / duration_sec * 60, 2),
            "Comments per Minute": round(self._n_comments / duration_sec * 60, 2),
            "Tokens per Minute": round(self._n_tokens / duration_sec * 60, 2),
        }

        print(f"{'-'*80}")
        title = f"{self.__class__.__name__} Completed on {end_dt.strftime('%Y-%m-%d at %H:%M:%S')}"
        self._printer.print_dict(data=summary, title=title)
        print(f"{'='*80}\n")

        logger.info(f"{self.__class__.__name__} finished successfully.")
