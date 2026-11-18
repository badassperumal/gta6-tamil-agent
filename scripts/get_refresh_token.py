"""Run ONCE on your own computer to authorise the agent to manage your YouTube channel.

  pip install google-auth-oauthlib
  python scripts/get_refresh_token.py path/to/client_secret.json

Then paste the three printed values into GitHub → Settings → Secrets and variables → Actions.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

if len(sys.argv) < 2:
    sys.exit("usage: python scripts/get_refresh_token.py client_secret.json")

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(sys.argv[1]))
client = info.get("installed") or info.get("web")
print("\n✅ Add these as GitHub repository secrets:\n")
print("YT_CLIENT_ID     =", client["client_id"])
print("YT_CLIENT_SECRET =", client["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)
print("\nIMPORTANT: your OAuth consent screen must be 'In production' (not 'Testing'),"
      " otherwise this refresh token expires after 7 days and uploads stop.")
