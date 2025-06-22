#!/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /scraper/model.py                                                                   #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Sunday June 22nd 2025 01:38:28 am                                                   #
# Modified   : Sunday June 22nd 2025 03:33:55 am                                                   #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Encapsulates the Generative AI Model"""
from typing import List

import json
import os

from dotenv import load_dotenv
from google import genai

from scraper.constants import DEFAULT_GENAI_MODEL

# ------------------------------------------------------------------------------------------------ #
load_dotenv()
# ------------------------------------------------------------------------------------------------ #
class GenAIModel:
    """Manages interactions with the Google Generative AI models.

    This class provides a convenient wrapper for accessing various Google Generative AI
    model functionalities, such as token counting. It handles client initialization
    and model selection based on environment variables.
    """
    def __init__(self) -> None:
        api_key = os.getenv("GOOGLE_API_KEY")
        self._model = os.getenv("GENAI_MODEL", DEFAULT_GENAI_MODEL)
        self._client = genai.Client(api_key=api_key)

    def count_tokens(self, data: List) -> int:
        """Counts the number of tokens in the provided data using the configured GenAI model.

        Args:
            data: A list of dictionaries to be tokenized. This data will be
                  serialized to a JSON string before tokenization.

        Returns:
            The total number of tokens in the serialized data as an integer.
        """
        # Serialize the data to be tokenized
        serialized_data = json.dumps(data, indent=DEFAULT_GENAI_MODEL)
        # Count the tokens
        return self._client.models.count_tokens(model=self._model, contents=serialized_data).total_tokens