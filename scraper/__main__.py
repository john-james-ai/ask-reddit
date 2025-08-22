#!/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /scraper/__main__.py                                                                #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.com                                                           #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday June 21st 2025 12:28:41 pm                                                 #
# Modified   : Sunday June 22nd 2025 07:16:15 am                                                   #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
from typing import Optional

import logging
import logging.handlers
import os
import sys

import praw
import typer
from dotenv import load_dotenv

from scraper.constants import BatchSpan
from scraper.model import GenAIModel
from scraper.monitor import CircuitBreaker
from scraper.persist import FileManager
from scraper.print import Printer
from scraper.scrape import RedditScraper

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
    """
    Configures a time-rotating logger.

    Log files will rotate daily, and up to 7 old log files will be kept.
    This function configures the root logger, so any module using
    logging.getLogger(__name__) will inherit this configuration.
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
    """
    Creates and authenticates a PRAW Reddit instance using credentials
    from environment variables.
    """

    USER_AGENT = (
        f"python:{os.getenv("APP_NAME")}:{os.getenv("VERSION")} by u/{os.getenv("REDDIT_USERNAME")}"
    )
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


def create_file_manager(subreddit: str) -> Optional[FileManager]:
    """Creates a file manager instance for persistance"""
    FILE_LOCATION = os.getenv("FILE_LOCATION", "data")
    SOURCE = os.getenv("SOURCE", "reddit")
    TIMESTAMP = os.getenv("TIMESTAMP", "true").lower() == "true"
    try:
        return FileManager(
            source=SOURCE, topic=subreddit, file_location=FILE_LOCATION, timestamp=TIMESTAMP
        )
    except Exception as e:
        logging.exception(f"Failed to create FileManager instance: {e}")
        return None


@app.command()
def main(
    subreddit: str = typer.Option(
        ...,  # The '...' makes this option required.
        "--subreddit",
        "-s",
        help="The name of the subreddit to scrape (e.g., 'learnpython').",
    ),
    days: int = typer.Option(
        30,
        "--days",
        "-d",
        help="The number of past days to extract data for.",
    ),
    batch_span: BatchSpan = typer.Option(
        BatchSpan.MONTH,  # Default value must be an Enum member
        "--batch",
        "-c",
        case_sensitive=False,  # Allows user to type 'M' or 'D'
        help="The time span for batch output files.",
    ),
):
    """
    The main function to run the Reddit scraper CLI.
    """

    # Setup Logging
    log_filepath = os.getenv("LOG_FILEPATH", "logs/default_scraper.log")
    setup_logging(log_filepath)

    # Acknowledge command line invocation and parameters
    logging.info(f"CLI started for r/{subreddit}, days={days}, batch='{batch_span}'")

    # Obtain the reddit praw instance
    reddit = create_praw_instance()
    if not reddit:
        logging.critical("Exiting due to failed Reddit authentication.")
        raise typer.Exit(code=1)

    # Instantiate the file manager responsible for persisting submissions to json
    file_manager = create_file_manager(subreddit=subreddit)
    if not file_manager:
        logging.critical("Exiting due to failed FileManager instantiation.")
        raise typer.Exit(code=1)

    # Instantiate the generative AI client used to count tokens
    model = GenAIModel()

    # Instantiate the printer object
    printer = Printer()

    # Instantiate the circuit breaker
    cb = CircuitBreaker()
    scraper = RedditScraper(
        scraper=reddit,
        model=model,
        printer=printer,
        circuit_breaker=cb,
        subreddit=subreddit,
        days=days,
        batch_span=batch_span,
        filemanager=file_manager,
    )
    scraper.scrape()


if __name__ == "__main__":
    app()
