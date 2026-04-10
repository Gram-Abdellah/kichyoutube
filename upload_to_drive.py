import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive.file']
FOLDER_NAME = 'kick_streaming'


def upload_to_drive(file_path, upload_name=None):
    creds = None

    # Load existing token
    if os.path.exists('token.json'):
        print("🔑 Loading token.json...")
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        print("❌ token.json not found!")

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            print("🔄 Token expired, refreshing...")
            creds.refresh(Request())
            with open('token.json', 'w') as token_file:
                token_file.write(creds.to_json())
            print("✅ Token refreshed successfully!")
        except Exception as e:
            print(f"⚠️ Token refresh failed: {e}")
            creds = None

    # If no valid creds and we're on a server (no browser), fail clearly
    if not creds or not creds.valid:
        if os.environ.get("GITHUB_ACTIONS") or not os.environ.get("DISPLAY"):
            raise Exception(
                "Token is invalid/expired and cannot open browser for re-auth. "
                "Please run the bot LOCALLY once to generate a fresh token.json, "
                "then update the GOOGLE_TOKEN secret in GitHub."
            )
        # Only try browser auth if running locally
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token_file:
            token_file.write(creds.to_json())

    service = build('drive', 'v3', credentials=creds)

    # Check if folder exists
    folder_id = None
    query = f"name='{FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    folders = response.get('files', [])

    if folders:
        folder_id = folders[0]['id']
    else:
        folder_metadata = {
            'name': FOLDER_NAME,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        folder_id = folder.get('id')

    # Upload file
    file_metadata = {
        'name': upload_name or os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, resumable=True)
    uploaded_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()

    print(f"✅ Uploaded to Google Drive with ID: {uploaded_file.get('id')}")