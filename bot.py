import os
import time
import requests
import re
import traceback
from downloader import cut_and_watermark_kick_video
from list_video_from_drive import list_videos_in_folder, delete_all_videos_in_folder_and_trash
from post_on_youtube import get_drive_service, get_youtube_service, download_file_from_drive, upload_video_to_youtube

TOKEN = os.getenv("BOT_TOKEN")
URL = f"https://api.telegram.org/bot{TOKEN}/"

user_states = {}
user_data = {}


def get_updates(offset=None):
    try:
        response = requests.get(URL + "getUpdates", params={"offset": offset}, timeout=30)
        return response.json()
    except Exception as e:
        print(f"⚠️ Failed to get updates: {e}")
        return {}


def send_message(chat_id, text):
    try:
        # Telegram has 4096 char limit, split if needed
        if len(text) > 4000:
            text = text[:2000] + "\n...\n" + text[-2000:]
        requests.post(URL + "sendMessage", data={"chat_id": chat_id, "text": text}, timeout=30)
    except Exception as e:
        print(f"⚠️ Failed to send message: {e}")


def scrape_data(url, start, end, name, chat_id):
    """Run the scraper and return status message. Sends progress to Telegram."""
    print(f"Scraping from {url}, start='{start}', end='{end}', name='{name}'")
    
    try:
        send_message(chat_id, "📋 Step 1: Parsing m3u8 playlist...")
        
        result = cut_and_watermark_kick_video(
            m3u8_url=url,
            start_time=start,
            end_time=end,
            logo_path="./logo/logo.png",
            streamer_name=name,
            font_path="./font/Merriweather.ttf"
        )
        
        if result is True:
            return "✅ Done! Video scraped, edited, and uploaded to Google Drive!"
        elif isinstance(result, str):
            return f"❌ Scraping failed: {result}"
        else:
            return "❌ Scraping failed: Unknown error (function returned None)"
            
    except Exception as e:
        error_msg = f"❌ Scraping crashed:\n{str(e)}\n\n{traceback.format_exc()[-1000:]}"
        print(error_msg)
        return error_msg


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

    if text == "/start":
        send_message(chat_id, 
            "🤖 Welcome! Available commands:\n"
            "/scrape - Clip a Kick stream\n"
            "/listvideos - List & upload videos to YouTube\n"
            "/cancel - Cancel current operation"
        )
        return

    if text == "/cancel":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        send_message(chat_id, "❌ Operation cancelled.")
        return

    if text == "/listvideos":
        user_states[chat_id] = "awaiting_selecting_video"
        user_data[chat_id] = {}

        send_message(chat_id, "📥 Listing videos, please wait...")

        FOLDER_ID = "1gz_hpSSr0f73scjkwAE5XfH1zSrj60sT"
        try:
            videos = safe_list_videos(FOLDER_ID)

            if not videos:
                send_message(chat_id, "❌ No videos found in the folder.")
                user_states.pop(chat_id, None)
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
        except Exception as e:
            send_message(chat_id, f"❌ Error listing videos: {str(e)}")
            user_states.pop(chat_id, None)
        return

    elif text == "/scrape":
        user_states[chat_id] = "awaiting_url"
        user_data[chat_id] = {}
        send_message(chat_id, "📥 Please send the m3u8 URL to scrape:")
        return

    if state == "awaiting_url":
        if is_valid_url(text):
            user_data[chat_id]["url"] = text
            user_states[chat_id] = "awaiting_start"
            send_message(chat_id, "✅ URL received!\n⏱️ Enter the start time (HH:MM:SS):")
        else:
            send_message(chat_id, "❌ Invalid URL format. Must start with http:// or https://")

    elif state == "awaiting_start":
        if is_valid_time_format(text):
            user_data[chat_id]["start"] = text
            user_states[chat_id] = "awaiting_end"
            send_message(chat_id, f"✅ Start time: {text}\n⏱️ Enter the end time (HH:MM:SS):")
        else:
            send_message(chat_id, "❌ Invalid format. Use HH:MM:SS (e.g., 00:01:30)")

    elif state == "awaiting_end":
        if is_valid_time_format(text):
            user_data[chat_id]["end"] = text
            user_states[chat_id] = "awaiting_name"
            send_message(chat_id, f"✅ End time: {text}\n💾 Enter the streamer/clip name:")
        else:
            send_message(chat_id, "❌ Invalid time format. Use HH:MM:SS")

    elif state == "awaiting_name":
        if is_valid_name(text):
            user_data[chat_id]["name"] = text
            data = user_data[chat_id]
            
            # Show summary before starting
            summary = (
                f"🎬 Starting scrape:\n"
                f"🔗 URL: {data['url'][:80]}...\n"
                f"⏱️ From: {data['start']} → {data['end']}\n"
                f"📛 Name: {data['name']}\n"
                f"⏳ Please wait..."
            )
            send_message(chat_id, summary)
            
            # Run the scraper with error reporting
            result = scrape_data(data["url"], data["start"], data["end"], data["name"], chat_id)
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

                send_message(chat_id, f"📤 Downloading and uploading '{title}' to YouTube...")

                try:
                    drive_service = get_drive_service()
                    youtube_service = get_youtube_service()
                    download_file_from_drive(drive_url, filename, drive_service)
                    upload_video_to_youtube(filename, title, desc, youtube_service)
                    delete_all_videos_in_folder_and_trash(FOLDER_ID)
                    send_message(chat_id, "✅ Video uploaded to YouTube successfully!")
                    send_message(chat_id, "📤 Folder is Empty Now")
                except Exception as e:
                    error_msg = f"❌ Error uploading video:\n{str(e)}\n\n{traceback.format_exc()[-500:]}"
                    send_message(chat_id, error_msg)

                user_states.pop(chat_id, None)
                user_data.pop(chat_id, None)
            else:
                send_message(chat_id, f"❌ Invalid number. Send 1–{len(videos)}.")
        else:
            send_message(chat_id, "❌ Please send a number to select a video.")

    else:
        send_message(chat_id, "🤖 Send /scrape to clip a stream or /listvideos to upload from Drive.")


# ----- Main Bot Loop -----
def main():
    print("🤖 Bot started! Waiting for messages...")
    offset = None
    while True:
        try:
            updates = get_updates(offset)
            if "result" in updates:
                for update in updates["result"]:
                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"].strip()
                        print(f"📩 Message from {chat_id}: {text}")
                        try:
                            handle_message(chat_id, text)
                        except Exception as e:
                            error_msg = f"❌ Bot error:\n{str(e)}\n\n{traceback.format_exc()[-1000:]}"
                            print(error_msg)
                            send_message(chat_id, error_msg)
                    offset = update["update_id"] + 1
        except Exception as e:
            print(f"⚠️ Main loop error: {e}")
            time.sleep(5)
        time.sleep(2)


if __name__ == "__main__":
    main()