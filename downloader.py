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
    temp_raw = f"temp_raw_{timestamp}.ts"
    raw_video = f"raw_kick_clip_{timestamp}.mp4"
    final_video = f"{streamer_name}_kick_clip_{timestamp}.mp4"

    # Calculate duration
    start_seconds = hms_to_seconds(start_time)
    end_seconds = hms_to_seconds(end_time)
    duration_seconds = max(0, end_seconds - start_seconds)
    duration = seconds_to_hms(duration_seconds)

    # =========================================================
    # Step 1: Download raw clip (pure copy, no decoding at all)
    # =========================================================
    download_cmd = [
        "ffmpeg",
        "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "-referer", "https://kick.com/",
        "-multiple_requests", "0",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", m3u8_url,
        "-ss", start_time,
        "-t", duration,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-ignore_unknown",
        "-c", "copy",
        "-copyts",
        "-y",
        temp_raw
    ]

    print(f"🎬 Step 1: Downloading raw clip to: {temp_raw}")
    try:
        subprocess.run(download_cmd, check=True)
    except subprocess.CalledProcessError:
        print("❌ Failed to download video. Check FFmpeg or m3u8 link.")
        return

    if not os.path.exists(temp_raw) or os.path.getsize(temp_raw) == 0:
        print("❌ Downloaded file is empty or missing!")
        return

    size_mb = os.path.getsize(temp_raw) / (1024 * 1024)
    print(f"✅ Downloaded raw clip: {temp_raw} ({size_mb:.2f} MB)")

    # =========================================================
    # Step 1.5: Fix timestamps and convert to mp4
    # =========================================================
    fix_cmd = [
        "ffmpeg",
        "-y",
        "-i", temp_raw,
        "-c:v", "copy",
        "-c:a", "aac",
        "-ac", "2",
        "-ar", "48000",
        "-af", "aresample=async=1",
        "-fflags", "+genpts",
        "-avoid_negative_ts", "make_zero",
        "-max_muxing_queue_size", "2048",
        raw_video
    ]

    print(f"🔧 Step 1.5: Fixing timestamps: {temp_raw} → {raw_video}")
    try:
        subprocess.run(fix_cmd, check=True)
    except subprocess.CalledProcessError:
        print("⚠️ Audio re-encode failed, trying pure copy fallback...")
        fallback_cmd = [
            "ffmpeg",
            "-y",
            "-i", temp_raw,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            raw_video
        ]
        try:
            subprocess.run(fallback_cmd, check=True)
        except subprocess.CalledProcessError:
            print("❌ All conversion methods failed.")
            if os.path.exists(temp_raw):
                os.remove(temp_raw)
            return

    # Clean up temp .ts file
    if os.path.exists(temp_raw):
        os.remove(temp_raw)

    if not os.path.exists(raw_video) or os.path.getsize(raw_video) == 0:
        print("❌ Raw video was not created or is empty!")
        return

    size_mb = os.path.getsize(raw_video) / (1024 * 1024)
    print(f"✅ Raw video ready: {raw_video} ({size_mb:.2f} MB)")

    # =========================================================
    # Step 2: Add watermark and scrolling text
    # =========================================================
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

    print(f"🖼️ Step 2: Applying logo and scrolling text...")

    # Check that inputs exist
    if not os.path.exists(logo_path):
        print(f"❌ Logo not found: {logo_path}")
        if os.path.exists(raw_video):
            os.remove(raw_video)
        return
    if font_path and not os.path.exists(font_path):
        print(f"⚠️ Font not found: {font_path}, using default")

    try:
        result = subprocess.run(watermark_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        output = result.stdout.decode()
        if result.returncode != 0:
            print("❌ FFmpeg watermark failed:\n", output)
            if os.path.exists(raw_video):
                os.remove(raw_video)
            return
    except subprocess.TimeoutExpired:
        print("❌ FFmpeg watermark timed out after 10 minutes!")
        if os.path.exists(raw_video):
            os.remove(raw_video)
        return
    except Exception as e:
        print(f"❌ FFmpeg exception: {e}")
        if os.path.exists(raw_video):
            os.remove(raw_video)
        return

    if not os.path.exists(final_video) or os.path.getsize(final_video) == 0:
        print("❌ Final video was not created or is empty!")
        if os.path.exists(raw_video):
            os.remove(raw_video)
        return

    size_mb = os.path.getsize(final_video) / (1024 * 1024)
    print(f"✅ Final video ready: {final_video} ({size_mb:.2f} MB)")

    # =========================================================
    # Step 3: Upload to Google Drive
    # =========================================================
    print(f"☁️ Step 3: Uploading to Google Drive...")
    try:
        upload_to_drive(final_video)
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return
    finally:
        # =========================================================
        # Step 4: Clean up local files
        # =========================================================
        if os.path.exists(raw_video):
            os.remove(raw_video)
        if os.path.exists(final_video):
            os.remove(final_video)
        if os.path.exists(temp_raw):
            os.remove(temp_raw)
        print("🧹 Cleaned up local files.")