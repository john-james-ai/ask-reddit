#!/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /scraper/constants.py                                                               #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday June 21st 2025 07:42:33 pm                                                 #
# Modified   : Saturday June 21st 2025 07:57:31 pm                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #

from __future__ import annotations

from enum import Enum


# ------------------------------------------------------------------------------------------------ #
class ChunkSpan(Enum):
    """Represents supported time spans for chunking data files.

    This enum associates a simple character identifier (the member's value)
    with a corresponding ``strftime`` format string. This allows for a robust
    way to handle different date-based grouping strategies.

    Members:
        DAY (tuple): Represents daily chunking ('d', '%Y-%m-%d').
        MONTH (tuple): Represents monthly chunking ('m', '%Y-%m').

    Attributes:
        value (str): The short character identifier (e.g., 'd' or 'm').
        fmt (str): The ``strftime`` compatible format string (e.g., '%Y-%m-%d').
    """
    DAY = ("d", "%Y-%m-%d")
    MONTH = ('m', "%Y-%m")

    @classmethod
    def from_value(cls, value: str) -> ChunkSpan:
        """Retrieves an enum member by its character identifier.

        This class method provides a way to look up a `ChunkSpan` member
        using its assigned value (e.g., 'd' or 'm'), acting as a reverse
        lookup factory.

        Args:
            value (str): The character identifier to search for ('d' or 'm').

        Returns:
            ChunkSpan: The matching enum member.

        Raises:
            ValueError: If no member has a matching `value`.
        """
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"No matching {cls.__name__} for value: {value}")

    def __new__(cls, cid: str, fmt: str) -> ChunkSpan:
        """Constructs a new ChunkSpan member with custom attributes."""
        obj = object.__new__(cls)
        obj._value_ = cid
        obj.fmt = fmt
        return obj
