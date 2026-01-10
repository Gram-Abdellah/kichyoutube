import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Use token.json from the repo
if os.path.exists('token.json'):
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
else:
    flow = InstalledAppFlow.from_client_secrets_file('kick_downloader_token.json', SCOPES)
    creds = flow.run_local_server(port=0)
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())

service = build('drive', 'v3', credentials=creds)

# ====== STEP 2: List Videos in a Folder ======

def list_videos_in_folder(folder_id):
    query = f"'{folder_id}' in parents and mimeType contains 'video/' and trashed = false"
    
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, size, createdTime)"
    ).execute()

    files = results.get('files', [])
    return files



def delete_all_videos_in_folder_and_trash(folder_id):
    # Step 1: List all videos in the folder
    videos = list_videos_in_folder(folder_id)
    
    # Step 2: Delete each file
    for video in videos:
        try:
            print(f"Deleting: {video['name']} ({video['id']})")
            service.files().delete(fileId=video['id']).execute()
        except Exception as e:
            print(f"Error deleting {video['name']}: {e}")

    # Step 3: Empty the trash
    try:
        print("Emptying trash...")
        service.files().emptyTrash().execute()
        print("Trash emptied.")
    except Exception as e:
        print(f"Error emptying trash: {e}")