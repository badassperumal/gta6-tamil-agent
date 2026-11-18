#!/usr/bin/env python3
"""
GTA6 Tamil Agent — complete YouTube upload script (standalone).

This is the exact upload flow the GTA6 Tamil Agent uses for its owner's single
YouTube channel, collected into one runnable file for review.

What it does, in order:
  1. Authenticates with OAuth 2.0 as the channel owner. On first run it opens the
     Google consent screen and then reuses the stored refresh token.
  2. Uploads the video with videos.insert (resumable, 8 MB chunks, automatic retries),
     setting title, description, tags, category, language, privacy, made-for-kids = false
     and the altered/synthetic-content disclosure (containsSyntheticMedia = true,
     because narration uses an AI voice).
  3. Sets the custom thumbnail with thumbnails.set.
  4. Adds the video to a playlist on the owner's channel (playlists.list,
     then playlists.insert if missing, then playlistItems.insert).
  5. Prints the video URL and its processing and privacy status (videos.list).

Scopes requested (minimum needed):
  https://www.googleapis.com/auth/youtube.upload      upload videos
  https://www.googleapis.com/auth/youtube.force-ssl   thumbnails, playlists, comments

Usage:
  pip install google-api-python-client google-auth-oauthlib
  python youtube_upload.py --client-secret client_secret.json \
      --video final.mp4 --thumbnail thumbnail.jpg \
      --title "GTA 6 Tamil — Vice City Secrets" \
      --description "GTA 6 secrets explained in Tamil." \
      --tags "gta 6 tamil,gta vi,tamil gaming" \
      --playlist "GTA 6 Tamil Shorts" --privacy private

Data handling: no data is stored except the OAuth token file (token.json) on the
owner's machine or as an encrypted CI secret. Revoke access any time at
https://myaccount.google.com/permissions
"""
import argparse
import os
import sys
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
RETRIABLE_STATUS = {500, 502, 503, 504}
GAMING_CATEGORY_ID = "20"


def get_credentials(client_secret: str, token_file: str) -> Credentials:
    """OAuth 2.0. CI uses env vars, a local run uses token.json or the browser consent flow."""
    if os.getenv("YT_REFRESH_TOKEN"):
        creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                            client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                            token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
        creds.refresh(Request())
        return creds
    creds = Credentials.from_authorized_user_file(token_file, SCOPES) if os.path.exists(token_file) else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        with open(token_file, "w") as f:
            f.write(creds.to_json())
    return creds


def upload_video(youtube, args) -> str:
    body = {
        "snippet": {
            "title": args.title[:100],
            "description": args.description[:5000],
            "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
            "categoryId": GAMING_CATEGORY_ID,
            "defaultLanguage": "ta",
            "defaultAudioLanguage": "ta",
        },
        "status": {
            "privacyStatus": args.privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,   # AI-generated narration voice
            "embeddable": True,
        },
    }
    media = MediaFileUpload(args.video, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response, retry = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"  uploading… {int(status.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS and retry < 5:
                retry += 1
                wait = 2 ** retry
                print(f"  server error {e.resp.status}, retrying in {wait}s")
                time.sleep(wait)
            else:
                raise
    video_id = response["id"]
    print(f"✔ uploaded: https://youtu.be/{video_id}")
    return video_id


def set_thumbnail(youtube, video_id: str, thumbnail: str):
    youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail, mimetype="image/jpeg")).execute()
    print("✔ thumbnail set")


def add_to_playlist(youtube, video_id: str, playlist_title: str):
    playlist_id, page = None, None
    while not playlist_id:
        r = youtube.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=page).execute()
        playlist_id = next((p["id"] for p in r.get("items", []) if p["snippet"]["title"] == playlist_title), None)
        page = r.get("nextPageToken")
        if not page:
            break
    if not playlist_id:
        p = youtube.playlists().insert(part="snippet,status", body={
            "snippet": {"title": playlist_title, "defaultLanguage": "ta"},
            "status": {"privacyStatus": "public"}}).execute()
        playlist_id = p["id"]
        print(f"✔ created playlist '{playlist_title}'")
    youtube.playlistItems().insert(part="snippet", body={"snippet": {
        "playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
    print(f"✔ added to playlist '{playlist_title}'")


def report_status(youtube, video_id: str):
    v = youtube.videos().list(part="status,processingDetails", id=video_id).execute()["items"][0]
    print(f"✔ privacy: {v['status']['privacyStatus']} · upload status: {v['status']['uploadStatus']}")


def main():
    ap = argparse.ArgumentParser(description="Upload a video to the owner's YouTube channel.")
    ap.add_argument("--client-secret", default="client_secret.json")
    ap.add_argument("--token-file", default="token.json")
    ap.add_argument("--video", required=True)
    ap.add_argument("--thumbnail")
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--playlist")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    args = ap.parse_args()

    youtube = build("youtube", "v3", credentials=get_credentials(args.client_secret, args.token_file),
                    cache_discovery=False)
    video_id = upload_video(youtube, args)
    if args.thumbnail:
        set_thumbnail(youtube, video_id, args.thumbnail)
    if args.playlist:
        add_to_playlist(youtube, video_id, args.playlist)
    report_status(youtube, video_id)


if __name__ == "__main__":
    try:
        main()
    except HttpError as e:
        sys.exit(f"YouTube API error {e.resp.status}: {e}")
