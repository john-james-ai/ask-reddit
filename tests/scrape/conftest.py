#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /tests/scrape/conftest.py                                                           #
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
"""Fixtures for the end-to-end scraper integration tests.

These tests hit the live Reddit API. Nothing is mocked or stubbed: the PRAW clients,
`FileManager`, `GenAIModel`, and `Printer` are the real objects the CLI wires together,
constructed through the same factory functions `__main__` uses.

Target subreddit
    r/apljk was chosen by measuring candidates against what actually governs cost and
    coverage. It carries roughly ten submissions per month with the largest thread under
    twenty comments, so a four month scrape is well inside the rate limit. Several spans
    are populated, so a run produces multiple batch files and genuinely exercises the
    span boundary, span selection, and the timestamped rescrape path.

    A quiet month may legitimately have no submissions, in which case no file is written
    for it. Assertions therefore check invariants against the spans that actually exist
    rather than assuming every month in the window produced one.

Cost and isolation
    Every scrape writes into a module scoped temporary directory, so the project's
    `data/` tree is never touched and each test module starts from an empty corpus. The
    full scrape is performed once per module and shared by the assertions that inspect
    it, rather than re-scraping per test.

Token counting
    `GenAIModel` is real and calls the Gemini API. A missing or rejected key makes
    `count_tokens` log an error and report a floor of zero rather than raising, so the
    scrape still completes. The assertions therefore treat a zero token count as
    acceptable and never require the Gemini key to be present.
"""
from typing import Any, Callable, Dict, List

import json
import re
import shutil
from pathlib import Path

import pytest

from ask_reddit.date import DateTime
from ask_reddit.persist import FileManager

# ------------------------------------------------------------------------------------------------ #
# pylint: disable=missing-class-docstring, redefined-outer-name
# mypy: ignore-errors
# ------------------------------------------------------------------------------------------------ #

SUBMISSION_ID_PATTERN = re.compile(r"^t3_[a-z0-9]+$")
COMMENT_ID_PATTERN = re.compile(r"^t1_[a-z0-9]+$")
SUBMISSION_KEYS = {"submission_id", "title", "author", "selftext", "comments"}
COMMENT_KEYS = {"comment_id", "author", "body"}


# ------------------------------------------------------------------------------------------------ #
#                                        JOB PARAMETERS                                            #
# ------------------------------------------------------------------------------------------------ #
@pytest.fixture(scope="module")
def subreddit() -> str:
    """Returns the low traffic subreddit used for the integration scrapes."""
    return "apljk"


@pytest.fixture(scope="module")
def months() -> int:
    """Returns the month count under test.

    Four gives room to place a gap in the middle of the window and to simulate a run
    that aborted partway, neither of which two spans can express.
    """
    return 4


@pytest.fixture(scope="module")
def expected_spans(months: int) -> List[str]:
    """Returns the span labels a full scrape should produce, newest first."""
    return [DateTime.get_month_st(n) for n in range(1, months + 1)]


@pytest.fixture(scope="module")
def scrape_dir(tmp_path_factory) -> Path:
    """Returns an empty module scoped directory for scraped output."""
    return tmp_path_factory.mktemp("scrape")


# ------------------------------------------------------------------------------------------------ #
#                                         FILE HELPERS                                             #
# ------------------------------------------------------------------------------------------------ #
@pytest.fixture
def base_span_files() -> Callable[[Path, str], List[Path]]:
    """Returns a callable listing the base span files written for a topic.

    Timestamped rescrape siblings are excluded, so the result is one path per span.

    Returns:
        Callable[[Path, str], List[Path]]: Function taking the output directory and the
            topic, returning the sorted base span files.
    """

    def _base_span_files(directory: Path, topic: str) -> List[Path]:
        pattern = re.compile(rf"^reddit-{re.escape(topic.lower())}-\d{{4}}-\d{{2}}\.json$")
        found = (directory / topic.lower()).glob("*.json")
        return sorted(path for path in found if pattern.match(path.name))

    return _base_span_files


@pytest.fixture
def all_span_files() -> Callable[[Path, str], List[Path]]:
    """Returns a callable listing every JSON file written for a topic, siblings included."""

    def _all_span_files(directory: Path, topic: str) -> List[Path]:
        return sorted((directory / topic.lower()).glob("*.json"))

    return _all_span_files


