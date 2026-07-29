#!/usr/bin/env python3
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Description: Reddit Scraper.                                                                     #
# Version    : 0.3.1                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : __main__.py                                                                         #
# Filename   : __main__.py                                                                         #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday July 24th 2026 07:29:32 am                                                   #
# Modified   : Wednesday July 29th 2026 01:26:58 am                                                #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2026 John James                                                                 #
# ================================================================================================ #
"""Main entry point for the Ask Reddit CLI application.

This module sets up the command-line interface (CLI) for the Ask Reddit application. It uses the Typer library to define commands and options, allowing users to specify parameters such as the subreddit to scrape, the number of months to look back, and whether to use the asynchronous or synchronous scraping engine. The module also handles logging configuration, Reddit API authentication, and the instantiation of necessary components like the FileManager, GenAIModel, and Printer. Depending on the user's choice, it runs either the asynchronous or synchronous scraper to collect Reddit submissions and comments.
"""
import asyncio
import logging
import logging.handlers
import os
import sys
from typing import Optional

import aiohttp
import asyncpraw
import praw
import typer
from dotenv import load_dotenv
from tqdm.auto import tqdm

from ask.constants import ARCTICSHIFT_USER_AGENT
from ask.model import GenAIModel
from ask.persist import FileManager
from ask.print import Printer
from ask.scrape_arcticshift import ArcticShiftScraper
from ask.scrape_async import ARedditScraper
from ask.scrape_sync import RedditScraper

# ------------------------------------------------------------------------------------------------ #
load_dotenv()
# ------------------------------------------------------------------------------------------------ #


# --- Typer App Initialization ---
# This creates the main application object.
app = typer.Typer(
    name="Reddit Scraper",
    help="A CLI tool to scrape Reddit submissions and comments for a specified time period.",
    add_completion=False,
)


