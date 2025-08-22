#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/monitor.py                                                              #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 22nd 2025 02:40:33 pm                                                 #
# Modified   : Friday August 22nd 2025 03:56:59 pm                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Module responsible for resilience of the Scraper"""

from typing import Dict

import logging
import time
from enum import Enum

from ask_reddit.constants import (
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_HALF_OPEN_FACTOR,
    DEFAULT_OPEN_FACTOR,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    DEFAULT_SUCCESS_THRESHOLD,
)

# ------------------------------------------------------------------------------------------------ #


class CircuitState(Enum):
    OPEN = "o"
    HALF = "h"
    CLOSED = "c"


# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------------------------ #
class CircuitBreaker:
    def __init__(
        self,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        open_factor: int = DEFAULT_OPEN_FACTOR,
        half_open_factor: int = DEFAULT_HALF_OPEN_FACTOR,
        success_threshold: int = DEFAULT_SUCCESS_THRESHOLD,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    ) -> None:
        self._delay = 60 / rate_limit_per_minute
        self._open_delay = self._delay * open_factor
        self._half_open_delay = self._delay * half_open_factor
        self._success_threshold = success_threshold
        self._failure_threshold = failure_threshold
        self._n_successes = 0
        self._n_failures = 0
        self._current_state = CircuitState.CLOSED

    def success(self) -> None:
        self._n_successes += 1
        self._n_failures = 0
        if self._current_state == CircuitState.HALF:
            if self._n_successes > self._success_threshold:
                logger.info(f"Encountered {self._n_successes} successes in a row. Closing circuit.")
                self._current_state = CircuitState.CLOSED
        elif self._current_state == CircuitState.OPEN:
            logger.info(
                f"Encountered a success in Open state. Putting circuit in half-closed state."
            )
            self._current_state = CircuitState.HALF
        self.delay()

    def failure(self, context: Dict) -> None:
        logging.info(f"Encountered a failure at {context}")
        self._n_successes = 0
        self._n_failures += 1
        if self._current_state == CircuitState.CLOSED:
            if self._n_failures > self._failure_threshold:
                logger.info(
                    f"Exceeded failure threshold of {self._failure_threshold} failures. Opening the circuit."
                )
                self._current_state = CircuitState.OPEN
        elif self._current_state == CircuitState.HALF:
            logger.info(f"Failure encountered in half-open state. Opening the circuit.")
            self._current_state = CircuitState.OPEN
        else:
            logger.info(f"Changing the circuit from Open to Half-Open state.")
            self._current_state = CircuitState.HALF

        self.delay()

    def delay(self) -> None:
        if self._current_state == CircuitState.OPEN:
            time.sleep(self._open_delay)
        elif self._current_state == CircuitState.HALF:
            time.sleep(self._half_open_delay)
        else:
            time.sleep(self._delay)
