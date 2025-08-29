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
# Modified   : Friday August 29th 2025 12:53:46 am                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
from typing import Union

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_ID = "RedditAnalysis"


def upload_to_drive(file_path: Union[str, Path], file_name: str, folder_id=None):
    """Uploads a file to Google Drive in a specific folder."""
    creds = None
    folder_id = folder_id or FOLDER_ID
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    try:
        service = build("drive", "v3", credentials=creds)

        file_metadata = {
            "name": file_name,
            # If you have a specific folder, add its ID here
            "parents": [folder_id] if folder_id else [],
        }
        media = MediaFileUpload(file_path, mimetype="application/json")

        file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        print(f"File '{file_name}' uploaded successfully with File ID: {file.get('id')}")
        return file.get("id")

    except Exception as e:
        print(f"An error occurred: {e}")
        return None


# --- How to use it in your main script ---
# 1. After you save your JSON data to a local file...
#    with open('reddit_data.json', 'w') as f:
#        json.dump(data, f)

# 2. Call the upload function.
#    DRIVE_FOLDER_ID = "YOUR_FOLDER_ID_HERE" # Optional, but recommended
#    upload_to_drive('reddit_data.json', 'reddit_data.json', DRIVE_FOLDER_ID)
