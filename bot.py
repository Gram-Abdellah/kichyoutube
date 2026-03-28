import os
import time
import requests
import re
from downloader import cut_and_watermark_kick_video
from list_video_from_drive import list_videos_in_folder , delete_all_videos_in_folder_and_trash
from post_on_youtube import get_drive_service, get_youtube_service, download_file_from_drive, upload_video_to_youtube

TOKEN = os.getenv("BOT_TOKEN")
URL = f"https://api.telegram.org/bot{TOKEN}/"

user_states = {}
user_data = {}

def get_updates(offset=None):
    response = requests.get(URL + "getUpdates", params={"offset": offset})
    return response.json()

def send_message(chat_id, text):
    requests.post(URL + "sendMessage", data={"chat_id": chat_id, "text": text})

def scrape_data(url, start, end, name):
    print(f"Scraping from {url}, start='{start}', end='{end}', name='{name}'")
    cut_and_watermark_kick_video(
        m3u8_url=url,
        start_time=start,
        end_time=end,
        logo_path="./logo/logo.png",
        streamer_name=name,
        font_path="./font/Merriweather.ttf"
    )
    return "✅ Done scraping!"

def is_valid_url(url):
    return url.startswith("http://") or url.startswith("https://")

def is_valid_time_format(value):
    return re.match(r"^\d{2}:\d{2}:\d{2}$", value) is not None

def is_valid_name(name):
    return True


def safe_list_videos(folder_id, retries=5, delay=5):
    for attempt in range(retries):
        try:
            return list_videos_in_folder(folder_id)
        except Exception as e:
            print(f"⚠️ Error listing videos (attempt {attempt+1}):", e)
            time.sleep(delay)
    raise Exception("❌ Failed to list videos after retries.")






# ----- Handle Message -----
def handle_message(chat_id, text):
    state = user_states.get(chat_id)

    if text == "/listvideos":
        user_states[chat_id] = "awaiting_selecting_video"
        user_data[chat_id] = {}

        send_message(chat_id, "📥 Listing videos, please wait...")

        FOLDER_ID = "1gz_hpSSr0f73scjkwAE5XfH1zSrj60sT"
        videos = safe_list_videos(FOLDER_ID)

        if not videos:
            send_message(chat_id, "❌ No videos found in the folder.")
        else:
            user_data[chat_id]["videos"] = videos
            msg = ""
            for idx, file in enumerate(videos, start=1):
                name = file['name']
                file_id = file['id']
                url = f"https://drive.google.com/file/d/{file_id}/view"
                msg += f"{idx}. 🎥 {name}\n🔗 {url}\n"
            msg += f"\n📌 Reply with a number (1–{len(videos)}) to upload that video to YouTube."
            send_message(chat_id, msg)
        return

    elif text == "/scrape":
        user_states[chat_id] = "awaiting_url"
        user_data[chat_id] = {}
        send_message(chat_id, "📥 Please send the URL to scrape:")
        return

    if state == "awaiting_url":
        if is_valid_url(text):
            user_data[chat_id]["url"] = text
            user_states[chat_id] = "awaiting_start"
            send_message(chat_id, "⏱️ Enter the start time (HH:MM:SS):")
        else:
            send_message(chat_id, "❌ Invalid URL format.")

    elif state == "awaiting_start":
        if is_valid_time_format(text):
            user_data[chat_id]["start"] = text
            user_states[chat_id] = "awaiting_end"
            send_message(chat_id, "⏱️ Enter the end time (HH:MM:SS):")
        else:
            send_message(chat_id, "❌ Invalid format. Use HH:MM:SS.")

    elif state == "awaiting_end":
        if is_valid_time_format(text):
            user_data[chat_id]["end"] = text
            user_states[chat_id] = "awaiting_name"
            send_message(chat_id, "💾 Enter a name to save the result:")
        else:
            send_message(chat_id, "❌ Invalid time format.")

    elif state == "awaiting_name":
        if is_valid_name(text):
            user_data[chat_id]["name"] = text
            data = user_data[chat_id]
            send_message(chat_id, f"✅ Scraping from {data['start']} to {data['end']} as {data['name']}")
            result = scrape_data(data["url"], data["start"], data["end"], data["name"])
            time.sleep(5) 
            send_message(chat_id, result)
            user_states.pop(chat_id, None)
            user_data.pop(chat_id, None)
        else:
            send_message(chat_id, "❌ Invalid name.")

    elif state == "awaiting_selecting_video":
        FOLDER_ID = "1gz_hpSSr0f73scjkwAE5XfH1zSrj60sT"
        if text.isdigit():
            idx = int(text) - 1
            videos = user_data[chat_id].get("videos", [])
            if 0 <= idx < len(videos):
                selected_video = videos[idx]
                name = selected_video['name']
                file_id = selected_video['id']
                drive_url = f"https://drive.google.com/file/d/{file_id}/view"
                filename = "downloaded_video.mp4"
                title = name
                desc = f"Auto-uploaded video: {name}"

                send_message(chat_id, f"📤 Downloading and uploading **{title}** to YouTube...")

                drive_service = get_drive_service()
                youtube_service = get_youtube_service()

                try:
                    download_file_from_drive(drive_url, filename, drive_service)
                    upload_video_to_youtube(filename, title, desc, youtube_service)
                    delete_all_videos_in_folder_and_trash(FOLDER_ID)
                    send_message(chat_id, "✅ Video uploaded to YouTube successfully!")
                    send_message(chat_id, "📤 Folder is Empty Now")
                except Exception as e:
                    send_message(chat_id, f"❌ Error uploading video: {str(e)}")

                user_states.pop(chat_id, None)
                user_data.pop(chat_id, None)
            else:
                send_message(chat_id, "❌ Invalid number. Please try again.")
        else:
            send_message(chat_id, "❌ Please send a number to select a video.")

    else:
        send_message(chat_id, "🤖 Send /scrape to scrape a clip or /listvideos to upload from Google Drive.")

# ----- Main Bot Loop -----
def main():
    offset = None
    while True:
        updates = get_updates(offset)
        if "result" in updates:
            for update in updates["result"]:
                if "message" in update and "text" in update["message"]:
                    chat_id = update["message"]["chat"]["id"]
                    text = update["message"]["text"]
                    handle_message(chat_id, text)
                    offset = update["update_id"] + 1
        time.sleep(2)

if __name__ == "__main__":
    main()