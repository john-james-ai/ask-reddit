#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/model.py                                                                #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 22nd 2025 02:40:33 pm                                                 #
# Modified   : Wednesday October 1st 2025 11:17:13 pm                                              #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Encapsulates the Generative AI Model"""
from typing import Iterator, List, Tuple

import json
import logging
import os

from dotenv import load_dotenv
from google import genai

from ask_reddit.constants import DEFAULT_GENAI_MODEL, DEFAULT_TOKEN_COUNT_CHUNK_BYTES

# ------------------------------------------------------------------------------------------------ #
load_dotenv()
# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------------------------ #
class GenAIModel:
    """Manages interactions with the Google Generative AI models.

    This class provides a convenient wrapper for accessing various Google Generative AI
    model functionalities, such as token counting. It handles client initialization
    and model selection based on environment variables.
    """

    def __init__(self) -> None:
        api_key = os.getenv("GOOGLE_API_KEY")
        self._model_name = os.getenv("GENAI_MODEL", DEFAULT_GENAI_MODEL)
        self._client = genai.Client(api_key=api_key)

    def count_tokens(self, data: List) -> int:
        """Counts the number of tokens in the provided data using the configured GenAI model.

        A month of submissions and comments is far too large to submit as a single
        request, so the records are split into chunks bounded by serialized size and
        counted in several passes. The per-chunk counts are summed.

        A chunk that fails to count is logged with the number of records affected and
        contributes zero, so the returned total is a floor rather than an estimate.
        The failure is never silent.

        Args:
            data: A list of dictionaries to be tokenized. Each record is serialized
                  to JSON before tokenization.

        Returns:
            The total number of tokens across all records. If one or more chunks
            failed, the total covers only the records that were counted.
        """
        total_tokens = 0
        n_uncounted = 0

        for records, serialized in self._chunk(data=data):
            try:
                response_obj = self._client.models.count_tokens(
                    model=self._model_name, contents=serialized
                )
                total_tokens += getattr(response_obj, "total_tokens", 0) or 0
            except Exception as e:
                n_uncounted += len(records)
                logger.error(f"Failed to count tokens for {len(records)} record(s): {e}")

        if n_uncounted:
            logger.error(
                f"Token count is incomplete: {n_uncounted} of {len(data)} record(s) "
                f"could not be counted. Reported total of {total_tokens} is a floor."
            )

        return total_tokens

    def _chunk(self, data: List) -> Iterator[Tuple[List, str]]:
        """Splits records into chunks bounded by serialized size.

        Each record is serialized once and the fragments are joined into a JSON array,
        so no record is serialized twice. A single record larger than the limit is
        yielded on its own rather than dropped.

        Args:
            data: The list of records to split.

        Yields:
            Tuple[List, str]: The records in the chunk, and their serialized JSON.
        """
        max_bytes = int(os.getenv("TOKEN_COUNT_CHUNK_BYTES", DEFAULT_TOKEN_COUNT_CHUNK_BYTES))

        records: List = []
        fragments: List[str] = []
        n_bytes = 0

        for record in data:
            fragment = json.dumps(record)
            fragment_bytes = len(fragment.encode("utf-8"))

            # Close the current chunk before it would exceed the limit, but never
            # emit an empty one: an oversized single record goes out by itself.
            if records and n_bytes + fragment_bytes > max_bytes:
                yield records, f"[{','.join(fragments)}]"
                records, fragments, n_bytes = [], [], 0

            records.append(record)
            fragments.append(fragment)
            n_bytes += fragment_bytes

        if records:
            yield records, f"[{','.join(fragments)}]"
