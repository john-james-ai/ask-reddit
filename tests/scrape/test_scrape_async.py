#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /tests/scrape/test_scrape_async.py                                                  #
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
"""End to end integration tests for the asynchronous scraper.

The async counterpart to ``test_scrape_sync``. It asserts the same corpus contract, so
a divergence between the two engines shows up as a failure here rather than as a silent
difference in the data they produce. It additionally covers the concurrent fan out in
``_flush_batch``, which has no synchronous equivalent.

``pytest-asyncio`` is not a project dependency, so each test drives the coroutine with
``asyncio.run`` from an ordinary test function. The async client owns an aiohttp
session, so every helper closes it in a ``finally`` block.

Run with:  pytest tests/scrape/test_scrape_async.py -m integration
"""
from typing import Any, Callable, Dict, List

import asyncio
import inspect
import logging
from datetime import datetime
from pathlib import Path

import pytest

from ask_reddit.__main__ import create_async_reddit, create_file_manager
from ask_reddit.date import DateTime
from ask_reddit.model import GenAIModel
from ask_reddit.print import Printer
from ask_reddit.scrape_async import ARedditScraper

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
async def _build_and_run(
    subreddit: str, months: int, directory: Path, force: bool, run: bool
) -> ARedditScraper:
    """Builds an async scraper wired as the CLI wires it, optionally running it.

    The aiohttp session behind the async client is released in a ``finally`` block, so
    the client is closed whether or not the scrape succeeds.

    Args:
        subreddit (str): Subreddit to scrape.
        months (int): Month count requested.
        directory (Path): Output directory for batch files.
        force (bool): Whether to bypass the resume calculation.
        run (bool): When False, the scraper is constructed but not run, which is enough
            to inspect the stop boundary the constructor computed.

    Returns:
        ARedditScraper: The scraper, after running when requested.
    """
    reddit = await create_async_reddit()
    if reddit is None:
        pytest.skip("Reddit authentication failed; check the credentials in .env.")

    try:
        file_manager = create_file_manager(subreddit=subreddit, file_location=str(directory))
        assert file_manager is not None, "FileManager could not be constructed"

        scraper = ARedditScraper(
            scraper=reddit,
            model=GenAIModel(),
            printer=Printer(),
            subreddit=subreddit,
            months=months,
            filemanager=file_manager,
            force=force,
        )
        if run:
            await scraper.scrape()
        return scraper
    finally:
        await reddit.close()


# ------------------------------------------------------------------------------------------------ #
def run_scrape(
    subreddit: str, months: int, directory: Path, force: bool = False, run: bool = True
) -> ARedditScraper:
    """Drives the async scraper from a synchronous test."""
    return asyncio.run(
        _build_and_run(
            subreddit=subreddit, months=months, directory=directory, force=force, run=run
        )
    )


# ------------------------------------------------------------------------------------------------ #
@pytest.fixture(scope="module")
def completed_scrape(subreddit: str, months: int, scrape_dir: Path) -> ARedditScraper:
    """Performs one real two month async scrape and returns the scraper that ran it."""
    return run_scrape(subreddit=subreddit, months=months, directory=scrape_dir)


# ------------------------------------------------------------------------------------------------ #
#                                     FIRST, FULL SCRAPE                                           #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.integration
class TestAsyncScrapeProducesCorpus:
    # ============================================================================================ #
    def test_scrape_collects_submissions_and_comments(
        self, completed_scrape: ARedditScraper
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert completed_scrape._n_submissions > 0, "no submissions were collected"
        assert completed_scrape._n_comments > 0, "no comments were collected"
        assert completed_scrape._n_batches > 0, "no batches were written"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_concurrent_fan_out_recorded_no_failures(
        self, completed_scrape: ARedditScraper
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # _flush_batch tolerates individual failures and carries on, so a clean run is
        # only provable by the counter. A non-zero tail means comment trees were lost
        # even though the corpus looks well formed.
        assert completed_scrape._consecutive_failures == 0, (
            f"run ended with {completed_scrape._consecutive_failures} consecutive failures"
        )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_one_base_file_written_per_requested_span(
        self,
        completed_scrape: ARedditScraper,
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
    def test_every_record_matches_the_persisted_schema(
        self,
        completed_scrape: ARedditScraper,
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
        completed_scrape: ARedditScraper,
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

        assert len(records) == completed_scrape._n_submissions
        assert n_comments == completed_scrape._n_comments
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_no_submission_appears_twice(
        self,
        completed_scrape: ARedditScraper,
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

        duplicates = {sid for sid in ids if ids.count(sid) > 1}
        assert not duplicates, f"submissions written more than once: {sorted(duplicates)}"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ------------------------------------------------------------------------------------------------ #
#                                    RESUME AND FORCE                                              #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.integration
class TestAsyncScrapeResumes:
    # ============================================================================================ #
    def test_second_run_rescrapes_only_the_current_month(
        self,
        completed_scrape: ARedditScraper,
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

        scraper = run_scrape(subreddit=subreddit, months=months, directory=scrape_dir)

        assert scraper._stop_utc == DateTime.get_month_dt(n=1), (
            "stop boundary was not narrowed by the files already on disk"
        )

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
        completed_scrape: ARedditScraper,
        subreddit: str,
        months: int,
        scrape_dir: Path,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # Constructed only, not run: the stop boundary is computed in __init__, so the
        # assertion needs no second live scrape.
        scraper = run_scrape(
            subreddit=subreddit, months=months, directory=scrape_dir, force=True, run=False
        )

        assert scraper._stop_utc == DateTime.get_month_dt(n=months)
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)
