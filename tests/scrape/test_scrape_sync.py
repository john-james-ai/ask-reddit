#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.3.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : test_scrape_sync.py                                                                 #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday July 25th 2026 01:30:00 pm                                                 #
# Modified   : Wednesday July 29th 2026 01:05:37 am                                                #
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
import inspect
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

from ask.__main__ import create_file_manager, create_praw_instance
from ask.date import DateTime
from ask.model import GenAIModel
from ask.print import Printer
from ask.scrape_sync import RedditScraper

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

        # A quiet month may have no submissions and therefore no file, so the written
        # spans must be a subset of those requested rather than an exact match. At least
        # two are required, or the span boundary was never crossed and the batching
        # logic went untested.
        assert written_spans <= set(expected_spans), (
            f"wrote spans outside the requested window: {sorted(written_spans - set(expected_spans))}"
        )
        assert len(written_spans) >= 2, (
            f"only {len(written_spans)} span(s) written; no batch boundary was exercised"
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
#                                       SPAN SELECTION                                             #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.integration
class TestSyncScrapeSelectsSpans:
    """Span selection driven by real corpora with files removed.

    Each case starts from the corpus the live scrape produced and deletes specific span
    files, which is exactly what an aborted run or a lost file leaves behind. Because a
    quiet month may legitimately have produced no file, assertions that a span is *not*
    selected are made only for spans confirmed present on disk.
    """

    # ============================================================================================ #
    def test_complete_corpus_selects_only_the_current_month(
        self,
        completed_scrape: RedditScraper,
        subreddit: str,
        months: int,
        scrape_dir: Path,
        corpus_without: Callable[[Path, List[int]], Path],
        present_spans: Callable[[Path, str], set],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        directory = corpus_without(scrape_dir, [])
        scraper = build_scraper(subreddit, months, directory, force=False)

        current = DateTime.get_month_st(n=1)
        assert current in scraper._needed_spans, "the current month must always be selected"

        for span in present_spans(directory, subreddit):
            if span != current:
                assert span not in scraper._needed_spans, (
                    f"{span} is complete on disk and should have been skipped"
                )
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_aborted_run_still_selects_the_months_it_never_reached(
        self,
        completed_scrape: RedditScraper,
        subreddit: str,
        months: int,
        scrape_dir: Path,
        corpus_without: Callable[[Path, List[int]], Path],
        present_spans: Callable[[Path, str], set],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # A four month run that died partway leaves only the newest spans. Counting back
        # from the newest file would conclude one month was needed and abandon the rest.
        directory = corpus_without(scrape_dir, [3, 4])
        scraper = build_scraper(subreddit, months, directory, force=False)

        assert DateTime.get_month_st(n=3) in scraper._needed_spans
        assert DateTime.get_month_st(n=4) in scraper._needed_spans
        assert DateTime.get_month_st(n=1) in scraper._needed_spans

        # The month that completed before the abort must not be refetched.
        second = DateTime.get_month_st(n=2)
        if second in present_spans(directory, subreddit):
            assert second not in scraper._needed_spans
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_interior_gap_is_selected(
        self,
        completed_scrape: RedditScraper,
        subreddit: str,
        months: int,
        scrape_dir: Path,
        corpus_without: Callable[[Path, List[int]], Path],
        present_spans: Callable[[Path, str], set],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        directory = corpus_without(scrape_dir, [2])
        scraper = build_scraper(subreddit, months, directory, force=False)

        assert DateTime.get_month_st(n=2) in scraper._needed_spans, "the gap was not filled"

        third = DateTime.get_month_st(n=3)
        if third in present_spans(directory, subreddit):
            assert third not in scraper._needed_spans, "a complete span behind the gap was refetched"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_month_left_partial_by_an_earlier_run_is_revisited(
        self,
        completed_scrape: RedditScraper,
        subreddit: str,
        months: int,
        scrape_dir: Path,
        corpus_without: Callable[[Path, List[int]], Path],
        present_spans: Callable[[Path, str], set],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # Without the current month on disk, the newest remaining span is the one an
        # earlier run was working on when it stopped, so it is presumed incomplete.
        directory = corpus_without(scrape_dir, [1])
        scraper = build_scraper(subreddit, months, directory, force=False)

        present = present_spans(directory, subreddit)
        assert DateTime.get_month_st(n=1) in scraper._needed_spans

        if present:
            newest = max(present)
            assert newest in scraper._needed_spans, (
                f"{newest} was left partial by an earlier run and must be revisited"
            )
            for span in present:
                if span != newest:
                    assert span not in scraper._needed_spans
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_force_selects_the_entire_window_regardless_of_disk(
        self,
        completed_scrape: RedditScraper,
        subreddit: str,
        months: int,
        scrape_dir: Path,
        expected_spans: List[str],
        corpus_without: Callable[[Path, List[int]], Path],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        directory = corpus_without(scrape_dir, [])
        scraper = build_scraper(subreddit, months, directory, force=True)

        assert scraper._needed_spans == set(expected_spans)
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_stop_boundary_always_covers_the_requested_window(
        self,
        completed_scrape: RedditScraper,
        subreddit: str,
        months: int,
        scrape_dir: Path,
        corpus_without: Callable[[Path, List[int]], Path],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # Selection decides what is fetched, not the boundary. The boundary must stay at
        # the far edge of the window, or the loop would break out before reaching an
        # older span that selection had marked as needed.
        directory = corpus_without(scrape_dir, [3, 4])
        scraper = build_scraper(subreddit, months, directory, force=False)

        assert scraper._stop_utc == DateTime.get_month_dt(n=months)
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)
