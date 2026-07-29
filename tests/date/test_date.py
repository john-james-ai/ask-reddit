#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.3.2                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : test_date.py                                                                        #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday July 25th 2026 12:00:00 pm                                                 #
# Modified   : Wednesday July 29th 2026 02:03:45 am                                                #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Tests for ask.date.DateTime.

Covers all five static methods of the utility:

* ``get_month_dt`` and ``get_month_st``, which convert a month count into the first instant of a
  calendar month and its ``YYYY-MM`` label. These drive the scraper's batch spans, so the tests
  assert timezone awareness, day and time normalization, year rollover, and multi year spans.
* ``format_timedelta``, whose four way conditional is exercised on both sides of the 60, 3600,
  and 86400 second thresholds.
* ``get_minutes`` and ``get_seconds``, covering truncation and the sub second case.

Two characterization tests record how the module currently behaves for negative durations. That
behavior is surprising and is called out in comments at the point of assertion. The tests assert
today's behavior rather than the desirable behavior, because this suite does not modify source.

The system clock is not frozen or patched. Expected months are derived from the independent
``expected_month`` oracle in conftest, and ``month_boundary_guard`` skips any assertion that
straddles a UTC month rollover.
"""
import inspect
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Tuple

import pytest

from ask.date import DateTime

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
    """Logs the start of a test and returns the start time.

    Args:
        cls_name (str): The name of the test class.
        test_name (str): The name of the test method.

    Returns:
        datetime: The moment the test began, for duration reporting.
    """
    start = datetime.now()
    logger.info(
        f"\n\nStarted {cls_name} {test_name} at {start.strftime('%I:%M:%S %p')} on {start.strftime('%m/%d/%Y')}"
    )
    logger.info(double_line)
    return start


# ------------------------------------------------------------------------------------------------ #
def log_end(cls_name: str, test_name: str, start: datetime) -> None:
    """Logs the completion of a test and its duration.

    Args:
        cls_name (str): The name of the test class.
        test_name (str): The name of the test method.
        start (datetime): The value returned by ``log_start``.
    """
    end = datetime.now()
    duration = round((end - start).total_seconds(), 1)
    logger.info(
        f"\n\nCompleted {cls_name} {test_name} in {duration} seconds at {end.strftime('%I:%M:%S %p')} on {end.strftime('%m/%d/%Y')}"
    )
    logger.info(single_line)


# ------------------------------------------------------------------------------------------------ #
#                                        GET MONTH DT                                              #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.date
class TestMonthDatetimeResolution:
    # ============================================================================================ #
    def test_single_count_resolves_to_first_of_current_month(
        self,
        month_count_current: int,
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        result = DateTime.get_month_dt(month_count_current)
        month_boundary_guard(before)

        assert result.year == before.year
        assert result.month == before.month
        assert result.day == 1
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_result_is_normalized_to_midnight(
        self,
        month_counts: List[int],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        for n in month_counts:
            result = DateTime.get_month_dt(n)

            assert result.day == 1, f"n={n} did not land on the first of the month"
            assert result.hour == 0, f"n={n} did not normalize the hour"
            assert result.minute == 0, f"n={n} did not normalize the minute"
            assert result.second == 0, f"n={n} did not normalize the second"
            assert result.microsecond == 0, f"n={n} did not normalize the microsecond"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_result_is_timezone_aware_utc(
        self,
        month_counts: List[int],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        for n in month_counts:
            result = DateTime.get_month_dt(n)

            # A naive datetime here would silently compare wrong against submission timestamps,
            # which PRAW returns as UTC aware values.
            assert result.tzinfo is not None, f"n={n} returned a naive datetime"
            assert result.utcoffset() == timedelta(0), f"n={n} is not at UTC offset zero"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_counts_match_independent_month_walk(
        self,
        month_counts: List[int],
        expected_month: Callable[[int, datetime], Tuple[int, int]],
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        results = {n: DateTime.get_month_dt(n) for n in month_counts}
        month_boundary_guard(before)

        for n, result in results.items():
            want_year, want_month = expected_month(n, before)
            assert result.year == want_year, f"n={n} produced the wrong year"
            assert result.month == want_month, f"n={n} produced the wrong month"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_prior_month_count_steps_back_exactly_one_month(
        self,
        month_count_current: int,
        month_count_prior: int,
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        current = DateTime.get_month_dt(month_count_current)
        prior = DateTime.get_month_dt(month_count_prior)
        month_boundary_guard(before)

        assert prior < current
        # Exactly one calendar month apart, whatever that month's length.
        elapsed_months = (current.year - prior.year) * 12 + (current.month - prior.month)
        assert elapsed_months == 1
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_count_crossing_year_boundary_lands_on_previous_december(
        self,
        month_count_prior_december: int,
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        result = DateTime.get_month_dt(month_count_prior_december)
        month_boundary_guard(before)

        # Stepping back one more month than the current month number always lands on the
        # December preceding the current year, which exercises the divmod year borrow.
        assert result.year == before.year - 1
        assert result.month == 12
        assert result.day == 1
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_multi_year_count_borrows_two_years(
        self,
        month_count_two_years_back: int,
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        result = DateTime.get_month_dt(month_count_two_years_back)
        month_boundary_guard(before)

        assert result.year == before.year - 2
        assert result.month == 12
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_larger_counts_reach_strictly_further_back(
        self,
        month_counts: List[int],
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        results = [DateTime.get_month_dt(n) for n in sorted(month_counts)]
        month_boundary_guard(before)

        # Monotonicity matters: the scraper uses this value as a stop boundary, so a larger
        # month count must never produce a later or equal cutoff.
        for earlier, later in zip(results, results[1:]):
            assert later < earlier
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_repeated_calls_are_stable(
        self,
        month_count_prior: int,
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        first = DateTime.get_month_dt(month_count_prior)
        second = DateTime.get_month_dt(month_count_prior)
        month_boundary_guard(before)

        # Idempotence is what makes the derived filename stable across a run.
        assert first == second
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ------------------------------------------------------------------------------------------------ #
#                                        GET MONTH ST                                              #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.date
class TestMonthStringResolution:
    # ============================================================================================ #
    def test_single_count_returns_current_year_month_label(
        self,
        month_count_current: int,
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        result = DateTime.get_month_st(month_count_current)
        month_boundary_guard(before)

        assert result == f"{before.year:04d}-{before.month:02d}"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_label_is_zero_padded_and_correct_length(
        self,
        month_counts: List[int],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        for n in month_counts:
            result = DateTime.get_month_st(n)

            # The label becomes part of a filename, so the exact shape is load bearing.
            assert len(result) == 7, f"n={n} produced '{result}', expected 7 characters"
            assert result[4] == "-", f"n={n} produced '{result}', expected a hyphen at index 4"

            year_part, month_part = result.split("-")
            assert year_part.isdigit(), f"n={n} produced a non numeric year in '{result}'"
            assert month_part.isdigit(), f"n={n} produced a non numeric month in '{result}'"
            assert len(month_part) == 2, f"n={n} did not zero pad the month in '{result}'"
            assert 1 <= int(month_part) <= 12, f"n={n} produced an out of range month '{result}'"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_label_agrees_with_datetime_for_every_count(
        self,
        month_counts: List[int],
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        pairs = [(DateTime.get_month_st(n), DateTime.get_month_dt(n), n) for n in month_counts]
        month_boundary_guard(before)

        # The two accessors must never disagree; the scraper uses one to name the file and the
        # other to bound the scrape.
        for label, moment, n in pairs:
            assert label == f"{moment.year:04d}-{moment.month:02d}", f"n={n} disagreed"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_label_crossing_year_boundary_reports_previous_december(
        self,
        month_count_prior_december: int,
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        result = DateTime.get_month_st(month_count_prior_december)
        month_boundary_guard(before)

        assert result == f"{before.year - 1:04d}-12"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_labels_sort_chronologically_as_strings(
        self,
        month_counts: List[int],
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        labels = [DateTime.get_month_st(n) for n in sorted(month_counts)]
        month_boundary_guard(before)

        # Zero padding is what makes lexical order match chronological order, which is relied on
        # whenever these labels are sorted as filenames.
        assert labels == sorted(labels, reverse=True)
        assert len(set(labels)) == len(labels)
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ------------------------------------------------------------------------------------------------ #
#                                      FORMAT TIMEDELTA                                            #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.date
class TestDurationFormatting:
    # ============================================================================================ #
    def test_zero_duration_reports_seconds_only(self, td_zero: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.format_timedelta(td=td_zero) == "0 seconds"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_subsecond_duration_truncates_to_zero_seconds(self, td_subsecond: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # int() truncation on total_seconds discards the fractional part entirely.
        assert DateTime.format_timedelta(td=td_subsecond) == "0 seconds"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_under_one_minute_reports_seconds_only(self, td_seconds_only: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.format_timedelta(td=td_seconds_only) == "59 seconds"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_exactly_one_minute_enters_the_minutes_branch(
        self, td_exactly_one_minute: timedelta
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.format_timedelta(td=td_exactly_one_minute) == "1 minutes, 0 seconds"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_just_under_one_hour_stays_in_the_minutes_branch(
        self, td_minutes_only: timedelta
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.format_timedelta(td=td_minutes_only) == "59 minutes, 59 seconds"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_exactly_one_hour_enters_the_hours_branch(
        self, td_exactly_one_hour: timedelta
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.format_timedelta(td=td_exactly_one_hour) == "1 hours, 0 minutes, 0 seconds"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_just_under_one_day_stays_in_the_hours_branch(self, td_hours_only: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.format_timedelta(td=td_hours_only) == "23 hours, 59 minutes, 59 seconds"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_exactly_one_day_enters_the_days_branch(self, td_exactly_one_day: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        result = DateTime.format_timedelta(td=td_exactly_one_day)

        assert result == "1 days, 0 hours, 0 minutes, 0 seconds"
        # The hours component is reported modulo 24, not as the running total of 24.
        assert "24 hours" not in result
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_multi_unit_duration_reports_every_component(self, td_full: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.format_timedelta(td=td_full) == "1 days, 1 hours, 1 minutes, 1 seconds"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_every_branch_boundary_formats_exactly(
        self, td_format_expectations: Dict[int, str]
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        for total_seconds, expected in td_format_expectations.items():
            result = DateTime.format_timedelta(td=timedelta(seconds=total_seconds))
            assert result == expected, f"{total_seconds}s produced '{result}'"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_negative_duration_current_behavior_is_misleading(
        self, td_negative_hour: timedelta
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # Characterization test, not an endorsement. Negative one hour reports "23 hours"
        # because `days = hours // 24` floors to -1 and `hours = hours % 24` then wraps to 23,
        # while the days branch is skipped since -1 is not greater than 0. The scraper only ever
        # passes end - start, so this path is not reached in production. Asserting the current
        # output means any future fix to the source will surface here rather than pass silently.
        assert DateTime.format_timedelta(td=td_negative_hour) == "23 hours, 0 minutes, 0 seconds"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ------------------------------------------------------------------------------------------------ #
#                                         GET MINUTES                                              #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.date
class TestMinuteConversion:
    # ============================================================================================ #
    def test_zero_duration_yields_zero_minutes(self, td_zero: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.get_minutes(td=td_zero) == 0
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_partial_minute_rounds_down(self, td_seconds_only: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.get_minutes(td=td_seconds_only) == 0
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_exact_minute_boundary_counts_one(self, td_exactly_one_minute: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.get_minutes(td=td_exactly_one_minute) == 1
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_hour_and_day_durations_convert_exactly(
        self,
        td_exactly_one_hour: timedelta,
        td_hours_only: timedelta,
        td_exactly_one_day: timedelta,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.get_minutes(td=td_exactly_one_hour) == 60
        assert DateTime.get_minutes(td=td_hours_only) == 1439
        assert DateTime.get_minutes(td=td_exactly_one_day) == 1440
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_subsecond_duration_yields_zero_minutes(self, td_subsecond: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.get_minutes(td=td_subsecond) == 0
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_negative_duration_floors_away_from_zero(
        self, td_negative_ninety_seconds: timedelta
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # Characterization test. Floor division sends -90 seconds to -2 minutes rather than -1,
        # which is the opposite rounding direction from get_seconds. Recorded, not endorsed.
        assert DateTime.get_minutes(td=td_negative_ninety_seconds) == -2
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ------------------------------------------------------------------------------------------------ #
#                                         GET SECONDS                                              #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.date
class TestSecondConversion:
    # ============================================================================================ #
    def test_zero_duration_yields_zero_seconds(self, td_zero: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.get_seconds(td=td_zero) == 0
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_subsecond_duration_truncates_to_zero(self, td_subsecond: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        # This is why callers guard against division by zero on very fast runs.
        assert DateTime.get_seconds(td=td_subsecond) == 0
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_fractional_seconds_truncate_toward_zero(self) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.get_seconds(td=timedelta(seconds=1.9)) == 1
        # Truncation toward zero, unlike the floor division used by get_minutes.
        assert DateTime.get_seconds(td=timedelta(seconds=-1.9)) == -1
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_whole_unit_durations_convert_exactly(
        self,
        td_seconds_only: timedelta,
        td_exactly_one_minute: timedelta,
        td_exactly_one_hour: timedelta,
        td_exactly_one_day: timedelta,
        td_full: timedelta,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.get_seconds(td=td_seconds_only) == 59
        assert DateTime.get_seconds(td=td_exactly_one_minute) == 60
        assert DateTime.get_seconds(td=td_exactly_one_hour) == 3600
        assert DateTime.get_seconds(td=td_exactly_one_day) == 86400
        assert DateTime.get_seconds(td=td_full) == 90061
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_negative_duration_preserves_sign(self, td_negative_hour: timedelta) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        assert DateTime.get_seconds(td=td_negative_hour) == -3600
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)


# ------------------------------------------------------------------------------------------------ #
#                                     CROSS METHOD CONTRACTS                                       #
# ------------------------------------------------------------------------------------------------ #
@pytest.mark.date
class TestCrossMethodConsistency:
    # ============================================================================================ #
    def test_minutes_and_seconds_agree_on_whole_minute_durations(
        self,
        td_exactly_one_minute: timedelta,
        td_exactly_one_hour: timedelta,
        td_exactly_one_day: timedelta,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        for td in (td_exactly_one_minute, td_exactly_one_hour, td_exactly_one_day):
            assert DateTime.get_minutes(td=td) == DateTime.get_seconds(td=td) // 60
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_formatted_components_reconstruct_the_original_duration(
        self,
        td_full: timedelta,
        td_hours_only: timedelta,
        td_minutes_only: timedelta,
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        for td in (td_full, td_hours_only, td_minutes_only):
            formatted = DateTime.format_timedelta(td=td)

            # Parse the rendered components back out and confirm they sum to the input, which
            # verifies the divmod chain rather than just the string shape.
            units = {"days": 86400, "hours": 3600, "minutes": 60, "seconds": 1}
            total = 0
            for part in formatted.split(", "):
                value, unit = part.split(" ")
                total += int(value) * units[unit]

            assert total == DateTime.get_seconds(td=td), f"'{formatted}' did not round trip"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)

    # ============================================================================================ #
    def test_month_accessors_stay_consistent_across_the_full_sweep(
        self,
        month_counts: List[int],
        expected_month: Callable[[int, datetime], Tuple[int, int]],
        month_boundary_guard: Callable[[datetime], None],
    ) -> None:
        start = log_start(self.__class__.__name__, inspect.stack()[0][3])
        # ---------------------------------------------------------------------------------------- #
        before = datetime.now(timezone.utc)
        observed = [(n, DateTime.get_month_dt(n), DateTime.get_month_st(n)) for n in month_counts]
        month_boundary_guard(before)

        for n, moment, label in observed:
            want_year, want_month = expected_month(n, before)
            assert (moment.year, moment.month) == (want_year, want_month), f"n={n} datetime"
            assert label == f"{want_year:04d}-{want_month:02d}", f"n={n} label"
        # ---------------------------------------------------------------------------------------- #
        log_end(self.__class__.__name__, inspect.stack()[0][3], start)
