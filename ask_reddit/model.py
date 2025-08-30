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
# Modified   : Saturday August 30th 2025 02:13:45 pm                                               #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
"""Encapsulates the Generative AI Model"""

from typing import List

import json
import logging

from dotenv import load_dotenv
from google import genai

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

    def __init__(self, api_key: str, model_name: str) -> None:
        self._model_name = model_name
        self._client = genai.Client(api_key=api_key)

    def count_tokens(self, data: List) -> int:
        """Counts the number of tokens in the provided data using the configured GenAI model.

        Args:
            data: A list of dictionaries to be tokenized. This data will be
                  serialized to a JSON string before tokenization.

        Returns:
            The total number of tokens in the serialized data as an integer.
        """
        try:
            # Serialize the data to be tokenized
            serialized_data = json.dumps(data)

            # Get the full response object from the API call
            response_obj = self._client.models.count_tokens(
                model=self._model_name, contents=serialized_data
            )

            # Safely get the token count and return it.
            # If 'total_tokens' doesn't exist for some reason, return 0.
            return getattr(response_obj, "total_tokens", 0)

        except Exception as e:
            # It's good practice to log errors if the API call fails
            logger.error(f"Failed to count tokens: {e}")
            return 0
