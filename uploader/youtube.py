"""Upload finished videos to YouTube via the official YouTube Data API v3.

One-time setup:  put the OAuth file from Google Cloud into secrets/client_secret.json, then
    python pipeline/youtube.py auth                     # opens browser once, saves secrets/token.json
Upload:
    python pipeline/youtube.py upload 001_milo_of_croton            # private (default)
    python pipeline/youtube.py upload 001_milo_of_croton --public
    python pipeline/youtube.py upload 001_milo_of_croton --schedule 2026-11-01T17:00:00Z
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parent.parent  # project root
OUTPUT_DIR = ROOT / "output"  # finished videos: <id>.mp4 + <id>.json (title, description, tags)

SECRETS_DIR = ROOT / "secrets"
CLIENT_SECRET = SECRETS_DIR / "client_secret.json"
TOKEN = SECRETS_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
CATEGORY_SPORTS = "17"


def service():
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not CLIENT_SECRET.exists():
            sys.exit(f"Missing {CLIENT_SECRET}. Download the OAuth client JSON from Google Cloud first.")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
    SECRETS_DIR.mkdir(exist_ok=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def channel_info(yt) -> dict:
    items = yt.channels().list(part="snippet,statistics", mine=True).execute().get("items", [])
    if not items:
        sys.exit("This Google account has no YouTube channel yet. Create one at youtube.com first.")
    return items[0]


def upload(video_id: str, privacy: str = "private", publish_at: str | None = None,
           synthetic: bool = True) -> str:
    meta_path = OUTPUT_DIR / f"{video_id}.json"
    video_path = OUTPUT_DIR / f"{video_id}.mp4"
    done_path = OUTPUT_DIR / f"{video_id}.uploaded.json"
    if done_path.exists():
        url = json.loads(done_path.read_text(encoding="utf-8"))["url"]
        print(f"Already uploaded: {url}")
        return url

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    status = {
        "privacyStatus": "private" if publish_at else privacy,
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": synthetic,  # YouTube requires disclosure of realistic AI visuals
    }
    if publish_at:
        status["publishAt"] = publish_at
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": meta["description"][:5000],
            "tags": meta["tags"],
            "categoryId": CATEGORY_SPORTS,
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": status,
    }

    yt = service()
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            print(f"   uploading {int(progress.progress() * 100)}%")

    url = f"https://youtu.be/{response['id']}"
    done_path.write_text(json.dumps({"id": response["id"], "url": url, "status": response["status"]},
                                    indent=2), encoding="utf-8")
    print(f"Uploaded: {url}  ({response['status'].get('privacyStatus')})")
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth")
    up = sub.add_parser("upload")
    up.add_argument("video_id")
    up.add_argument("--public", action="store_true")
    up.add_argument("--schedule", help="ISO 8601 UTC time, e.g. 2026-11-01T17:00:00Z")
    args = parser.parse_args()

    if args.cmd == "auth":
        ch = channel_info(service())
        print(f"Authorized for channel: {ch['snippet']['title']} "
              f"({ch['statistics'].get('subscriberCount', '?')} subscribers)")
    else:
        upload(args.video_id, "public" if args.public else "private", args.schedule)


if __name__ == "__main__":
    main()
