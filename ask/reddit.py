#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask/reddit.py                                                                      #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Tuesday July 28th 2026                                                              #
# Modified   : Wednesday July 29th 2026 12:15:57 am                                                #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2026 John James                                                                 #
# ================================================================================================ #
"""Programmatic entry point for a scrape, for callers that are not a command line.

:mod:`ask.__main__` wires a run by hand inside a Typer command: logging, the
:class:`FileManager`, the token-count model, the printer, the session, the engine. That
wiring is only reachable by launching a process, which is the wrong shape for a notebook.
A shelled-out run puts the scraper's progress bar in a child process, where it can only
write bytes to a pipe: no kernel, no comm channel, and therefore no widget.

The split of responsibilities follows the split in the arguments. Everything that describes
the machine -- where files land, how hard to push Arctic Shift, where the log goes -- is
constructor state and holds for a session. Everything that describes a job -- which
subreddit, how many months -- belongs to :meth:`run`, because those are what vary across a
corpus. One controller therefore serves a whole run of subreddits, and because it outlives
any single scrape it can keep the record of them: what was collected, when, and for how
long, which is otherwise only recoverable by parsing the log.

This is additive. The CLI keeps its own wiring and behaviour unchanged, so anything that
runs today still runs the same way; this is a second door into the same engine.
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
import pandas as pd
from dotenv import load_dotenv

from ask.constants import (
    ARCTICSHIFT_USER_AGENT,
    ARCTICSHIFT_WINDOW_HOURS,
    DEFAULT_ARCTICSHIFT_CONCURRENCY,
)
from ask.model import GenAIModel
from ask.persist import FileManager
from ask.print import Printer
from ask.scrape_arcticshift import ArcticShiftScraper

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #

# Read once at import, so every default is visible in the constructor signature rather than
# resolved somewhere inside the run. help(AskReddit) then shows the values a call will
# actually use, which is the point: a default that only appears as None tells the caller
# nothing about where the files land. The cost of binding here is that a change to .env
# needs a module reload to take effect, which for a notebook session is the right trade.
load_dotenv()

FILE_LOCATION = os.getenv("FILE_LOCATION", "data")
SOURCE = os.getenv("SOURCE", "reddit")
LOG_FILEPATH = os.getenv("LOG_FILEPATH", "logs/default_scraper.log")


class ScrapeFailed(RuntimeError):
    """Raised when a scrape completed but captured nothing.

    The CLI signals this with ``typer.Exit(code=1)``, which is meaningless to a caller that
    is not a shell. A loop over many subreddits needs to tell "captured nothing" from
    "captured something", and an exception is what that loop can catch and record.
    """


class AskReddit:
    """Run scrapes from inside the calling process, keeping a record of each one.

    A single instance is configured once and then run repeatedly, one call per subreddit.
    Nothing is built at construction, so a controller costs nothing to create and cannot
    fail; the collaborators are built per run and the run is recorded whether it succeeded
    or not.

    Args:
        directory (str): Where batches are written. Defaults to ``FILE_LOCATION`` from the
            environment, then ``'data'``.
        source (str): Corpus source recorded by the FileManager. Defaults to ``SOURCE``
            from the environment, then ``'reddit'``.
        force (bool): When True, scrape the full window rather than resuming from what is
            already on file.
        verbose (bool): When True, print the pre-run description and post-run summary
            tables. The progress bar is not gated on this: it is default behaviour, and the
            tables are the only thing ``verbose`` decides.
        concurrency (int): Ceiling on Arctic Shift requests in flight. The engine opens
            well below this and searches upward, so it is a cap rather than a setting.
        window_hours (int): Size of the slices a month is cut into. Affects speed only,
            not results.
        configure_logging (bool): When True, point logging at the rotating file the CLI
            uses. Set False when the caller has already configured logging and does not
            want its handlers replaced.
        log_filepath (str): Log file to configure. Defaults to ``LOG_FILEPATH`` from the
            environment, then the CLI's default path.
    """

    def __init__(
        self,
        directory: str = FILE_LOCATION,
        source: str = SOURCE,
        *,
        force: bool = False,
        verbose: bool = False,
        concurrency: int = DEFAULT_ARCTICSHIFT_CONCURRENCY,
        window_hours: int = ARCTICSHIFT_WINDOW_HOURS,
        configure_logging: bool = True,
        log_filepath: str = LOG_FILEPATH,
    ) -> None:
        self._directory = directory
        self._source = source
        self._force = force
        self._verbose = verbose
        self._concurrency = concurrency
        self._window_hours = window_hours
        self._log_filepath = log_filepath
        # Configured once here rather than per run: setup_logging clears the root logger's
        # handlers, so calling it before every subreddit would tear down and rebuild the
        # same file handler dozens of times in a corpus run.
        if configure_logging:
            # Imported here rather than at module scope: __main__ builds a Typer app on
            # import, and a notebook importing this module should not pay for that.
            from ask.__main__ import setup_logging

            setup_logging(log_filepath)

        # Built once and reused: neither carries state from one subreddit to the next, and
        # GenAIModel opens a client, which is not worth doing per run in a corpus.
        self._model = GenAIModel()
        self._printer = Printer(verbose=verbose)

        # One entry per run, in the order they ran. Private: the DataFrame from
        # `summary` is the way to read it, so there is one shape to know rather than two.
        self._records: List[Dict[str, Any]] = []
        # Per run rather than per controller, unlike the two above: a FileManager binds its
        # topic at construction and the topic is the subreddit, so one cannot serve two.
        self._filemanager: Optional[FileManager] = None
        self._scraper: Optional[ArcticShiftScraper] = None

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(directory='{self._directory}', "
            f"source='{self._source}', runs={len(self._records)})"
        )

    @property
    def scraper(self) -> Optional[ArcticShiftScraper]:
        """The engine from the last run, or None before the first one."""
        return self._scraper

    @property
    def filemanager(self) -> Optional[FileManager]:
        """The FileManager the last run wrote through, or None before the first one."""
        return self._filemanager

    @property
    def model(self) -> GenAIModel:
        """The token-count model every run of this controller uses."""
        return self._model

    @property
    def printer(self) -> Printer:
        """The printer every run of this controller uses."""
        return self._printer

    @property
    def summary(self) -> pd.DataFrame:
        """The runs so far as a DataFrame, one row per subreddit scraped.

        Columns: subreddit, months, start, end, duration, spans, spans_failed,
        submissions, comments, tokens. There is no overall pass/fail column: the counts
        already carry it, since a run that wrote no spans and failed several is visible
        without a flag summarising the same two numbers. Empty with those columns before
        the first run, so a caller can concatenate or filter without special-casing the
        empty case.

        Returns:
            pd.DataFrame: The history, oldest run first.
        """
        columns = [
            "subreddit",
            "months",
            "start",
            "end",
            "duration",
            "spans",
            "spans_failed",
            "submissions",
            "comments",
            "tokens",
        ]
        return pd.DataFrame(self._records, columns=columns)

    async def scrape(self, subreddit: str, months: int = 1) -> ArcticShiftScraper:
        """Scrape one subreddit and record the run.

        Args:
            subreddit (str): Subreddit to scrape, without the ``r/`` prefix.
            months (int): Number of months back to cover, counting the current month.

        Returns:
            ArcticShiftScraper: The engine that ran, for its counters.

        Raises:
            ScrapeFailed: The run captured nothing; every span failed. The run is recorded
                before this is raised, so a caller that catches it still sees the attempt
                in :meth:`summary`. A RuntimeError from the FileManager propagates too;
                it is documented on the method that raises it.
        """
        # The only collaborator that cannot be built once: it is scoped to one subreddit's
        # topic. The model and printer were built with the controller.
        self._filemanager = self._create_file_manager(subreddit)

        logger.info(
            f"Programmatic scrape started for r/{subreddit}, months={months}, "
            f"engine=arcticshift"
        )

        # Arctic Shift answers the default aiohttp agent with a 403, so the header is
        # required rather than merely polite.
        headers = {"User-Agent": ARCTICSHIFT_USER_AGENT}
        start = datetime.now()
        async with aiohttp.ClientSession(headers=headers) as session:
            scraper = self._build_scraper(session, subreddit, months)
            self._scraper = scraper
            try:
                await scraper.scrape()
            finally:
                # Recorded in `finally` so a run that raised partway still appears in the
                # history. A corpus run is judged on which subreddits are missing, and a
                # failure that leaves no trace is the one that gets missed.
                self._record(scraper, subreddit, months, start)

        if scraper.failed:
            message = (
                f"Arctic Shift scrape of r/{subreddit} captured nothing; every span failed."
            )
            logger.critical(message)
            raise ScrapeFailed(message)
        return scraper

    def run(self, subreddit: str, months: int = 1) -> ArcticShiftScraper:
        """Scrape one subreddit from synchronous code.

        Args:
            subreddit (str): Subreddit to scrape, without the ``r/`` prefix.
            months (int): Number of months back to cover, counting the current month.

        Returns:
            ArcticShiftScraper: The engine that ran, as :meth:`scrape` returns.

        Raises:
            RuntimeError: Called from inside a running event loop, which a Jupyter kernel
                always has. ``asyncio.run`` cannot nest, so the caller must await instead.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.scrape(subreddit=subreddit, months=months))
        raise RuntimeError(
            "run() cannot be called from inside a running event loop, which is what a "
            "Jupyter kernel provides. Use 'await controller.scrape(subreddit)' instead."
        )

    def _record(
        self,
        scraper: ArcticShiftScraper,
        subreddit: str,
        months: int,
        start: datetime,
    ) -> None:
        """Append one run's numbers to the history.

        Args:
            scraper (ArcticShiftScraper): The engine that ran, read through its public
                counters.
            subreddit (str): The subreddit scraped.
            months (int): Months requested.
            start (datetime): When the run began, timed here rather than read from the
                engine so a run that raised before starting still has a duration.
        """
        end = datetime.now()
        self._records.append(
            {
                "subreddit": subreddit,
                "months": months,
                "start": start,
                "end": end,
                "duration": end - start,
                # Spans written, which is not the same as months requested: a resumed run
                # skips the spans already on file.
                "spans": scraper.n_batches,
                "spans_failed": scraper.n_spans_failed,
                "submissions": scraper.n_submissions,
                "comments": scraper.n_comments,
                "tokens": scraper.n_tokens,
            }
        )

    def _build_scraper(
        self, session: aiohttp.ClientSession, subreddit: str, months: int
    ) -> ArcticShiftScraper:
        """Assemble the engine from the controller's settings and this run's job.

        Args:
            session (aiohttp.ClientSession): Session the engine issues requests on. Owned by
                the caller, which closes it when the run ends.
            subreddit (str): Subreddit to scrape.
            months (int): Months to cover.

        Returns:
            ArcticShiftScraper: The configured engine, not yet started.
        """
        return ArcticShiftScraper(
            scraper=session,
            model=self._model,
            printer=self._printer,
            subreddit=subreddit,
            months=months,
            filemanager=self._filemanager,
            force=self._force,
            verbose=self._verbose,
            concurrency=self._concurrency,
            window_hours=self._window_hours,
        )

    def _create_file_manager(self, subreddit: str) -> FileManager:
        """Build the FileManager for one subreddit, failing loudly rather than returning None.

        The CLI's equivalent returns None and lets the caller exit; here the caller is
        ordinary code, and a None that is only checked at one call site is worse than an
        exception.

        Args:
            subreddit (str): Subreddit the FileManager is scoped to, as its topic.

        Returns:
            FileManager: Configured for this subreddit under the controller's directory.

        Raises:
            RuntimeError: The FileManager could not be built, so there is nowhere to write.
        """
        try:
            return FileManager(
                source=self._source,
                topic=subreddit,
                file_location=self._directory,
            )
        except Exception as e:
            logger.exception(f"Failed to create FileManager instance: {e}")
            raise RuntimeError(
                f"Could not create FileManager for r/{subreddit}: {e}"
            ) from e
