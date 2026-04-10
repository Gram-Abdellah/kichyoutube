import subprocess
import os
from datetime import datetime, timedelta
from upload_to_drive import upload_to_drive

def get_overlay_position(position):
    positions = {
        'bottom_left':  "10:H-h-10",
        'bottom_right': "W-w-10:H-h-10",
        'top_left':     "10:10",
        'top_right':    "W-w-10:10",
        'bottom_center':"(W-w)/2:H-h-10",
        'top_center':   "(W-w)/2:10"
    }
    return positions.get(position, "W-w-10:H-h-10")

def escape_text_for_drawtext(text):
    return text.replace(":", r'\:').replace("'", r"\\'")

def hms_to_seconds(hms):
    h, m, s = map(int, hms.split(":"))
    return h * 3600 + m * 60 + s

def seconds_to_hms(seconds):
    return str(timedelta(seconds=seconds))

def cut_and_watermark_kick_video(m3u8_url, start_time, end_time, logo_path="logo.png", streamer_name="MoroccanStreamer123", font_path=""):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_video = f"raw_kick_clip_{timestamp}.mp4"
    final_video = f"{streamer_name}_kick_clip_{timestamp}.mp4"

    # Calculate duration
    start_seconds = hms_to_seconds(start_time)
    end_seconds = hms_to_seconds(end_time)
    duration_seconds = max(0, end_seconds - start_seconds)
    duration = seconds_to_hms(duration_seconds)

    # Step 1: Download and re-encode the clip
    # Step 1: Download and copy the clip (no re-encode needed, Step 2 handles that)
    cut_cmd = [
        "ffmpeg",
        "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "-referer", "https://kick.com/",
        "-multiple_requests", "0",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", m3u8_url,               # Input FIRST
        "-ss", start_time,            # Seek AFTER input
        "-t", duration,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-ignore_unknown",
        "-c:v", "copy",
        "-c:a", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-avoid_negative_ts", "make_zero",   # Fix timestamp issues
        "-y",
        raw_video
    ]

    print(f"🎬 Cutting clip to: {raw_video}")
    try:
        subprocess.run(cut_cmd, check=True)
    except subprocess.CalledProcessError:
        print("❌ Failed to cut video. Check FFmpeg or m3u8 link.")
        return

    # Step 2: Add watermark and scrolling text
    overlay_pos = get_overlay_position("top_left")

    base_message = (
        f"Clip by: {streamer_name} - Follow him on Kick.com and show some support! "
        f"Catch amazing gameplay, reactions, and stories! "
        f"Support the Moroccan streaming scene! "
    )
    repeat_message = base_message + "     " + base_message
    safe_text = escape_text_for_drawtext(repeat_message)

    if font_path:
        drawtext_filter = (
            f"drawtext=fontfile='{font_path}':"
            f"text='{safe_text}':"
            f"fontcolor=#53fc18:fontsize=30:"
            f"x=w-mod(t*100\\,text_w*2):y=h-th-20:"
            f"box=1:boxcolor=#b31015@1.0:boxborderw=10"
        )
    else:
        drawtext_filter = (
            f"drawtext=text='{safe_text}':"
            f"fontcolor=#53fc18:fontsize=30:"
            f"x=w-mod(t*100\\,text_w*2):y=h-th-20:"
            f"box=1:boxcolor=#b31015@1.0:boxborderw=10"
        )

    filter_complex = f"[1]scale=180:-1[logo];[0][logo]overlay={overlay_pos},{drawtext_filter}"

    watermark_cmd = [
        "ffmpeg",
        "-y",
        "-i", raw_video,
        "-i", logo_path,
        "-filter_complex", filter_complex,
        "-c:a", "copy",
        "-preset", "ultrafast",
        final_video
    ]

    print(f"🖼️ Running FFmpeg to apply logo and scrolling text...")
    try:
        result = subprocess.run(watermark_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = result.stdout.decode()
        if result.returncode != 0:
            print("❌ FFmpeg failed:\n", output)
            return
        print(f"✅ Final video ready: {final_video}")
    except Exception as e:
        print(f"❌ FFmpeg exception: {e}")
        return

    # Step 3: Upload to Google Drive
    try:
        upload_to_drive(final_video)
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return

    # Step 4: Clean up local files
    os.remove(raw_video)
    os.remove(final_video)
    print("🧹 Cleaned up local files.")

