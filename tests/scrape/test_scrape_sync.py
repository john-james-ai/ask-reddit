#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /tests/scrape/test_scrape_sync.py                                                   #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday July 25th 2026 01:30:00 pm                                                 #
# Modified   : Saturday July 25th 2026 01:30:00 pm                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2026 John James                                                                 #
# ================================================================================================ #
"""End to end integration tests for the synchronous scraper.

Nothing is mocked. A real two month scrape of r/apljk runs once for the module, and the
assertions inspect the scraper state and the files it produced. Two further scrapes
exercise the resume calculation and the force override.

Run with:  pytest tests/scrape/test_scrape_sync.py -m integration
"""
from typing import Any, Callable, Dict, List

import inspect
import logging
from datetime import datetime
from pathlib import Path

import pytest

from ask_reddit.__main__ import create_file_manager, create_praw_instance
from ask_reddit.date import DateTime
from ask_reddit.model import GenAIModel
from ask_reddit.print import Printer
from ask_reddit.scrape_sync import RedditScraper

# ------------------------------------------------------------------------------------------------ #
# pylint: disable=missing-class-docstring, line-too-long, redefined-outer-name
# mypy: ignore-errors
# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #
double_line = f"\n{100 * '='}"
single_line = f"\n{100 * '-'}"


# ------------------------------------------------------------------------------------------------ #
def log_start(cls_name: str, test_name: str) -> datetime:
    """Logs the start of a test and returns the start time."""
    start = datetime.now()
    logger.info(f"\n\nStarted {cls_name} {test_name} at {start.strftime('%I:%M:%S %p')}")
    logger.info(double_line)
    return start


# ------------------------------------------------------------------------------------------------ #
def log_end(cls_name: str, test_name: str, start: datetime) -> None:
    """Logs the completion of a test and its duration."""
    end = datetime.now()
    logger.info(
        f"\n\nCompleted {cls_name} {test_name} in "
        f"{round((end - start).total_seconds(), 1)} seconds"
    )
    logger.info(single_line)


# ------------------------------------------------------------------------------------------------ #
def build_scraper(subreddit: str, months: int, directory: Path, force: bool) -> RedditScraper:
    """Builds a synchronous scraper wired exactly as the CLI wires it.

    Args:
        subreddit (str): Subreddit to scrape.
        months (int): Month count requested.
        directory (Path): Output directory for batch files.
        force (bool): Whether to bypass the resume calculation.

    Returns:
        RedditScraper: A ready to run scraper.
    """
    reddit = create_praw_instance()
    if reddit is None:
        pytest.skip("Reddit authentication failed; check the credentials in .env.")

    file_manager = create_file_manager(subreddit=subreddit, file_location=str(directory))
    assert file_manager is not None, "FileManager could not be constructed"

    return RedditScraper(
        scraper=reddit,
        model=GenAIModel(),
        printer=Printer(),
        subreddit=subreddit,
        months=months,
        filemanager=file_manager,
        force=force,
    )


# ------------------------------------------------------------------------------------------------ #
@pytest.fixture(scope="module")
def completed_scrape(subreddit: str, months: int, scrape_dir: Path) -> RedditScraper:
    """Performs one real two month scrape and returns the scraper that ran it.

    Module scoped so the live API is exercised once rather than per assertion.
    """
    scraper = build_scraper(
        subreddit=subreddit, months=months, directory=scrape_dir, force=False
    )
    scraper.scrape()
    return scraper