class _TqdmLoggingHandler(logging.Handler):
    """Write log records without tearing the progress bar apart.

    A plain ``StreamHandler`` writes straight into the same stream the bar is redrawing,
    which leaves the bar duplicated mid-line and the message half-overwritten. ``tqdm.write``
    clears the bar, emits the line, and redraws it underneath. Writes to stderr because that
    is where the bar itself is written; splitting them across streams puts the clearing
    sequence on one stream and the bar on the other, which is the corruption this avoids.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.write(self.format(record), file=sys.stderr)
        except Exception:
            self.handleError(record)


def setup_logging(log_filepath: str) -> None:
    """Configure logging to use a time-rotating file handler.

    The root logger is configured to emit INFO level logs to a file that
    rotates daily. Optionally, logs are also sent to the console when the
    environment variable ``LOG_TO_CONSOLE`` is set to ``true``.

    Args:
        log_filepath (str): Path to the log file. The function ensures the
            directory exists and creates a daily rotating file handler with a
            seven-day retention.
    """
    # Ensure the log directory exists
    log_dir = os.path.dirname(log_filepath)
    os.makedirs(log_dir, exist_ok=True)

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Prevent handlers from being added multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create a handler for rotating files
    handler = logging.handlers.TimedRotatingFileHandler(
        log_filepath, when="d", interval=1, backupCount=7
    )

    # Create a formatter and set it for the handler
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)

    # Add the handler to the root logger
    logger.addHandler(handler)

    # The token-count client logs one INFO line per HTTP call, which is one line per batch
    # written and nothing a run is ever diagnosed from. Warnings and errors still come
    # through, so a genuine failure is not hidden by this.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Also log to the console if configured to do so. The console is where the progress bar
    # lives, so it is held to a higher bar than the file: INFO and WARNING are routine
    # during a scrape (skipped spans, throttling) and belong in the file, where they can be
    # read after the fact without competing with the bar for the same lines. Only ERROR and
    # above interrupt, and those go through the tqdm-aware handler so the bar survives.
    if os.getenv("LOG_TO_CONSOLE", "false").lower() == "true":
        console_handler = _TqdmLoggingHandler()
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logging.info("Logging has been configured successfully.")


def create_praw_instance() -> Optional[praw.Reddit]:
    """Create and authenticate a synchronous PRAW ``Reddit`` instance.

    Credentials are read from environment variables: ``REDDIT_CLIENT_ID``,
    ``REDDIT_CLIENT_SECRET``, ``REDDIT_USERNAME``, ``REDDIT_PASSWORD``, and
    ``USER_AGENT``. On success, the authenticated ``praw.Reddit`` instance is
    returned; on failure, ``None`` is returned and the error is logged.

    Returns:
        Optional[praw.Reddit]: Authenticated PRAW Reddit instance or ``None``
            if authentication failed.
    """

    USER_AGENT = os.getenv("USER_AGENT")
    try:
        reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent=USER_AGENT,
            username=os.getenv("REDDIT_USERNAME"),
            password=os.getenv("REDDIT_PASSWORD"),
        )
        # Validate credentials by trying to access user data
        logging.info(f"Successfully authenticated as Reddit user: {reddit.user.me()}")
        return reddit
    except Exception as e:
        logging.error(f"Failed to create PRAW instance: {e}")
        return None


async def create_async_reddit() -> Optional[asyncpraw.Reddit]:
    """Create and authenticate an asynchronous ``asyncpraw.Reddit`` instance.

    Credentials are sourced from the same environment variables as the
    synchronous client. Returns the authenticated async client on success or
    ``None`` on failure.

    Returns:
        Optional[asyncpraw.Reddit]: Authenticated async Reddit client or
            ``None`` if authentication failed.
    """

    USER_AGENT = os.getenv("USER_AGENT")
    try:
        reddit = asyncpraw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent=USER_AGENT,
            username=os.getenv("REDDIT_USERNAME"),
            password=os.getenv("REDDIT_PASSWORD"),
        )
        # Validate credentials by trying to access user data
        logging.info(f"Successfully authenticated as Reddit user: {await reddit.user.me()}")
        return reddit
    except Exception as e:
        logging.error(f"Failed to create Async PRAW instance: {e}")
        return None


def create_file_manager(
    subreddit: str, file_location: Optional[str] = None
) -> Optional[FileManager]:
    """Create a configured :class:`FileManager` for a given subreddit.

    Args:
        subreddit (str): Subreddit/topic name used as the FileManager topic.
        file_location (Optional[str]): Directory where files will be written.
            If ``None``, the ``FILE_LOCATION`` environment variable or
            ``'data'`` is used.

    Returns:
        Optional[FileManager]: A configured FileManager instance, or ``None``
            if instantiation failed (an exception will be logged).
    """
    FILE_LOCATION = file_location or os.getenv("FILE_LOCATION", "data")
    SOURCE = os.getenv("SOURCE", "reddit")
    
    try:
        return FileManager(
            source=SOURCE, topic=subreddit, file_location=FILE_LOCATION
        )
    except Exception as e:
        logging.exception(f"Failed to create FileManager instance: {e}")
        return None

def run_sync(
    subreddit: str,
    months: int,
    file_manager: FileManager,
    model: GenAIModel,
    printer: Printer,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Run the synchronous (blocking) scraping engine.

    This function creates a PRAW client, instantiates the synchronous
    ``RedditScraper`` and executes ``scrape()``. If authentication fails the
    function logs a critical error and exits via ``typer.Exit``.

    Args:
        subreddit (str): Name of the subreddit to scrape.
        months (int): Number of past months to include.
        file_manager (FileManager): FileManager used to persist results.
        model (GenAIModel): Generative AI model helper used by scraper.
        printer (Printer): Printer instance for formatted output.
        force (bool): When True, scrape the full requested window rather than
            resuming from what is already on file.
        verbose (bool): When True, print progress and the summary to the console.

    Raises:
        typer.Exit: If Reddit authentication fails.
    """
    reddit = create_praw_instance()
    if not reddit:
        logging.critical("Exiting due to failed Reddit authentication.")
        raise typer.Exit(code=1)

    scraper = RedditScraper(
        scraper=reddit,
        model=model,
        printer=printer,
        subreddit=subreddit,
        months=months,
        filemanager=file_manager,
        force=force,
        verbose=verbose,
    )
    scraper.scrape()

