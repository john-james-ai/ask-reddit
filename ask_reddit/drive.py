#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : /ask_reddit/drive.py                                                                #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 29th 2025 12:03:06 am                                                 #
# Modified   : Friday August 29th 2025 05:20:07 am                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
from typing import Any, List, Optional, Union

import logging
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ------------------------------------------------------------------------------------------------ #
# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
# ------------------------------------------------------------------------------------------------ #
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------------------------ #
from typing import Any, List, Optional, Union

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GDriveUploader:
    """
    A class to handle authentication and file uploads to Google Drive.

    This class provides a clean interface for managing the Google Drive API
    service connection and uploading one or more files to a designated folder.
    It handles authentication and token management internally, ensuring the
    service is built only when needed.
    """

    def __init__(
        self,
        token_filepath: Union[str, Path],
        credentials_filepath: Union[str, Path],
        folder_id: Optional[str] = None,
    ) -> None:
        self._folder_id = folder_id
        self._token_filepath = token_filepath
        self._credentials_filepath = credentials_filepath
        self._service = None

    def build_service(self) -> Any:
        """
        Handles authentication and returns a Google Drive API service object.

        Checks for an existing 'token.json', refreshes it if expired, or
        initiates a new OAuth2 flow if it doesn't exist. The built service
        object is stored as a private attribute.

        Returns:
            Any: The authorized and built Google Drive API service object.
        """
        creds = None
        if os.path.exists(self._token_filepath):
            creds = Credentials.from_authorized_user_file(self._token_filepath, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self._credentials_filepath, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self._token_filepath, "w") as token:
                token.write(creds.to_json())
        try:
            self._service = build("drive", "v3", credentials=creds)
            return self._service
        except Exception as e:
            # Re-raising the exception is a better practice for larger applications:
            msg = f"Exception occurred while building Google Drive service.\n{e}"
            logger.error(msg)
            raise

    def upload(self, filepaths: Union[str, List]) -> None:
        """
        Uploads a file or list of files to the designated Google Drive folder.

        The method handles the core upload logic, including type-checking the
        input and handling per-file errors gracefully. It ensures the API service
        is built only once for the lifetime of the object.

        Args:
            filepaths (Union[str, List]): A list of filepaths or a string for
                a single filepath to be uploaded to Google Drive.
        """
        if self._service is None:
            self.build_service()

        # Corrects the bug: ensures filepaths is always a list of strings
        if isinstance(filepaths, str):
            filepaths = [filepaths]

        for filepath in filepaths:
            filename = os.path.basename(filepath)
            file_metadata = {
                "name": filename,
                "parents": [self._folder_id] if self._folder_id else [],
            }
            try:
                media = MediaFileUpload(filepath, mimetype="application/json")
                file = (
                    self._service.files()  # type: ignore[]
                    .create(body=file_metadata, media_body=media, fields="id")
                    .execute()
                )
                msg = f"File '{filename}' uploaded successfully with File ID: {file.get('id')}"
                logger.info(msg)
                print(msg)
            except Exception as e:
                msg = f"Exception occurred while uploading {filename}.\n{e}"
                logger.error(msg)
                # Corrects the bug: logs the error and continues the loop
                continue
