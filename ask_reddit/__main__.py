#!/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/__main__.py                                                             #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.com                                                           #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday June 21st 2025 12:28:41 pm                                                 #
# Modified   : Saturday August 30th 2025 02:42:30 pm                                               #
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

from ask_reddit.constants import DEFAULT_GENAI_MODEL
from ask_reddit.drive import GDriveUploader
from ask_reddit.model import GenAIModel
from ask_reddit.monitor import CircuitBreaker
from ask_reddit.persist import FileManager
from ask_reddit.print import Printer
from ask_reddit.scrape import RedditScraper

# ------------------------------------------------------------------------------------------------ #
load_dotenv()
# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)


# --- Typer App Initialization ---
# This creates the main application object.
app = typer.Typer(
    name="Reddit Scraper",
    help="A CLI tool to scrape Reddit submissions and comments for a specified time period.",
    add_completion=False,
)


def setup_logging(log_filepath: str) -> None:
    """
    Configures the root logger to use a time-rotating file handler.

    Log files will rotate daily, and up to 7 old log files will be kept.
    """
    # Ensure the log directory exists
    log_dir = os.path.dirname(log_filepath)
    os.makedirs(log_dir, exist_ok=True)

    # Define the log message format
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Prevent handlers from being added multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create the file handler
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_filepath, when="d", interval=1, backupCount=7
    )
    file_handler.setFormatter(formatter)

    # Create a list of the handlers to use
    handlers = [file_handler]

    # Create the console handler if so designated.
    if os.getenv("LOG_TO_CONSOLE", "false").lower() == "true":
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    # --- Configure the root logger with the handlers ---
    # This single call replaces all the logger.addHandler() and setLevel() calls.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )

    # Get the loggers for the noisy Google libraries and set their level higher.
    # This silences their INFO messages, only showing WARNING or ERROR.
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)
    logging.getLogger("google.auth").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # It's good practice to get the logger after configuration to announce it's ready.
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
        logger.info(f"Successfully authenticated as Reddit user: {reddit.user.me()}")
        return reddit
    except Exception as e:
        logger.error(f"Failed to create PRAW instance: {e}")
        return None


def create_genai_model() -> GenAIModel:
    """Creates a GenAIModel instance, used for counting tokens."""
    api_key = os.getenv("GOOGLE_API_KEY")
    model_name = os.getenv("GENAI_MODEL", DEFAULT_GENAI_MODEL)
    return GenAIModel(api_key=api_key, model_name=model_name)


def create_file_manager() -> Optional[FileManager]:
    """Creates a file manager instance for persistance"""
    FILE_LOCATION = os.getenv("FILE_LOCATION", "data")
    SOURCE = os.getenv("SOURCE", "reddit")
    TIMESTAMP = os.getenv("TIMESTAMP", "true").lower() == "true"
    try:
        return FileManager(source=SOURCE, file_location=FILE_LOCATION, timestamp=TIMESTAMP)
    except Exception as e:
        logger.exception(f"Failed to create FileManager instance: {e}")
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
    google_drive: bool = typer.Option(
        False, "--google-drive", "-g", help="Upload the scraped files to Google Drive."
    ),
):
    """
    The main function to run the Reddit scraper CLI.
    """

    # Setup Logging
    log_filepath = os.getenv("LOG_FILEPATH", "logs/default_scraper.log")
    setup_logging(log_filepath)

    # Acknowledge command line invocation and parameters
    logger.info(f"CLI started for r/{subreddit}, days={days}")

    # Obtain the reddit praw instance
    reddit = create_praw_instance()
    if not reddit:
        logger.critical("Exiting due to failed Reddit authentication.")
        raise typer.Exit(code=1)

    # Instantiate the file manager responsible for persisting submissions to json
    file_manager = create_file_manager()
    if not file_manager:
        logger.critical("Exiting due to failed FileManager instantiation.")
        raise typer.Exit(code=1)

    # Instantiate the generative AI client used to count tokens
    model = create_genai_model()

    # Instantiate the printer object
    printer = Printer()

    # Instantiate the circuit breaker
    cb = CircuitBreaker()

    # Intantiate the scraper
    scraper = RedditScraper(
        scraper=reddit,
        model=model,
        printer=printer,
        circuit_breaker=cb,
        subreddit=subreddit,
        days=days,
        filemanager=file_manager,
    )
    # Scrape subreddit submissions
    scraper.scrape()

    # Handle Google Drive file upload if requested
    if google_drive and scraper.filepath:
        folder_id = os.getenv(f"GOOGLE_DRIVE_FOLDER_ID")
        token_filepath = os.getenv("GOOGLE_TOKENS_JSON_FILEPATH")
        credentials_filepath = os.getenv("GOOGLE_CREDENTIALS_FILEPATH")
        gdrive = GDriveUploader(
            token_filepath=token_filepath,
            credentials_filepath=credentials_filepath,
            folder_id=folder_id,
        )
        gdrive.upload(filepath=scraper.filepath)


if __name__ == "__main__":
    app()