async def run_async(
    subreddit: str,
    months: int,
    file_manager: FileManager,
    model: GenAIModel,
    printer: Printer,
    force: bool = False,
    verbose: bool = False,
    concurrency: Optional[int] = None,
) -> None:
    """Run the asynchronous scraping engine using ``asyncpraw``.

    This coroutine creates an async PRAW client, instantiates
    ``ARedditScraper``, and awaits its ``scrape()`` coroutine. The async
    PRAW client is closed in a ``finally`` block to ensure the aiohttp
    session is released.

    Args:
        subreddit (str): Name of the subreddit to scrape.
        months (int): Number of past months to include.
        file_manager (FileManager): FileManager used to persist results.
        model (GenAIModel): Generative AI model helper used by scraper.
        printer (Printer): Printer instance for formatted output.
        force (bool): When True, scrape the full requested window rather than
            resuming from what is already on file.
        verbose (bool): When True, print progress and the summary to the console.
        concurrency (Optional[int]): Maximum concurrent submission processors. When None,
            the scraper's own default applies.

    Raises:
        typer.Exit: If async Reddit authentication fails.
    """
    reddit = await create_async_reddit()
    if not reddit:
        logging.critical("Exiting due to failed Reddit authentication.")
        raise typer.Exit(code=1)

    # Omitted rather than passed as None, so the default lives in exactly one place: the
    # scraper's own signature.
    overrides = {} if concurrency is None else {"concurrency": concurrency}

    try:
        scraper = ARedditScraper(
            scraper=reddit,
            model=model,
            printer=printer,
            subreddit=subreddit,
            months=months,
            filemanager=file_manager,
            force=force,
            verbose=verbose,
            **overrides,
        )
        await scraper.scrape()
    finally:
        # Async PRAW requires an explicit close to release the aiohttp session.
        await reddit.close()

