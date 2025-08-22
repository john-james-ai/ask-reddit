# type: ignore[attr-defined]
"""A Python scraper using PRAW to extract Reddit comments for NLP and GPT model analysis. This project aims to collect comprehensive comment data from Reddit threads."""

import sys

if sys.version_info >= (3, 8):
    from importlib import metadata as importlib_metadata
else:
    import importlib_metadata


def get_version() -> str:
    try:
        return importlib_metadata.version(__name__)
    except importlib_metadata.PackageNotFoundError:  # pragma: no cover
        return "unknown"


version: str = get_version()
