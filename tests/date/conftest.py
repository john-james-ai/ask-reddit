#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /tests/date/conftest.py                                                             #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday July 25th 2026 12:00:00 pm                                                 #
# Modified   : Saturday July 25th 2026 12:00:00 pm                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Fixtures for the DateTime utility tests.

Characteristics of the module under test that shape these fixtures:

* ``DateTime`` is stateless. Every member is a ``staticmethod`` and nothing is persisted, so
  there is no repository, no cleanup, and no teardown to perform.
* ``get_month_dt`` and ``get_month_st`` read the wall clock through ``datetime.now``. The clock
  is deliberately not frozen or patched, so the expected value is derived by an independent
  reference implementation (``expected_month``) that walks months backwards one at a time. That
  algorithm is intentionally different from the absolute-month-index arithmetic used by the
  source, so agreement between the two is meaningful rather than tautological.
* Because the clock is live, a test that samples the clock and then calls the module can in
  principle straddle a UTC month boundary. ``month_boundary_guard`` detects that and skips
  rather than producing a spurious failure.
* ``format_timedelta``, ``get_minutes``, and ``get_seconds`` are pure functions of a
  ``timedelta``. Their fixtures are plain boundary values chosen to land on each side of the
  60 second, 3600 second, and 86400 second thresholds that select the output branches.
"""
from typing import Callable, Dict, List, Tuple

from datetime import datetime, timedelta, timezone

import pytest

# ------------------------------------------------------------------------------------------------ #
# pylint: disable=missing-class-docstring, redefined-outer-name
# mypy: ignore-errors
# ------------------------------------------------------------------------------------------------ #


# ------------------------------------------------------------------------------------------------ #
#                                    CLOCK AND MONTH FIXTURES                                      #
# ------------------------------------------------------------------------------------------------ #
@pytest.fixture
def now_utc() -> datetime:
    """Returns the current timezone aware UTC datetime, sampled once per test."""
    return datetime.now(timezone.utc)


@pytest.fixture
def expected_month() -> Callable[[int, datetime], Tuple[int, int]]:
    """Returns an independent reference implementation of the month calculation.

    The returned callable walks backwards one month at a time rather than using the absolute
    month index arithmetic of the source, so it serves as a genuine oracle.

    Returns:
        Callable[[int, datetime], Tuple[int, int]]: A function taking the month count ``n`` and
            a reference datetime, and returning the expected ``(year, month)`` pair.
    """

    def _expected_month(n: int, now: datetime) -> Tuple[int, int]:
        year, month = now.year, now.month
        for _ in range(n - 1):
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        return year, month

    return _expected_month


@pytest.fixture
def month_boundary_guard() -> Callable[[datetime], None]:
    """Returns a callable that skips the test if the UTC month rolled over mid test.

    Returns:
        Callable[[datetime], None]: A function taking the datetime sampled before the call under
            test, which skips the test when the UTC month has since changed.
    """

    def _guard(before: datetime) -> None:
        after = datetime.now(timezone.utc)
        if (before.year, before.month) != (after.year, after.month):
            pytest.skip("UTC month rolled over mid test; clock dependent assertion skipped.")

    return _guard


@pytest.fixture
def month_counts() -> List[int]:
    """Returns a sweep of month counts covering same year, year rollover, and multi year spans."""
    return [1, 2, 3, 6, 12, 13, 24, 25, 37]


@pytest.fixture
def month_count_current() -> int:
    """Returns the month count that designates the current month."""
    return 1


@pytest.fixture
def month_count_prior() -> int:
    """Returns the month count that designates the immediately preceding month."""
    return 2


@pytest.fixture
def month_count_prior_december(now_utc: datetime) -> int:
    """Returns the month count that lands exactly on December of the previous year.

    Going back ``n - 1`` months from the current month reaches December of the previous year
    when ``n - 1`` equals the current month number, so this is derived from the live clock and
    holds no matter which month the suite runs in.
    """
    return now_utc.month + 1


@pytest.fixture
def month_count_two_years_back(now_utc: datetime) -> int:
    """Returns the month count that lands on December two years before the current year."""
    return now_utc.month + 13


# ------------------------------------------------------------------------------------------------ #
#                                      TIMEDELTA FIXTURES                                          #
# ------------------------------------------------------------------------------------------------ #
@pytest.fixture
def td_zero() -> timedelta:
    """Returns a zero length duration, the lower boundary of the seconds branch."""
    return timedelta(seconds=0)


@pytest.fixture
def td_subsecond() -> timedelta:
    """Returns a sub second duration, which truncates to zero whole seconds."""
    return timedelta(milliseconds=500)


@pytest.fixture
def td_seconds_only() -> timedelta:
    """Returns 59 seconds, the upper boundary of the seconds branch."""
    return timedelta(seconds=59)


@pytest.fixture
def td_exactly_one_minute() -> timedelta:
    """Returns exactly 60 seconds, the lower boundary of the minutes branch."""
    return timedelta(seconds=60)


@pytest.fixture
def td_minutes_only() -> timedelta:
    """Returns 3599 seconds, the upper boundary of the minutes branch."""
    return timedelta(seconds=3599)


@pytest.fixture
def td_exactly_one_hour() -> timedelta:
    """Returns exactly 3600 seconds, the lower boundary of the hours branch."""
    return timedelta(seconds=3600)


@pytest.fixture
def td_hours_only() -> timedelta:
    """Returns 86399 seconds, the upper boundary of the hours branch."""
    return timedelta(seconds=86399)


@pytest.fixture
def td_exactly_one_day() -> timedelta:
    """Returns exactly 86400 seconds, the lower boundary of the days branch."""
    return timedelta(seconds=86400)


@pytest.fixture
def td_full() -> timedelta:
    """Returns a duration exercising every unit at once: 1 day, 1 hour, 1 minute, 1 second."""
    return timedelta(seconds=90061)


@pytest.fixture
def td_negative_hour() -> timedelta:
    """Returns a negative one hour duration, used to characterize negative input handling."""
    return timedelta(seconds=-3600)


@pytest.fixture
def td_negative_ninety_seconds() -> timedelta:
    """Returns a negative ninety second duration, used to characterize floor division."""
    return timedelta(seconds=-90)


@pytest.fixture
def td_format_expectations() -> Dict[int, str]:
    """Returns a mapping of total seconds to the exact expected ``format_timedelta`` output.

    Every entry sits on a branch boundary of the four way conditional in the source, so the
    mapping as a whole covers each branch and both sides of each threshold.
    """
    return {
        0: "0 seconds",
        59: "59 seconds",
        60: "1 minutes, 0 seconds",
        3599: "59 minutes, 59 seconds",
        3600: "1 hours, 0 minutes, 0 seconds",
        86399: "23 hours, 59 minutes, 59 seconds",
        86400: "1 days, 0 hours, 0 minutes, 0 seconds",
        90061: "1 days, 1 hours, 1 minutes, 1 seconds",
    }
