import subprocess
import os
import re
import requests
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


def parse_m3u8_segments(m3u8_url, headers):
    """Fetch and parse m3u8 playlist, return segments with timing info."""
    resp = requests.get(m3u8_url, headers=headers, timeout=30)
    resp.raise_for_status()
    playlist = resp.text

    base_url = m3u8_url.rsplit('/', 1)[0] + '/'

    segments = []
    current_time = 0.0
    lines = playlist.strip().split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF:'):
            match = re.search(r'#EXTINF:([\d.]+)', line)
            if match:
                duration = float(match.group(1))
                # Find the segment URL (next non-comment, non-empty line)
                j = i + 1
                while j < len(lines):
                    seg_line = lines[j].strip()
                    if seg_line and not seg_line.startswith('#'):
                        seg_url = seg_line
                        if not seg_url.startswith('http'):
                            seg_url = base_url + seg_url
                        segments.append({
                            'url': seg_url,
                            'duration': duration,
                            'start': current_time,
                            'end': current_time + duration,
                        })
                        current_time += duration
                        i = j
                        break
                    j += 1
        i += 1

    return segments


def download_needed_segments(segments, start_sec, end_sec, output_path, headers):
    """Download only segments that overlap with the requested time range."""
    needed = [s for s in segments if s['end'] > start_sec and s['start'] < end_sec]

    if not needed:
        print(f"❌ No segments found for {start_sec}s - {end_sec}s")
        return False, 0, 0

    print(f"📦 Need {len(needed)} segments ({needed[0]['start']:.1f}s to {needed[-1]['end']:.1f}s)")

    with open(output_path, 'wb') as f:
        for i, seg in enumerate(needed):
            try:
                resp = requests.get(seg['url'], headers=headers, timeout=30)
                resp.raise_for_status()
                f.write(resp.content)
                if (i + 1) % 3 == 0 or (i + 1) == len(needed):
                    print(f"  📥 Downloaded {i+1}/{len(needed)} segments")
            except requests.RequestException as e:
                print(f"  ⚠️ Segment {i+1} failed: {e}, skipping...")
                continue

    # How much to trim from the start of first segment
    trim_start = start_sec - needed[0]['start']
    clip_duration = end_sec - start_sec

    return True, trim_start, clip_duration


def cut_and_watermark_kick_video(m3u8_url, start_time, end_time, logo_path="logo.png", streamer_name="MoroccanStreamer123", font_path=""):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_ts = f"temp_segments_{timestamp}.ts"
    raw_video = f"raw_kick_clip_{timestamp}.mp4"
    final_video = f"{streamer_name}_kick_clip_{timestamp}.mp4"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://kick.com/'
    }

    start_sec = hms_to_seconds(start_time)
    end_sec = hms_to_seconds(end_time)

    # =========================================================
    # Step 1: Parse m3u8 and download only needed segments
    # =========================================================
    print(f"📋 Step 1: Parsing m3u8 playlist...")
    try:
        segments = parse_m3u8_segments(m3u8_url, headers)
        if not segments:
            print("❌ No segments found in playlist!")
            return
        total_duration = segments[-1]['end']
        print(f"   Found {len(segments)} segments ({total_duration:.1f}s total)")
    except Exception as e:
        print(f"❌ Failed to parse m3u8: {e}")
        return

    print(f"📥 Downloading segments for {start_time} → {end_time}...")
    success, trim_start, clip_duration = download_needed_segments(
        segments, start_sec, end_sec, temp_ts, headers
    )

    if not success:
        return

    if not os.path.exists(temp_ts) or os.path.getsize(temp_ts) == 0:
        print("❌ Downloaded segment file is empty!")
        return

    size_mb = os.path.getsize(temp_ts) / (1024 * 1024)
    print(f"✅ Downloaded: {temp_ts} ({size_mb:.2f} MB)")

    # =========================================================
    # Step 1.5: Convert local .ts to clean .mp4
    # =========================================================
    convert_cmd = [
        "ffmpeg",
        "-y",
        "-err_detect", "ignore_err",
        "-fflags", "+genpts+discardcorrupt",
        "-i", temp_ts,
        "-ss", str(trim_start),
        "-t", str(clip_duration),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        "-ac", "2",
        "-ar", "48000",
        "-b:a", "128k",
        "-avoid_negative_ts", "make_zero",
        "-max_muxing_queue_size", "4096",
        "-movflags", "+faststart",
        raw_video
    ]

    print(f"🔧 Step 1.5: Converting to MP4 (trim {trim_start:.1f}s, duration {clip_duration:.1f}s)...")
    try:
        result = subprocess.run(convert_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = result.stdout.decode()
        if result.returncode != 0:
            print(f"❌ Conversion failed:\n{output[-1000:]}")
            if os.path.exists(temp_ts):
                os.remove(temp_ts)
            return
    except Exception as e:
        print(f"❌ Conversion exception: {e}")
        if os.path.exists(temp_ts):
            os.remove(temp_ts)
        return

    # Clean up temp .ts
    if os.path.exists(temp_ts):
        os.remove(temp_ts)

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
            print("❌ FFmpeg watermark failed:\n", output[-1000:])
            if os.path.exists(raw_video):
                os.remove(raw_video)
            return
    except subprocess.TimeoutExpired:
        print("❌ Watermark timed out after 10 minutes!")
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
        # Step 4: Clean up ALL local files
        # =========================================================
        for f in [raw_video, final_video, temp_ts]:
            if os.path.exists(f):
                os.remove(f)
        print("🧹 Cleaned up local files.")