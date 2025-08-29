#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# ================================================================================================ #
# Project    : Ask Reddit                                                                          #
# Version    : 0.1.0                                                                               #
# Python     : 3.13.5                                                                              #
# Filename   : \ask_reddit\authorization.py                                                        #
# ------------------------------------------------------------------------------------------------ #
# Author     : John James                                                                          #
# Email      : john.james.ai.studio@gmail.com                                                      #
# URL        : https://github.com/john-james-ai/ask-reddit/                                        #
# ------------------------------------------------------------------------------------------------ #
# Created    : Friday August 29th 2025 02:12:37 am                                                 #
# Modified   : Friday August 29th 2025 02:18:41 am                                                 #
# ------------------------------------------------------------------------------------------------ #
# License    : MIT License                                                                         #
# Copyright  : (c) 2025 John James                                                                 #
# ================================================================================================ #
# This canvas now shows a refactored, cleaner approach.
# It's best practice to separate the authentication logic into its own function.
# For clarity, both modules are shown here, but they should be in separate files.

# ===================================================================
# Purpose: Handles Google API authentication and token management.
# ===================================================================
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_credentials():
    """
    Handles user authentication for the Google API.

    Checks for an existing 'token.json', refreshes it if expired, or
    initiates a new OAuth2 flow if it doesn't exist. This function is
    reusable for any script that needs to authenticate.

    Returns:
        google.oauth2.credentials.Credentials: The authorized credentials object.
    """
    creds = None
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

    return creds


# ===================================================================
# Purpose: Run this script ONCE on a machine with a web browser
# to generate the 'token.json' file.
# ===================================================================

# Note: In your actual project, you would uncomment the following line
# because this code would be in a separate file from auth_handler.py.
# from auth_handler import get_credentials

if __name__ == "__main__":
    """
    Calls the dedicated get_credentials function to trigger the
    authentication flow and create the token.json file.
    """
    print("Attempting to authenticate with Google Drive to generate token...")

    # This is the only line needed to trigger the authentication flow.
    creds = get_credentials()

    if creds:
        print("\nAuthentication successful!")
        print("A 'token.json' file should now be present in your directory.")
        print("You can now move this 'token.json' file to your server or WSL2 environment.")
    else:
        print("\nAuthentication failed. Please check your 'credentials.json' file and try again.")
