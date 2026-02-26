import os
import json
import yt_dlp
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ----------------------------
# CONFIG
# ----------------------------

DOWNLOAD_FILE = "temp_video.mp4"

TITLE = "Reupload - My Own Content"
DESCRIPTION = "Reuploaded from my official channel."
TAGS = ["my content", "official"]
CATEGORY_ID = "22"
PRIVACY = "private"

# ----------------------------
# AUTH
# ----------------------------

def get_youtube_service():

    with open("token2.json", "r") as f:
        creds = Credentials.from_authorized_user_info(json.load(f))

    return build("youtube", "v3", credentials=creds)

# ----------------------------
# DOWNLOAD (FROM YOUR CHANNEL)
# ----------------------------

def download_video(url):
    print("📥 Downloading video...")

    ydl_opts = {
        "outtmpl": DOWNLOAD_FILE,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        # Required if private/unlisted
        "cookies": "cookies.txt" if os.path.exists("cookies.txt") else None
    }

    # Remove None values
    ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    print("✅ Download complete")

# ----------------------------
# UPLOAD (TO SECOND CHANNEL)
# ----------------------------

def upload_video():
    print("📺 Uploading to second channel...")

    youtube = get_youtube_service()

    body = {
        "snippet": {
            "title": TITLE,
            "description": DESCRIPTION,
            "tags": TAGS,
            "categoryId": CATEGORY_ID
        },
        "status": {
            "privacyStatus": PRIVACY
        }
    }

    media = MediaFileUpload(
        DOWNLOAD_FILE,
        mimetype="video/mp4",
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = request.execute()
    video_id = response["id"]

    print(f"✅ Uploaded successfully: {video_id}")

    return video_id

# ----------------------------
# MAIN
# ----------------------------

def process_upload(VIDEO_URL):
    try:
        download_video(VIDEO_URL)
        upload_video()

        if os.path.exists(DOWNLOAD_FILE):
            os.remove(DOWNLOAD_FILE)

        print("🎉 Process completed successfully.")

    except Exception as e:
        print("❌ Error:", e)