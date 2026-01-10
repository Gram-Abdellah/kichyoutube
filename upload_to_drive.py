import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive.file']
FOLDER_NAME = 'kick_streaming'

def upload_to_drive(file_path, upload_name=None):
    # Use token.json from the repo
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file('kick_downloader_token.json', SCOPES)
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