async def run_arcticshift(
    subreddit: str,
    months: int,
    file_manager: FileManager,
    model: GenAIModel,
    printer: Printer,
    force: bool = False,
    verbose: bool = False,
    concurrency: Optional[int] = None,
    window_hours: Optional[int] = None,
) -> None:
    """Run Arctic Shift scraping engine against Arctic Shift.

    Unlike the live engines this needs no Reddit credentials, since it never touches
    Reddit's API. It is the only engine that can reach submissions older than roughly the
    last thousand in a subreddit's listing, which for a busy subreddit is about a week.

    Args:
        subreddit (str): Name of the subreddit to scrape.
        months (int): Number of past months to include.
        file_manager (FileManager): FileManager used to persist results.
        model (GenAIModel): Generative AI model helper used by the scraper.
        printer (Printer): Printer instance for formatted output.
        force (bool): When True, scrape the full requested window rather than
            resuming from what is already on file.
        verbose (bool): When True, print progress and the summary to the console.
        concurrency (Optional[int]): Maximum concurrent Arctic Shift requests. When None, the
            scraper's own default applies.
        window_hours (Optional[int]): Size of the time slices a span is cut into. When
            None, the scraper's own default applies.

    Raises:
        typer.Exit: The run captured nothing; every span failed. Raised rather than
            returned so a batch over many subreddits cannot walk past the failure.
    """
    # Omitted rather than passed as None, so each default lives in exactly one place: the
    # scraper's own signature.
    overrides = {
        key: value
        for key, value in (("concurrency", concurrency), ("window_hours", window_hours))
        if value is not None
    }
    # Arctic Shift answers the default aiohttp agent with a 403, so the header is required
    # rather than merely polite.
    headers = {"User-Agent": ARCTICSHIFT_USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        scraper = ArcticShiftScraper(
            scraper=session,
            model=model,
            printer=printer,
            subreddit=subreddit,
            months=months,
            filemanager=file_manager,
            force=force,
            verbose=verbose,
            **overrides,
        )
        await scraper.scrape()
        # A run that captured nothing must not exit 0, or a batch loop over many
        # subreddits will walk straight past the failure.
        if scraper.failed:
            logging.critical(
                f"Arctic Shift scrape of r/{subreddit} captured nothing; every span failed."
            )
            raise typer.Exit(code=1)


@app.command()
def main(
    subreddit: str = typer.Option(
        ...,  # The '...' makes this option required.
        "--subreddit",
        "-s",
        help="The name of the subreddit to scrape (e.g., 'learnpython').",
    ),
    months: int = typer.Option(
        1,
        "--month",
        "-m",
        help="The number of past months for which data shall be extracted.",
    ),
    arcticshift: bool = typer.Option(
        True,
        "--arcticshift/--live",
        help="Read from the Arctic Shift (default) or from Reddit's API. The live "
        "API caps every listing at ~1000 submissions regardless of --month, so --live "
        "reaches only about a week of a busy subreddit. Arctic Shift has no such cap and "
        "needs no Reddit credentials.",
    ),
    async_mode: bool = typer.Option(
        True,
        "--async/--sync",
        help="With --live, choose the asynchronous scraper (default) or the synchronous "
        "fallback. Ignored by the Arctic Shift engine, which is always asynchronous.",
    ),
    directory: Optional[str] = typer.Option(
        None,
        "--directory",
        "-d",
        help="The directory into which the scraped files are stored.",
    ),
    concurrency: Optional[int] = typer.Option(
        None,
        "--concurrency",
        "-c",
        min=1,
        help="Maximum requests in flight. Applies to Arctic Shift and --live --async "
        "engines; the --sync engine is serial and ignores it. Defaults to the engine's "
        "own setting.",
    ),
    window_hours: Optional[int] = typer.Option(
        None,
        "--window-hours",
        "-w",
        min=1,
        help="Arctic Shift engine only: size of the time slices each month is cut into. "
        "Pagination is serial within a slice, so this bounds how much of --concurrency "
        "can be used. Affects speed only, not results.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose/--quiet",
        "-v",
        help="Print progress and the run summary to the console. Errors always go to "
        "stderr, and logging is unaffected.",
    ),
    force: bool = typer.Option(
        False,
        "--force/--no-force",
        "-f",
        help="Scrape the full requested window instead of resuming from existing files.",
    ),
):
    """Entry point for the Typer-based CLI.

    The function wires up logging, constructs the required helpers
    (``FileManager``, ``GenAIModel``, and ``Printer``) and dispatches to the
    chosen scraping engine (async by default).

    Args:
        subreddit (str): Subreddit name to scrape (required).
        months (int): Number of past months to retrieve (default: 1).
        arcticshift (bool): Read from the Arctic Shift rather than Reddit's API.
            The default, and the only engine that can reach past Reddit's ~1000-item
            listing cap. Takes precedence over ``async_mode``.
        async_mode (bool): With ``arcticshift`` disabled, use the async scraper when True
            and the synchronous fallback otherwise. Ignored when ``arcticshift`` is set.
        directory (Optional[str]): Output directory for scraped files. When
            omitted, the ``FILE_LOCATION`` environment variable or ``'data'``
            is used.
        concurrency (Optional[int]): Maximum requests in flight, for the engines that
            make more than one at a time. None leaves the engine's own default.
        window_hours (Optional[int]): Arctic Shift engine only; size of the time slices a
            month is cut into. None leaves the engine's own default.
        verbose (bool): When True, print the run summary to the console. The progress bar
            shows regardless.
        force (bool): When True, scrape the full requested window rather than
            resuming from what is already on file.

    Raises:
        typer.Exit: The FileManager could not be built, Reddit authentication failed, or
            the scrape captured nothing. Every one of these must exit non-zero so a shell
            loop over many subreddits registers the failure.
    """

    # Setup Logging
    log_filepath = os.getenv("LOG_FILEPATH", "logs/default_scraper.log")
    setup_logging(log_filepath)

    # Acknowledge command line invocation and parameters
    logging.info(
        f"CLI started for r/{subreddit}, months={months}, "
        f"engine={'arcticshift' if arcticshift else ('async' if async_mode else 'sync')}"
    )

    # Instantiate the file manager responsible for persisting submissions to json
    file_manager = create_file_manager(subreddit=subreddit, file_location=directory)
    if not file_manager:
        logging.critical("Exiting due to failed FileManager instantiation.")
        raise typer.Exit(code=1)

    # Instantiate the generative AI client used to count tokens
    model = GenAIModel()

    # Instantiate the printer object
    printer = Printer(verbose=verbose)

    if arcticshift:
        asyncio.run(
            run_arcticshift(
                subreddit=subreddit,
                months=months,
                file_manager=file_manager,
                model=model,
                printer=printer,
                force=force,
                verbose=verbose,
                concurrency=concurrency,
                window_hours=window_hours,
            )
        )
    elif async_mode:
        if window_hours is not None:
            logging.warning("--window-hours applies to the Arctic Shift engine only; ignoring.")
        asyncio.run(
            run_async(
                subreddit=subreddit,
                months=months,
                file_manager=file_manager,
                model=model,
                printer=printer,
                force=force,
                verbose=verbose,
                concurrency=concurrency,
            )
        )
    else:
        if concurrency is not None or window_hours is not None:
            logging.warning("--concurrency and --window-hours do not apply to --sync; ignoring.")
        run_sync(
            subreddit=subreddit,
            months=months,
            file_manager=file_manager,
            model=model,
            printer=printer,
            force=force,
            verbose=verbose,
        )





if __name__ == "__main__":
    app()