# ------------------------------------------------------------------------------------------------ #
#                                     FIRST, FULL SCRAPE                                           #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.integration
class TestSyncScrapeProducesCorpus:
    # ============================================================================================ #
    def test_scrape_collects_submissions_and_comments(
        self, completed_scrape: RedditScraper
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # A scrape that silently collected nothing would pass every structural check
        # below, so the corpus must be non-empty before anything else is asserted.
        assert completed_scrape._n_submissions > 0, "no submissions were collected"
        assert completed_scrape._n_comments > 0, "no comments were collected"
        assert completed_scrape._n_batches > 0, "no batches were written"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_one_base_file_written_per_requested_span(
        self,
        completed_scrape: RedditScraper,
        scrape_dir: Path,
        subreddit: str,
        expected_spans: List[str],
        base_span_files: Callable[[Path, str], List[Path]],
        span_of: Callable[[Path], str],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        files = base_span_files(scrape_dir, subreddit)
        written_spans = {span_of(path) for path in files}

        assert written_spans == set(expected_spans), (
            f"expected spans {sorted(expected_spans)}, found {sorted(written_spans)}"
        )
        assert completed_scrape._n_batches == len(files), (
            f"reported {completed_scrape._n_batches} batches but wrote {len(files)} files"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_no_timestamped_siblings_on_a_first_run(
        self,
        completed_scrape: RedditScraper,
        scrape_dir: Path,
        subreddit: str,
        base_span_files: Callable[[Path, str], List[Path]],
        all_span_files: Callable[[Path, str], List[Path]],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # Nothing pre-existed, so every path should be a clean base name.
        assert all_span_files(scrape_dir, subreddit) == base_span_files(scrape_dir, subreddit)
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_every_record_matches_the_persisted_schema(
        self,
        completed_scrape: RedditScraper,
        scrape_dir: Path,
        subreddit: str,
        base_span_files: Callable[[Path, str], List[Path]],
        load_records: Callable[[Path], List[Dict[str, Any]]],
        assert_valid_submission: Callable[[Dict[str, Any]], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        for filepath in base_span_files(scrape_dir, subreddit):
            records = load_records(filepath)
            assert records, f"{filepath.name} is empty"
            for record in records:
                assert_valid_submission(record)
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_counters_agree_with_what_was_written(
        self,
        completed_scrape: RedditScraper,
        scrape_dir: Path,
        subreddit: str,
        base_span_files: Callable[[Path, str], List[Path]],
        load_records: Callable[[Path], List[Dict[str, Any]]],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        records = [
            record
            for filepath in base_span_files(scrape_dir, subreddit)
            for record in load_records(filepath)
        ]
        n_comments = sum(len(record["comments"]) for record in records)

        # The reported statistics drive the summary the operator reads, so a drift
        # between them and the corpus on disk is a real defect.
        assert len(records) == completed_scrape._n_submissions
        assert n_comments == completed_scrape._n_comments
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_no_submission_appears_twice(
        self,
        completed_scrape: RedditScraper,
        scrape_dir: Path,
        subreddit: str,
        base_span_files: Callable[[Path, str], List[Path]],
        load_records: Callable[[Path], List[Dict[str, Any]]],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        ids = [
            record["submission_id"]
            for filepath in base_span_files(scrape_dir, subreddit)
            for record in load_records(filepath)
        ]

        # A submission landing in two batches would mean the span boundary logic
        # failed to clear the batch between months.
        duplicates = {sid for sid in ids if ids.count(sid) > 1}
        assert not duplicates, f"submissions written more than once: {sorted(duplicates)}"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ------------------------------------------------------------------------------------------------ #
#                                    RESUME AND FORCE                                              #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.integration
class TestSyncScrapeResumes:
    # ============================================================================================ #
    def test_second_run_rescrapes_only_the_current_month(
        self,
        completed_scrape: RedditScraper,
        subreddit: str,
        months: int,
        scrape_dir: Path,
        base_span_files: Callable[[Path, str], List[Path]],
        all_span_files: Callable[[Path, str], List[Path]],
        span_of: Callable[[Path], str],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        files_before = set(all_span_files(scrape_dir, subreddit))
        base_before = set(base_span_files(scrape_dir, subreddit))

        scraper = build_scraper(
            subreddit=subreddit, months=months, directory=scrape_dir, force=False
        )
        # With the current month already on file, the resume calculation should pull the
        # stop boundary forward to the start of this month rather than the requested two.
        assert scraper._stop_utc == DateTime.get_month_dt(n=1), (
            "stop boundary was not narrowed by the files already on disk"
        )

        scraper.scrape()

        new_files = set(all_span_files(scrape_dir, subreddit)) - files_before
        assert len(new_files) == 1, f"expected exactly one new file, found {sorted(new_files)}"
        assert span_of(new_files.pop()) == DateTime.get_month_st(n=1), (
            "the rescrape did not target the current month"
        )

        # Nothing already on disk may be replaced or removed by a rescrape.
        assert set(base_span_files(scrape_dir, subreddit)) == base_before
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_force_ignores_existing_files_and_scrapes_the_full_window(
        self,
        completed_scrape: RedditScraper,
        subreddit: str,
        months: int,
        scrape_dir: Path,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        scraper = build_scraper(
            subreddit=subreddit, months=months, directory=scrape_dir, force=True
        )

        # force bypasses the resume calculation entirely, so the boundary is the full
        # requested window regardless of what is already on disk.
        assert scraper._stop_utc == DateTime.get_month_dt(n=months)
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)
