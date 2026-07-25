#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/constants.py                                                            #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 22nd 2025 02:40:33 pm                                                 #
# Modified   : Wednesday October 1st 2025 11:14:58 pm                                              #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
from __future__ import annotations

# ------------------------------------------------------------------------------------------------ #
DEFAULT_GENAI_MODEL = "gemini-2.5-flash"
DEFAULT_ERROR_TOLERANCE = 5
DEFAULT_CONCURRENCY = 10
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BACKOFF = 2.0
DEFAULT_JSON_INDENT = 2

# Batches are always whole calendar months. This is the single definition of the
# span label used for filenames, resume checks, and batch boundaries.
MONTH_SPAN_FORMAT = "%Y-%m"

# Maximum serialized bytes sent in a single token-count request. Well under the
# API request ceiling, so a large month is counted in several passes.
DEFAULT_TOKEN_COUNT_CHUNK_BYTES = 1_000_000
