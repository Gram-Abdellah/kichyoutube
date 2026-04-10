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

FOLDER_ID = "1gz_hpSSr0f73scjkwAE5XfH1zSrj60sT"

user_states = {}
user_data = {}


# =========================================================
# Telegram Helpers
# =========================================================
def get_updates(offset=None):
    try:
        response = requests.get(URL + "getUpdates", params={"offset": offset}, timeout=60)
        return response.json()
    except Exception as e:
        print(f"⚠️ Failed to get updates: {e}")
        return {}


def send_message(chat_id, text):
    try:
        # Telegram has 4096 char limit
        if len(text) > 4000:
            # Split into chunks
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for chunk in chunks:
                requests.post(URL + "sendMessage", data={"chat_id": chat_id, "text": chunk}, timeout=30)
                time.sleep(0.5)
        else:
            requests.post(URL + "sendMessage", data={"chat_id": chat_id, "text": text}, timeout=30)
    except Exception as e:
        print(f"⚠️ Failed to send message: {e}")


# =========================================================
# Scraper with Progress Updates
# =========================================================
def scrape_data(url, start, end, name, chat_id):
    """Run the scraper and return status message. Sends progress to Telegram."""
    print(f"Scraping from {url}, start='{start}', end='{end}', name='{name}'")

    def progress_callback(msg):
        """Send progress updates to Telegram."""
        send_message(chat_id, msg)

    try:
        result = cut_and_watermark_kick_video(
            m3u8_url=url,
            start_time=start,
            end_time=end,
            logo_path="./logo/logo.png",
            streamer_name=name,
            font_path="./font/Merriweather.ttf",
            progress_callback=progress_callback
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


# =========================================================
# Validators
# =========================================================
def is_valid_url(url):
    return url.startswith("http://") or url.startswith("https://")


def is_valid_time_format(value):
    return re.match(r"^\d{2}:\d{2}:\d{2}$", value) is not None


def is_valid_name(name):
    # Allow alphanumeric, spaces, underscores, hyphens
    return len(name.strip()) > 0


# =========================================================
# Drive Helpers
# =========================================================
def safe_list_videos(folder_id, retries=5, delay=5):
    for attempt in range(retries):
        try:
            return list_videos_in_folder(folder_id)
        except Exception as e:
            print(f"⚠️ Error listing videos (attempt {attempt+1}/{retries}):", e)
            if attempt < retries - 1:
                time.sleep(delay)
    raise Exception("Failed to list videos after all retries.")


# =========================================================
# Handle Messages
# =========================================================
def handle_message(chat_id, text):
    state = user_states.get(chat_id)

    # ---- Global Commands (work anytime) ----
    if text == "/start":
        send_message(chat_id,
            "🤖 Welcome to Kick Clipper Bot!\n\n"
            "Available commands:\n"
            "  /scrape - Clip a Kick stream VOD\n"
            "  /listvideos - List & upload videos to YouTube\n"
            "  /cancel - Cancel current operation\n"
            "  /status - Check bot status\n"
            "  /help - Show this message"
        )
        return

    if text == "/help":
        send_message(chat_id,
            "📖 How to use:\n\n"
            "1️⃣ Send /scrape\n"
            "2️⃣ Paste the m3u8 URL\n"
            "3️⃣ Enter start time (HH:MM:SS)\n"
            "4️⃣ Enter end time (HH:MM:SS)\n"
            "5️⃣ Enter streamer name\n"
            "6️⃣ Wait for processing & upload\n\n"
            "⏱️ Processing time depends on clip length:\n"
            "  • 1-5 min clip → ~2 min\n"
            "  • 5-30 min clip → ~5 min\n"
            "  • 30 min - 2h → ~15 min\n"
            "  • 2h+ → may take 30+ min\n\n"
            "💡 Tips:\n"
            "  • Use .m3u8 URL from Kick VOD\n"
            "  • For long VODs, only the clip portion is downloaded\n"
            "  • If watermark fails, video uploads without it"
        )
        return

    if text == "/cancel":
        user_states.pop(chat_id, None)
        user_data.pop(chat_id, None)
        send_message(chat_id, "❌ Operation cancelled.")
        return

    if text == "/status":
        import shutil
        try:
            total, used, free = shutil.disk_usage(".")
            free_mb = free // (1024 * 1024)
            send_message(chat_id,
                f"🤖 Bot Status: Running ✅\n"
                f"💾 Disk space free: {free_mb} MB\n"
                f"👤 Active sessions: {len(user_states)}"
            )
        except Exception as e:
            send_message(chat_id, f"🤖 Bot is running. Status check error: {e}")
        return

    # ---- /listvideos Command ----
    if text == "/listvideos":
        user_states[chat_id] = "awaiting_selecting_video"
        user_data[chat_id] = {}

        send_message(chat_id, "📥 Listing videos, please wait...")

        try:
            videos = safe_list_videos(FOLDER_ID)

            if not videos:
                send_message(chat_id, "❌ No videos found in the folder.")
                user_states.pop(chat_id, None)
                user_data.pop(chat_id, None)
            else:
                user_data[chat_id]["videos"] = videos
                msg = "📂 Videos in Google Drive:\n\n"
                for idx, file in enumerate(videos, start=1):
                    name = file['name']
                    file_id = file['id']
                    url = f"https://drive.google.com/file/d/{file_id}/view"
                    msg += f"{idx}. 🎥 {name}\n   🔗 {url}\n\n"
                msg += f"📌 Reply with a number (1–{len(videos)}) to upload to YouTube.\n"
                msg += f"📌 Send /cancel to go back."
                send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"❌ Error listing videos: {str(e)}")
            user_states.pop(chat_id, None)
            user_data.pop(chat_id, None)
        return

    # ---- /scrape Command ----
    if text == "/scrape":
        user_states[chat_id] = "awaiting_url"
        user_data[chat_id] = {}
        send_message(chat_id,
            "📥 Please send the m3u8 URL to scrape.\n\n"
            "💡 You can find this in your browser's Network tab\n"
            "   when playing a Kick VOD (look for .m3u8 files).\n\n"
            "Send /cancel to abort."
        )
        return

    # ---- State Machine: Scraping Flow ----
    if state == "awaiting_url":
        if is_valid_url(text):
            if '.m3u8' not in text and 'manifest' not in text.lower():
                send_message(chat_id,
                    "⚠️ This doesn't look like an m3u8 URL.\n"
                    "Are you sure? Proceeding anyway...\n"
                    "💡 Kick m3u8 URLs usually contain '.m3u8' or 'manifest'"
                )
            user_data[chat_id]["url"] = text
            user_states[chat_id] = "awaiting_start"
            send_message(chat_id, "✅ URL received!\n⏱️ Enter the start time (HH:MM:SS):\n\nExample: 00:05:30")
        else:
            send_message(chat_id, "❌ Invalid URL. Must start with http:// or https://\nTry again or send /cancel")

    elif state == "awaiting_start":
        if is_valid_time_format(text):
            user_data[chat_id]["start"] = text
            user_states[chat_id] = "awaiting_end"
            send_message(chat_id, f"✅ Start time: {text}\n⏱️ Enter the end time (HH:MM:SS):\n\nExample: 00:10:30")
        else:
            send_message(chat_id, "❌ Invalid format. Use HH:MM:SS (e.g., 01:30:00)\nTry again or send /cancel")

    elif state == "awaiting_end":
        if is_valid_time_format(text):
            # Validate end > start
            start = user_data[chat_id]["start"]
            start_parts = list(map(int, start.split(":")))
            end_parts = list(map(int, text.split(":")))
            start_sec = start_parts[0]*3600 + start_parts[1]*60 + start_parts[2]
            end_sec = end_parts[0]*3600 + end_parts[1]*60 + end_parts[2]

            if end_sec <= start_sec:
                send_message(chat_id, f"❌ End time ({text}) must be after start time ({start}).\nTry again.")
                return

            duration_sec = end_sec - start_sec
            duration_str = f"{duration_sec//3600:02d}:{(duration_sec%3600)//60:02d}:{duration_sec%60:02d}"

            user_data[chat_id]["end"] = text
            user_states[chat_id] = "awaiting_name"

            # Estimate processing time
            if duration_sec <= 300:
                est_time = "~2 minutes"
            elif duration_sec <= 1800:
                est_time = "~5-10 minutes"
            elif duration_sec <= 7200:
                est_time = "~15-30 minutes"
            else:
                est_time = "~30+ minutes"

            send_message(chat_id,
                f"✅ End time: {text}\n"
                f"📊 Clip duration: {duration_str}\n"
                f"⏱️ Estimated processing time: {est_time}\n\n"
                f"💾 Enter the streamer/clip name:"
            )
        else:
            send_message(chat_id, "❌ Invalid format. Use HH:MM:SS (e.g., 02:00:00)\nTry again or send /cancel")

    elif state == "awaiting_name":
        if is_valid_name(text):
            user_data[chat_id]["name"] = text.strip()
            data = user_data[chat_id]

            # Calculate duration for summary
            start_parts = list(map(int, data['start'].split(":")))
            end_parts = list(map(int, data['end'].split(":")))
            start_sec = start_parts[0]*3600 + start_parts[1]*60 + start_parts[2]
            end_sec = end_parts[0]*3600 + end_parts[1]*60 + end_parts[2]
            duration_sec = end_sec - start_sec
            duration_str = f"{duration_sec//3600:02d}:{(duration_sec%3600)//60:02d}:{duration_sec%60:02d}"

            summary = (
                f"🎬 Starting scrape:\n\n"
                f"🔗 URL: {data['url'][:80]}...\n"
                f"⏱️ From: {data['start']} → {data['end']} ({duration_str})\n"
                f"📛 Name: {data['name']}\n\n"
                f"⏳ Processing... Please wait.\n"
                f"📢 You'll receive progress updates."
            )
            send_message(chat_id, summary)

            # Run the scraper with progress callback
            result = scrape_data(data["url"], data["start"], data["end"], data["name"], chat_id)
            send_message(chat_id, result)

            user_states.pop(chat_id, None)
            user_data.pop(chat_id, None)
        else:
            send_message(chat_id, "❌ Invalid name. Enter at least 1 character.\nTry again or send /cancel")

    # ---- State Machine: Video Selection Flow ----
    elif state == "awaiting_selecting_video":
        if text.isdigit():
            idx = int(text) - 1
            videos = user_data.get(chat_id, {}).get("videos", [])

            if not videos:
                send_message(chat_id, "❌ Video list expired. Please send /listvideos again.")
                user_states.pop(chat_id, None)
                user_data.pop(chat_id, None)
                return

            if 0 <= idx < len(videos):
                selected_video = videos[idx]
                name = selected_video['name']
                file_id = selected_video['id']
                drive_url = f"https://drive.google.com/file/d/{file_id}/view"
                filename = "downloaded_video.mp4"
                title = name
                desc = f"Auto-uploaded video: {name}"

                send_message(chat_id, f"📤 Downloading '{title}' from Drive...")

                try:
                    drive_service = get_drive_service()
                    youtube_service = get_youtube_service()

                    send_message(chat_id, "📥 Downloading from Google Drive...")
                    download_file_from_drive(drive_url, filename, drive_service)

                    send_message(chat_id, "📤 Uploading to YouTube...")
                    upload_video_to_youtube(filename, title, desc, youtube_service)

                    send_message(chat_id, "🗑️ Cleaning up Drive folder...")
                    delete_all_videos_in_folder_and_trash(FOLDER_ID)

                    send_message(chat_id, "✅ Video uploaded to YouTube successfully!")
                    send_message(chat_id, "📤 Drive folder cleaned.")

                except Exception as e:
                    error_msg = f"❌ Error uploading video:\n{str(e)}\n\n{traceback.format_exc()[-500:]}"
                    send_message(chat_id, error_msg)
                finally:
                    # Clean up local file
                    if os.path.exists(filename):
                        try:
                            os.remove(filename)
                        except:
                            pass

                user_states.pop(chat_id, None)
                user_data.pop(chat_id, None)
            else:
                send_message(chat_id, f"❌ Invalid number. Send 1–{len(videos)} or /cancel.")
        else:
            send_message(chat_id, "❌ Please send a number to select a video, or /cancel to go back.")

    # ---- No Active State ----
    else:
        send_message(chat_id,
            "🤖 I don't understand that command.\n\n"
            "Available commands:\n"
            "  /scrape - Clip a Kick stream\n"
            "  /listvideos - List & upload videos\n"
            "  /status - Check bot status\n"
            "  /help - Show help"
        )