@pytest.fixture
def span_of() -> Callable[[Path], str]:
    """Returns a callable extracting the YYYY-MM span from a batch filename.

    Returns:
        Callable[[Path], str]: Function taking a batch file path and returning its span.
    """

    def _span_of(filepath: Path) -> str:
        match = re.search(r"(\d{4}-\d{2})", filepath.stem)
        assert match, f"no span found in filename: {filepath.name}"
        return match.group(1)

    return _span_of


@pytest.fixture
def load_records() -> Callable[[Path], List[Dict[str, Any]]]:
    """Returns a callable loading and minimally validating one batch file."""

    def _load_records(filepath: Path) -> List[Dict[str, Any]]:
        with open(filepath, "r", encoding="utf-8") as json_file:
            records = json.load(json_file)
        assert isinstance(records, list), f"{filepath.name} is not a JSON array"
        return records

    return _load_records


# ------------------------------------------------------------------------------------------------ #
#                                       SCHEMA ASSERTIONS                                          #
# ------------------------------------------------------------------------------------------------ #
@pytest.fixture
def assert_valid_submission() -> Callable[[Dict[str, Any]], None]:
    """Returns a callable asserting one submission record matches the persisted schema."""

    def _assert_valid_submission(record: Dict[str, Any]) -> None:
        assert isinstance(record, dict), f"record is {type(record).__name__}, expected dict"
        assert set(record) == SUBMISSION_KEYS, f"unexpected keys: {sorted(record)}"

        assert SUBMISSION_ID_PATTERN.match(
            record["submission_id"]
        ), f"malformed submission id: {record['submission_id']!r}"
        assert isinstance(record["title"], str) and record["title"], "title is empty"
        assert isinstance(record["author"], str) and record["author"], "author is empty"
        # selftext is legitimately empty for link posts, so only the type is asserted.
        assert isinstance(record["selftext"], str)
        assert isinstance(record["comments"], list)

        for comment in record["comments"]:
            assert set(comment) == COMMENT_KEYS, f"unexpected comment keys: {sorted(comment)}"
            assert COMMENT_ID_PATTERN.match(
                comment["comment_id"]
            ), f"malformed comment id: {comment['comment_id']!r}"
            # The scraper skips comments lacking either field, so both must be present.
            assert comment["author"], "comment author is empty"
            assert comment["body"], "comment body is empty"

    return _assert_valid_submission


# ------------------------------------------------------------------------------------------------ #
#                                    SPAN SELECTION SCENARIOS                                      #
# ------------------------------------------------------------------------------------------------ #
@pytest.fixture
def present_spans() -> Callable[[Path, str], set]:
    """Returns a callable listing the spans that have a base file in a directory."""

    def _present_spans(directory: Path, topic: str) -> set:
        pattern = re.compile(rf"^reddit-{re.escape(topic.lower())}-(\d{{4}}-\d{{2}})\.json$")
        matches = (pattern.match(path.name) for path in (directory / topic.lower()).glob("*.json"))
        return {match.group(1) for match in matches if match}

    return _present_spans


@pytest.fixture
def corpus_without(tmp_path: Path, subreddit: str) -> Callable[[Path, List[int]], Path]:
    """Returns a callable copying a scraped corpus with given spans removed.

    The corpus is real output from a live scrape; the copy simply loses some of its
    files. That is what an aborted run or a deleted file actually leaves behind, so the
    resulting state is genuine rather than fabricated. Paths are resolved through the
    real `FileManager`, so the naming matches what a scrape would have written.

    Returns:
        Callable[[Path, List[int]], Path]: Function taking the source corpus directory
            and the month counts to remove, returning the modified copy.
    """

    def _corpus_without(source: Path, month_counts: List[int]) -> Path:
        destination = tmp_path / f"corpus_{'_'.join(str(n) for n in month_counts) or 'full'}"
        shutil.copytree(source, destination)

        file_manager = FileManager(
            source="reddit", topic=subreddit, file_location=str(destination)
        )
        for n in month_counts:
            file_manager.create_filepath(span=DateTime.get_month_st(n)).unlink(missing_ok=True)

        return destination

    return _corpus_without
