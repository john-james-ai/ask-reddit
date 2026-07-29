#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : date.py                                                                             #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 22nd 2025 02:40:33 pm                                                 #
# Modified   : Wednesday July 29th 2026 12:15:57 am                                                #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Date Utilities"""

from datetime import datetime, timedelta, timezone

from ask.constants import MONTH_SPAN_FORMAT


# ------------------------------------------------------------------------------------------------ #
class DateTime:

    @staticmethod
    def get_month_dt(n: int) -> datetime:
        """Returns the UTC datetime for the 1st of the month, n-1 months back.

        Args:
            n (int): The number of months in the span, counting the current month.
                n=1 returns the 1st of the current month.

        Returns:
            datetime: Midnight, UTC, on the 1st of the target month.
        """
        now = datetime.now(timezone.utc)
        # Convert to an absolute month index so the subtraction handles year rollover.
        month_index = now.year * 12 + (now.month - 1) - (n - 1)
        year, month = divmod(month_index, 12)
        return datetime(year, month + 1, 1, tzinfo=timezone.utc)

    @staticmethod
    def get_month_st(n: int) -> str:
        """Returns the 'YYYY-MM' string for the month n-1 months back.

        Args:
            n (int): The number of months in the span, counting the current month.
                n=1 returns the current 'YYYY-MM'.

        Returns:
            str: The target month formatted as 'YYYY-MM'.
        """
        return DateTime.get_month_dt(n).strftime(MONTH_SPAN_FORMAT)

    @staticmethod
    def format_timedelta(td: timedelta) -> str:
        """Formats a timedelta object into a string with days, hours, minutes, and seconds."""
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        days = hours // 24  # Calculate days from total hours
        hours = hours % 24  # Get remaining hours after calculating days
        if days > 0:
            return f"{days} days, {hours} hours, {minutes} minutes, {seconds} seconds"
        elif hours > 0:
            return f"{hours} hours, {minutes} minutes, {seconds} seconds"
        elif minutes > 0:
            return f"{minutes} minutes, {seconds} seconds"
        else:
            return f"{seconds} seconds"

    @staticmethod
    def get_minutes(td: timedelta) -> int:
        """Returns the number of minutes in a timedelta object."""
        return int(td.total_seconds() // 60)

    @staticmethod
    def get_seconds(td: timedelta) -> int:
        """Returns the total number of seconds in a timedelta object."""
        return int(td.total_seconds())
