#!/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/persist.py                                                              #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.com                                                           #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Saturday June 21st 2025 02:41:05 pm                                                 #
# Modified   : Wednesday October 1st 2025 11:17:48 pm                                              #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
from typing import Any, Dict, List

import json
import logging
import os
from datetime import datetime

from ask_reddit.constants import DEFAULT_JSON_INDENT

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------------------------ #
class FileManager:
    """Manages reading and writing data to JSON files with a structured naming convention.

    This class handles the creation of file paths and the serialization/deserialization
    of data to and from JSON files. It standardizes filenames based on source,
    topic, a variable span (e.g., a specific month), and an optional timestamp.

    Attributes:
        _source (str): The origin of the data (e.g., 'reddit').
        _topic (str): The specific subject or channel (e.g., 'learnpython').
        _file_location (str): The directory where files will be stored.
        _timestamp (bool): If True, appends the current date to the filename.
    """

    def __init__(
        self, source: str, topic: str, file_location: str = "data", timestamp: bool = True
    ) -> None:
        """Initializes the FileManager with configuration settings."""
        self._source = source
        self._topic = topic
        self._file_location = file_location
        self._timestamp = timestamp
        # Ensure the target directory exists
        os.makedirs(self._file_location, exist_ok=True)

    def read(self, span: str) -> List[Dict[str, Any]]:
        """Reads and parses data from a specified JSON file.

        Constructs the file path using the provided span and reads the entire
        contents of the JSON file into a Python list of dictionaries.

        Args:
            span (str): A specific identifier for the file, typically a
                date string like 'YYYY-MM' or a specific keyword, used to
                uniquely identify the file to be read.

        Returns:
            list: A list of dictionaries containing the data from the JSON file.

        Raises:
            FileNotFoundError: If the file at the constructed path does not exist.
            json.JSONDecodeError: If the file content is not valid JSON.
        """
        filepath = self.create_filepath(span=span)

        with open(filepath, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
            return data

    def write(self, data: list, span: str) -> None:
        """Writes data to a specified JSON file.

        Serializes the provided list of data into a JSON formatted string and
        writes it to a file. The filename is constructed based on the
        instance attributes and the provided span.

        Args:
            data (list): The list of serializable data (e.g., dicts) to write.
            span (str): A specific identifier for the file, typically a
                date string like 'YYYY-MM' or a keyword, used to create the
                filename.
        """
        filepath = self.create_filepath(span=span)

        # Open the file in write mode and save as json
        with open(filepath, "w", encoding="utf-8") as json_file:
            logger.info(f"Saving final data batch for '{span}'.")
            json.dump(data, json_file, indent=DEFAULT_JSON_INDENT, ensure_ascii=False)

    def create_filepath(self, span: str) -> str:
        """Constructs a standardized file path and name.

        Combines the source, topic, span, and an optional timestamp to create
        a descriptive and unique filename. It then joins this filename with the
        base file location directory.

        Args:
            span (str): A specific identifier for the file, such as a
                date string ('YYYY-MM') or a keyword.

        Returns:
            str: The complete, absolute or relative path for the file.
        """
        dt = ""
        # Note: This logic assumes if a timestamp is used for writing,
        # the same logic must be used for reading to find the file.
        # A fixed span like 'YYYY-MM' is often more reliable for reads.
        if self._timestamp:
            dt = datetime.now().strftime("%Y-%m-%d")

        # Filter out the empty string from dt if timestamp is false
        filename_parts = [self._source, self._topic, span, dt]
        filename = "-".join(filter(None, filename_parts)) + ".json"

        filepath = os.path.join(self._file_location, filename)
        return filepath