# =========================================================
# Main Bot Loop
# =========================================================
def main():
    if not TOKEN:
        print("❌ BOT_TOKEN not set! Set it as environment variable.")
        return

    print("🤖 Bot started! Waiting for messages...")
    print(f"   Bot URL: {URL}")

    # Test the bot token
    try:
        me = requests.get(URL + "getMe", timeout=10).json()
        if me.get("ok"):
            bot_name = me['result'].get('username', 'unknown')
            print(f"   Bot username: @{bot_name}")
        else:
            print(f"   ⚠️ Bot token might be invalid: {me}")
    except Exception as e:
        print(f"   ⚠️ Could not verify bot token: {e}")

    offset = None
    error_count = 0

    while True:
        try:
            updates = get_updates(offset)

            if "result" in updates:
                error_count = 0  # Reset on success
                for update in updates["result"]:
                    offset = update["update_id"] + 1

                    if "message" in update and "text" in update["message"]:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"]["text"].strip()
                        username = update["message"]["from"].get("username", "unknown")
                        print(f"📩 [{username}] ({chat_id}): {text}")

                        try:
                            handle_message(chat_id, text)
                        except Exception as e:
                            error_msg = f"❌ Bot error:\n{str(e)}\n\n{traceback.format_exc()[-1000:]}"
                            print(error_msg)
                            try:
                                send_message(chat_id, error_msg)
                            except:
                                pass
            else:
                # Check for errors in response
                if "description" in updates:
                    print(f"⚠️ Telegram API error: {updates['description']}")
                    error_count += 1

            if error_count > 10:
                print("❌ Too many consecutive errors, waiting 30 seconds...")
                time.sleep(30)
                error_count = 0

        except KeyboardInterrupt:
            print("\n👋 Bot stopped by user.")
            break
        except Exception as e:
            print(f"⚠️ Main loop error: {e}")
            traceback.print_exc()
            error_count += 1
            time.sleep(5)

        time.sleep(2)


if __name__ == "__main__":
    main()