#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/controller.py                                                           #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Tuesday July 28th 2026                                                              #
# Modified   : Tuesday July 28th 2026                                                              #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2026 John James                                                                 #
# ================================================================================================ #
"""Programmatic entry point for a scrape, for callers that are not a command line.

:mod:`ask_reddit.__main__` wires a run by hand inside a Typer command: logging, the
:class:`FileManager`, the token-count model, the printer, the session, the engine. That
wiring is only reachable by launching a process, which is the wrong shape for a notebook.
A shelled-out run puts the scraper's progress bar in a child process, where it can only
write bytes to a pipe: no kernel, no comm channel, and therefore no widget. The bar is also
the natural place to watch a scrape from, since a healthy span logs nothing.

Running in the kernel instead makes the bar a widget and makes a run an ordinary object,
so several subreddits are a ``for`` loop rather than a shell loop, and a failure is an
exception to catch rather than an exit code to inspect.

This is additive. The CLI keeps its own wiring and behaviour unchanged, so anything that
runs today still runs the same way; this is a second door into the same engines.
"""
import asyncio
import logging
import os
from typing import Optional

import aiohttp
from dotenv import load_dotenv

from ask_reddit.constants import (
    ARCTICSHIFT_USER_AGENT,
    ARCTICSHIFT_WINDOW_HOURS,
    DEFAULT_ARCTICSHIFT_CONCURRENCY,
)
from ask_reddit.model import GenAIModel
from ask_reddit.persist import FileManager
from ask_reddit.print import Printer
from ask_reddit.scrape_arcticshift import ArcticShiftScraper

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
    """Configure and run one subreddit's scrape from inside the calling process.

    Construction only records intent; nothing is built and no request is made until
    :meth:`scrape` runs. That keeps the constructor safe to call in a loop that builds a
    list of runs before starting any of them.

    Args:
        subreddit (str): Subreddit to scrape, without the ``r/`` prefix.
        months (int): Number of months back to cover, counting the current month. Defaults
            to 1, matching the CLI's ``--month``. Every argument below it defaults to the
            same value its CLI option does, so ``AskReddit("learnpython")`` is the
            programmatic spelling of ``python -m ask_reddit -s learnpython``.
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
        subreddit: str,
        months: int = 1,
        *,
        directory: str = FILE_LOCATION,
        source: str = SOURCE,
        force: bool = False,
        verbose: bool = False,
        concurrency: int = DEFAULT_ARCTICSHIFT_CONCURRENCY,
        window_hours: int = ARCTICSHIFT_WINDOW_HOURS,
        configure_logging: bool = True,
        log_filepath: str = LOG_FILEPATH,
    ) -> None:
        self._subreddit = subreddit
        self._source = source
        self._months = months
        self._directory = directory
        self._force = force
        self._verbose = verbose
        self._concurrency = concurrency
        self._window_hours = window_hours
        self._configure_logging = configure_logging
        self._log_filepath = log_filepath
        # All built by scrape() rather than here, so constructing a controller costs
        # nothing and cannot fail: a loop can build a list of runs before starting any.
        self._scraper: Optional[ArcticShiftScraper] = None
        self._filemanager: Optional[FileManager] = None
        self._model: Optional[GenAIModel] = None
        self._printer: Optional[Printer] = None

    @property
    def scraper(self) -> Optional[ArcticShiftScraper]:
        """The engine from the last run, or None before the first one."""
        return self._scraper

    @property
    def filemanager(self) -> Optional[FileManager]:
        """The FileManager the last run wrote through, or None before the first one."""
        return self._filemanager

    @property
    def model(self) -> Optional[GenAIModel]:
        """The token-count model the last run used, or None before the first one."""
        return self._model

    @property
    def printer(self) -> Optional[Printer]:
        """The printer the last run used, or None before the first one."""
        return self._printer

    async def scrape(self) -> ArcticShiftScraper:
        """Run the scrape and return the engine that ran it.

        Returns:
            ArcticShiftScraper: The engine, for its counts and its ``failed`` flag.

        Raises:
            ScrapeFailed: The run captured nothing; every span failed.
            RuntimeError: The FileManager could not be built, so there is nowhere to write.
        """
        if self._configure_logging:
            # Imported here rather than at module scope: __main__ builds a Typer app on
            # import, and a notebook importing this module should not pay for that.
            from ask_reddit.__main__ import setup_logging

            setup_logging(self._log_filepath)

        # The same three collaborators the CLI builds, in the same order: somewhere to
        # write, something to count tokens, something to print with. Held on the instance
        # rather than left as locals so a caller can reach the FileManager for the paths it
        # wrote, which is otherwise only recoverable from the log.
        self._filemanager = self._create_file_manager()
        self._model = GenAIModel()
        self._printer = Printer(verbose=self._verbose)

        logger.info(
            f"Programmatic scrape started for r/{self._subreddit}, months={self._months}, "
            f"engine=arcticshift"
        )

        # Arctic Shift answers the default aiohttp agent with a 403, so the header is
        # required rather than merely polite.
        headers = {"User-Agent": ARCTICSHIFT_USER_AGENT}
        async with aiohttp.ClientSession(headers=headers) as session:
            scraper = self._build_scraper(session)
            self._scraper = scraper
            await scraper.scrape()

        if scraper.failed:
            message = (
                f"Arctic Shift scrape of r/{self._subreddit} captured nothing; "
                f"every span failed."
            )
            logger.critical(message)
            raise ScrapeFailed(message)
        return scraper

    def run(self) -> ArcticShiftScraper:
        """Run the scrape from synchronous code.

        Returns:
            ArcticShiftScraper: The engine that ran, as :meth:`scrape` returns.

        Raises:
            RuntimeError: Called from inside a running event loop, which a Jupyter kernel
                always has. ``asyncio.run`` cannot nest, so the caller must await instead.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.scrape())
        raise RuntimeError(
            "run() cannot be called from inside a running event loop, which is what a "
            "Jupyter kernel provides. Use 'await controller.scrape()' instead."
        )

    def _build_scraper(self, session: aiohttp.ClientSession) -> ArcticShiftScraper:
        """Assemble the engine from the collaborators built in :meth:`scrape`.

        Args:
            session (aiohttp.ClientSession): Session the engine issues requests on. Owned by
                the caller, which closes it when the run ends.

        Returns:
            ArcticShiftScraper: The configured engine, not yet started.
        """
        return ArcticShiftScraper(
            scraper=session,
            model=self._model,
            printer=self._printer,
            subreddit=self._subreddit,
            months=self._months,
            filemanager=self._filemanager,
            force=self._force,
            verbose=self._verbose,
            concurrency=self._concurrency,
            window_hours=self._window_hours,
        )

    def _create_file_manager(self) -> FileManager:
        """Build the FileManager, failing loudly rather than returning None.

        The CLI's equivalent returns None and lets the caller exit; here the caller is
        ordinary code, and a None that is only checked at one call site is worse than an
        exception.
        """
        try:
            return FileManager(
                source=self._source,
                topic=self._subreddit,
                file_location=self._directory,
            )
        except Exception as e:
            logger.exception(f"Failed to create FileManager instance: {e}")
            raise RuntimeError(
                f"Could not create FileManager for r/{self._subreddit}: {e}"
            ) from e
