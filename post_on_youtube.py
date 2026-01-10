import os
import io
import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive.file']


# ---------- DRIVE AUTH ----------
def get_drive_service():
    # Use token.json from the repo
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file('kick_downloader_token.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token_file:
            token_file.write(creds.to_json())

    return build('drive', 'v3', credentials=creds)

# Scope for YouTube upload

def get_youtube_service():
    creds = None
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    # Use token.json if it exists and is still valid
    if os.path.exists('YTtoken.json'):
        creds = Credentials.from_authorized_user_file('YTtoken.json', SCOPES)

    # If no valid credentials, go through OAuth flow once
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # Refresh token
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'youtube_client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for future runs
        with open('YTtoken.json', 'w') as token_file:
            token_file.write(creds.to_json())

    # Build and return the YouTube service
    return build("youtube", "v3", credentials=creds)

    return build('youtube', 'v3', credentials=creds)

# ---------- DOWNLOAD FROM DRIVE ----------
def download_file_from_drive(file_url, local_filename, drive_service):
    file_id = file_url.split("/d/")[1].split("/")[0]
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.FileIO(local_filename, 'wb')
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()
        print(f"Downloaded {int(status.progress() * 100)}%")
    fh.close()

# ---------- UPLOAD TO YOUTUBE ----------
def upload_video_to_youtube(file_path, title, description, youtube_service):
    body = {
        'snippet': {
            'title': title,
            'description': description,
        },
        'status': {
            'privacyStatus': 'private',
        }
    }

    media = MediaFileUpload(file_path, mimetype='video/*', resumable=True)
    request = youtube_service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print("✅ Uploaded to YouTube:", response['id'])
    return response['id']

"""# ---------- MAIN ----------
if __name__ == "__main__":
    drive_url = input("🔗 Enter Google Drive File URL: ")
    filename = "downloaded_video.mp4"
    title = input("📺 Enter YouTube video title: ")
    desc = input("📝 Enter YouTube video description: ")

    drive_service = get_drive_service()
    youtube_service = get_youtube_service()

    download_file_from_drive(drive_url, filename, drive_service)
    upload_video_to_youtube(filename, title, desc, youtube_service)"""