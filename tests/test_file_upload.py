#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /tests/test_file_upload.py                                                          #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 29th 2025 04:15:26 am                                                 #
# Modified   : Friday August 29th 2025 05:25:32 am                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
import inspect
import logging
import os
from datetime import datetime

import pytest
from dotenv import load_dotenv

from ask_reddit.drive import GDriveUploader

load_dotenv()
# ------------------------------------------------------------------------------------------------ #
# pylint: disable=missing-class-docstring, line-too-long
# mypy: ignore-errors
# ------------------------------------------------------------------------------------------------ #
# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)
# ------------------------------------------------------------------------------------------------ #
double_line = f"\n{100 * '='}"
single_line = f"\n{100 * '-'}"
FILEPATHS = [
    "data/reddit-outlier_ai-2025-08-2025-08-29.json",
    "data/reddit-outlier_ai-2025-07-2025-08-29.json",
]


@pytest.mark.gdrive
class TestGDriveUpload:  # pragma: no cover
    # ============================================================================================ #
    def test_upload(self, caplog) -> None:
        start = datetime.now()
        logger.info(
            f"\n\nStarted {self.__class__.__name__} {inspect.stack()[0][3]} at {start.strftime('%I:%M:%S %p')} on {start.strftime('%m/%d/%Y')}"
        )
        logger.info(double_line)
        # ---------------------------------------------------------------------------------------- #
        folder_id = os.getenv(f"GOOGLE_DRIVE_FOLDER_ID")
        token_filepath = os.getenv("GOOGLE_TOKENS_JSON_FILEPATH")
        credentials_filepath = os.getenv("GOOGLE_CREDENTIALS_FILEPATH")
        gdrive = GDriveUploader(
            token_filepath=token_filepath,
            credentials_filepath=credentials_filepath,
            folder_id=folder_id,
        )
        gdrive.upload(filepaths=FILEPATHS)

        # ---------------------------------------------------------------------------------------- #
        end = datetime.now()
        duration = round((end - start).total_seconds(), 1)

        logger.info(
            f"\n\nCompleted {self.__class__.__name__} {inspect.stack()[0][3]} in {duration} seconds at {start.strftime('%I:%M:%S %p')} on {start.strftime('%m/%d/%Y')}"
        )
        logger.info(single_line)
