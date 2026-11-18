"""Authenticated YouTube Data API v3 + Analytics API clients from a stored refresh token."""
import os

from . import get_logger

log = get_logger("youtube")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

_cache = {}


def _creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    missing = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing YouTube secrets: {', '.join(missing)} (run scripts/get_refresh_token.py)")
    c = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    c.refresh(Request())
    return c


def yt():
    if "yt" not in _cache:
        from googleapiclient.discovery import build
        _cache["yt"] = build("youtube", "v3", credentials=_creds(), cache_discovery=False)
    return _cache["yt"]


def yta():
    if "yta" not in _cache:
        from googleapiclient.discovery import build
        _cache["yta"] = build("youtubeAnalytics", "v2", credentials=_creds(), cache_discovery=False)
    return _cache["yta"]


def my_channel_id() -> str:
    if "cid" not in _cache:
        r = yt().channels().list(part="id", mine=True).execute()
        _cache["cid"] = r["items"][0]["id"]
    return _cache["cid"]
