#!/usr/bin/env python3
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Description: Reddit Scraper.                                                                     #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filepath   : /ask_reddit                                                                         #
# Filename   : __main__.py                                                                         #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday July 24th 2026 07:29:32 am                                                   #
# Modified   : Saturday July 25th 2026 12:11:17 pm                                                 #
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

import asyncpraw
import praw
import typer
from dotenv import load_dotenv

from ask_reddit.model import GenAIModel
from ask_reddit.persist import FileManager
from ask_reddit.print import Printer
from ask_reddit.scrape_async import ARedditScraper
from ask_reddit.scrape_sync import RedditScraper

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

    # Also log to the console if configured to do so
    if os.getenv("LOG_TO_CONSOLE", "false").lower() == "true":
        console_handler = logging.StreamHandler(sys.stdout)
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
    )
    scraper.scrape()

async def run_async(
    subreddit: str,
    months: int,
    file_manager: FileManager,
    model: GenAIModel,
    printer: Printer,
    force: bool = False,
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

    Raises:
        typer.Exit: If async Reddit authentication fails.
    """
    reddit = await create_async_reddit()
    if not reddit:
        logging.critical("Exiting due to failed Reddit authentication.")
        raise typer.Exit(code=1)

    try:
        scraper = ARedditScraper(
            scraper=reddit,
            model=model,
            printer=printer,
            subreddit=subreddit,
            months=months,
            filemanager=file_manager,
            force=force,
        )
        await scraper.scrape()
    finally:
        # Async PRAW requires an explicit close to release the aiohttp session.
        await reddit.close()

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
    async_mode: bool = typer.Option(
        True,
        "--async/--sync",
        help="Use the fast asynchronous scraper (default) or the synchronous fallback.",
    ),
    directory: Optional[str] = typer.Option(
        None,
        "--directory",
        "-d",
        help="The directory into which the scraped files are stored.",
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
        async_mode (bool): Use the async scraper when True, otherwise use the
            synchronous fallback.
        directory (Optional[str]): Output directory for scraped files. When
            omitted, the ``FILE_LOCATION`` environment variable or ``'data'``
            is used.
        force (bool): When True, scrape the full requested window rather than
            resuming from what is already on file.
    """

    # Setup Logging
    log_filepath = os.getenv("LOG_FILEPATH", "logs/default_scraper.log")
    setup_logging(log_filepath)

    # Acknowledge command line invocation and parameters
    logging.info(
        f"CLI started for r/{subreddit}, months={months}, "
        f"engine={'async' if async_mode else 'sync'}"
    )

    # Instantiate the file manager responsible for persisting submissions to json
    file_manager = create_file_manager(subreddit=subreddit, file_location=directory)
    if not file_manager:
        logging.critical("Exiting due to failed FileManager instantiation.")
        raise typer.Exit(code=1)

    # Instantiate the generative AI client used to count tokens
    model = GenAIModel()

    # Instantiate the printer object
    printer = Printer()

    if async_mode:
        asyncio.run(
            run_async(
                subreddit=subreddit,
                months=months,
                file_manager=file_manager,
                model=model,
                printer=printer,
                force=force,
            )
        )
    else:
        run_sync(
            subreddit=subreddit,
            months=months,
            file_manager=file_manager,
            model=model,
            printer=printer,
            force=force,
        )





if __name__ == "__main__":
    app()
