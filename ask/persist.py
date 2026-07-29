#!/usr/bin/env python3
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Description: Reddit Scraper.                                                                     #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask/persist.py                                                                     #
# Filename   : /ask/persist.py                                                                     #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john@variancexplained.ai                                                            #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Wednesday July 22nd 2026 08:28:57 pm                                                #
# Modified   : Wednesday July 29th 2026 12:15:57 am                                                #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2026 John James                                                                 #
# ================================================================================================ #

"""Persistence helpers for Ask Reddit.

This module provides a small `FileManager` helper used to read and write
JSON files using a consistent filename convention built from a source,
topic, and span identifier.

The module is intentionally small and focused on deterministic file path
construction and JSON serialization; it does not provide database-style
concurrency controls or locking.
"""


import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ask.constants import DEFAULT_JSON_INDENT

# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------------------------ #
class FileManager:
    """Manage reading and writing JSON files using a consistent filename convention.

    The `FileManager` constructs filenames from a `source`, `topic`, and
    `span` identifier and provides helpers to read and write JSON data.

    Args:
        source (str): Origin of the data (for example, 'reddit').
        topic (str): Specific subject or channel (for example, 'learnpython').
        file_location (str): Directory where files will be stored. Defaults to
            ``'data'``.

    Examples:
        >>> fm = FileManager('reddit', 'learnpython', file_location='data')
        >>> fm.create_filepath('2026-07')
        PosixPath('data/reddit-learnpython-2026-07.json')
    """

    def __init__(self, source: str, topic: str, file_location: str = "data") -> None:
        self._source = source
        self._topic = topic
        self._file_location = file_location

    def read(self, span: str) -> List[Dict[str, Any]]:
        """Read and parse JSON data from a file constructed for `span`.

        The filename is created by combining the instance `source`, `topic`,
        and the provided `span` (for example, ``'2026-07'``).

        Nothing is caught here: a missing file raises FileNotFoundError and malformed
        contents raise json.JSONDecodeError, both straight from the standard library. They
        are described here rather than in a Raises section because no raise statement in
        this body produces them.

        Args:
            span (str): Identifier for the file (for example, a date like
                ``'YYYY-MM'``) used to construct the filename.

        Returns:
            List[Dict[str, Any]]: The list of records loaded from the file.
        """
        filepath = self.create_filepath(span=span)

        with open(filepath, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
            return data

    def write(self, data: List[Dict[str, Any]], span: str) -> None:
        """Serialize and write `data` to the JSON file for `span`.

        Args:
            data (List[Dict[str, Any]]): List of serializable records to write.
            span (str): Identifier used to construct the filename (for example,
                a date string like ``'YYYY-MM'``).
        """
        filepath = self.create_filepath(span=span, for_new_file=True)
        os.makedirs(filepath.parent, exist_ok=True)

        # Open the file in write mode and save as json
        with open(filepath, "w", encoding="utf-8") as json_file:
            logger.info(f"Saving final data batch for '{span}'.")
            json.dump(data, json_file, indent=DEFAULT_JSON_INDENT, ensure_ascii=False)

    def exists(self, span: str) -> bool:
        """Check if the JSON file for `span` exists.

        Args:
            span (str): Identifier used to construct the filename (for example,
                a date string like ``'YYYY-MM'``).

        Returns:
            bool: True if the file exists, False otherwise.
        """
        filepath = self.create_filepath(span=span)
        return filepath.exists()

    def get_months_since_last(self) -> Optional[int]:
        """Return the month count of the most recent span already on file.

        The count uses the same 1-based indexing as
        :meth:`ask.date.DateTime.get_month_st`, where 1 is the current
        month, 2 is the month before it, and so on. If today falls in July and
        the most recent span on file is March, the return value is 5.

        Only base span files (``{source}-{topic}-YYYY-MM.json``) are counted.
        Timestamped rescrape siblings are ignored, since one only ever exists
        alongside the base file it was derived from.

        Returns:
            Optional[int]: The month count of the most recent span on file, or
                None when no span files are present.
        """
        prefix = f"{self._source}-{self._topic.lower()}"
        pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{4}})-(\d{{2}})\.json$")

        month_indices = []
        for filepath in Path(self._file_location).glob(f"{self._topic.lower()}/{prefix}-*.json"):
            match = pattern.match(filepath.name)
            if match:
                year, month = int(match.group(1)), int(match.group(2))
                # Absolute month index, so the comparison spans year boundaries.
                month_indices.append(year * 12 + (month - 1))

        if not month_indices:
            return None

        now = datetime.now(timezone.utc)
        elapsed = (now.year * 12 + (now.month - 1)) - max(month_indices)
        # Clamp to the current month: a span dated in the future would otherwise
        # produce a count of zero or less, which is not a valid month count.
        return max(1, elapsed + 1)

    def create_filepath(self, span: str, for_new_file: bool = False) -> Path:
        """Return the `Path` for the JSON file corresponding to `span`.

        The filename returned is ``{source}-{topic}-{span}.json`` (topic is
        lower-cased). Empty parts are filtered out so callers can pass an
        empty span when batching is not used.

        Set `for_new_file` when the caller intends to create a file rather than
        resolve an existing one. The returned path is then guaranteed not to
        name a file that already exists, so nothing previously captured is
        overwritten. Callers that need to locate the original file, such as
        `read` and `exists`, must leave `for_new_file` False.

        Args:
            span (str): Identifier used to form the filename (for example,
                ``'YYYY-MM'``).
            for_new_file (bool): Whether the path is destined for a file that
                does not exist yet. Defaults to False.

        Returns:
            Path: Filesystem path for the JSON file inside `file_location`.
        """

        filename_parts = [self._source, self._topic.lower(), span]
        # Filter out the empty string from filename_parts (if not batching)
        filename = "-".join(filter(None, filename_parts)) + ".json"

        filepath = Path(self._file_location) / self._topic.lower() / filename

        # A rescrape of an in-progress month lands beside the original rather
        # than replacing it, so no previously captured submissions are lost.
        if for_new_file and filepath.exists():
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            filepath = filepath.with_name(f"{filepath.stem}-{stamp}{filepath.suffix}")

        return filepath
