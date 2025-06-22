#!/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /scraper/date.py                                                                    #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Sunday June 22nd 2025 02:09:39 am                                                   #
# Modified   : Sunday June 22nd 2025 04:25:20 am                                                   #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Date Utilities"""
from datetime import timedelta


# ------------------------------------------------------------------------------------------------ #
class DateTime:

    @staticmethod
    def format_timedelta(td: timedelta) -> str:
        """Formats a timedelta object into a string with days, hours, minutes, and seconds."""
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        days = hours // 24 # Calculate days from total hours
        hours = hours % 24 # Get remaining hours after calculating days
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
        return td.total_seconds() // 60

    @staticmethod
    def get_seconds(td: timedelta) -> int:
        """Returns the total number of seconds in a timedelta object. """
        return td.total_seconds()


