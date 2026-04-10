import subprocess
import os
import re
import requests
import traceback
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
from datetime import datetime, timedelta
from upload_to_drive import upload_to_drive


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'Referer': 'https://kick.com/',
    'Accept': 'application/x-mpegURL, application/vnd.apple.mpegurl, application/json, text/plain',
    'Origin': 'https://kick.com',
}

MAX_CONCURRENT_DOWNLOADS = 5
SEGMENT_TIMEOUT = 30
DOWNLOAD_RETRIES = 3


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


def get_disk_space_mb():
    try:
        total, used, free = shutil.disk_usage(".")
        return free // (1024 * 1024)
    except:
        return 9999


def estimate_clip_size_mb(duration_sec):
    return (duration_sec / 60) * 50


def cleanup_files(files):
    for f in files:
        if f and os.path.exists(f):
            try:
                os.remove(f)
                print(f"   🗑️ Removed {f}")
            except Exception as e:
                print(f"   ⚠️ Failed to remove {f}: {e}")


def kill_ffmpeg():
    try:
        subprocess.run(["pkill", "-f", "ffmpeg"], capture_output=True, timeout=5)
    except:
        pass


def parse_m3u8_segments(m3u8_url):
    print(f"📋 Fetching playlist: {m3u8_url}")
    resp = requests.get(m3u8_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    playlist = resp.text

    lines = playlist.strip().split('\n')
    print(f"   Playlist has {len(lines)} lines")
    print(f"   First 3 lines:")
    for l in lines[:3]:
        print(f"     {l.strip()[:120]}")

    if '#EXT-X-STREAM-INF' in playlist:
        print("   ⚠️ Master playlist detected, selecting best quality...")
        best_url = None
        best_bandwidth = 0
        for i, line in enumerate(lines):
            if '#EXT-X-STREAM-INF' in line:
                bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                bandwidth = int(bw_match.group(1)) if bw_match else 0
                for j in range(i + 1, len(lines)):
                    candidate = lines[j].strip()
                    if candidate and not candidate.startswith('#'):
                        if bandwidth > best_bandwidth:
                            best_bandwidth = bandwidth
                            best_url = candidate
                        break
        if best_url:
            if not best_url.startswith('http'):
                best_url = urljoin(m3u8_url, best_url)
            print(f"   Using variant (bandwidth={best_bandwidth}): {best_url[:100]}")
            return parse_m3u8_segments(best_url)

    segments = []
    current_time = 0.0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF:'):
            match = re.search(r'#EXTINF:([\d.]+)', line)
            if match:
                duration = float(match.group(1))
                j = i + 1
                while j < len(lines):
                    seg_line = lines[j].strip()
                    if seg_line and not seg_line.startswith('#'):
                        seg_url = seg_line
                        if not seg_url.startswith('http'):
                            seg_url = urljoin(m3u8_url, seg_url)
                        segments.append({
                            'url': seg_url,
                            'duration': duration,
                            'start': current_time,
                            'end': current_time + duration,
                            'index': len(segments),
                        })
                        current_time += duration
                        i = j
                        break
                    j += 1
        i += 1

    if segments:
        print(f"   Total segments: {len(segments)}")
        print(f"   Total duration: {current_time:.1f}s ({seconds_to_hms(int(current_time))})")
        print(f"   First segment: {segments[0]['url'][:100]}")

    return segments


def download_single_segment(seg, session, retries=DOWNLOAD_RETRIES):
    for attempt in range(retries):
        try:
            resp = session.get(seg['url'], timeout=SEGMENT_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            return (seg['index'], resp.content)
        except Exception as e:
            if attempt < retries - 1:
                continue
            print(f"  ❌ Segment {seg['index']} failed after {retries} retries: {e}")
            return (seg['index'], None)


def download_needed_segments(segments, start_sec, end_sec, output_path, progress_callback=None):
    needed = [s for s in segments if s['end'] > start_sec and s['start'] < end_sec]

    if not needed:
        print(f"❌ No segments for {start_sec}s - {end_sec}s")
        return False, 0, 0

    total_segments = len(needed)
    duration_sec = end_sec - start_sec
    est_size = estimate_clip_size_mb(duration_sec)
    disk_free = get_disk_space_mb()

    print(f"📦 Need {total_segments} segments ({needed[0]['start']:.1f}s to {needed[-1]['end']:.1f}s)")
    print(f"📊 Estimated size: ~{est_size:.0f} MB | Disk free: {disk_free} MB")

    if est_size * 3 > disk_free:
        print("❌ Not enough disk space!")
        return False, 0, 0

    if progress_callback:
        progress_callback(f"📦 Downloading {total_segments} segments (~{est_size:.0f} MB)...")

    session = requests.Session()
    session.headers.update(HEADERS)

    if total_segments <= 10:
        workers = 1
    elif total_segments <= 50:
        workers = 3
    else:
        workers = MAX_CONCURRENT_DOWNLOADS

    print(f"   Using {workers} download workers")

    downloaded = {}
    failed_count = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(download_single_segment, seg, session): seg
            for seg in needed
        }

        completed = 0
        for future in as_completed(futures):
            idx, data = future.result()
            completed += 1

            if data is not None:
                downloaded[idx] = data
            else:
                failed_count += 1

            if completed % max(1, total_segments // 10) == 0 or completed == total_segments:
                pct = (completed / total_segments) * 100
                print(f"  📥 {completed}/{total_segments} ({pct:.0f}%)")
                if progress_callback and completed % max(1, total_segments // 5) == 0:
                    progress_callback(f"📥 Downloaded {completed}/{total_segments} segments ({pct:.0f}%)")

    session.close()

    if failed_count > total_segments * 0.3:
        print(f"❌ Too many failures: {failed_count}/{total_segments}")
        return False, 0, 0

    if failed_count > 0:
        print(f"⚠️ {failed_count} segments failed, continuing with {len(downloaded)}/{total_segments}")

    with open(output_path, 'wb') as f:
        for seg in needed:
            if seg['index'] in downloaded:
                f.write(downloaded[seg['index']])

    downloaded.clear()

    trim_start = start_sec - needed[0]['start']
    clip_duration = end_sec - start_sec

    return True, trim_start, clip_duration


def cut_and_watermark_kick_video(m3u8_url, start_time, end_time, logo_path="logo.png", streamer_name="MoroccanStreamer123", font_path="", progress_callback=None):
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_ts = f"temp_segments_{timestamp}.ts"
        raw_video = f"raw_kick_clip_{timestamp}.mp4"
        final_video = f"{streamer_name}_kick_clip_{timestamp}.mp4"

        start_sec = hms_to_seconds(start_time)
        end_sec = hms_to_seconds(end_time)
        clip_duration_sec = end_sec - start_sec

        if clip_duration_sec <= 0:
            return "End time must be after start time"

        print(f"🎬 Clip: {start_time} → {end_time} ({seconds_to_hms(clip_duration_sec)})")
        print(f"💾 Disk space: {get_disk_space_mb()} MB free")

        est_size = estimate_clip_size_mb(clip_duration_sec)
        disk_free = get_disk_space_mb()
        if est_size * 3 > disk_free:
            return f"Not enough disk space. Need ~{est_size*3:.0f} MB, have {disk_free} MB."

        # =========================================================
        # Step 1: Parse m3u8 and download segments
        # =========================================================
        if progress_callback:
            progress_callback("📋 Parsing playlist...")

        print("📋 Step 1: Parsing m3u8 playlist...")
        try:
            segments = parse_m3u8_segments(m3u8_url)
            if not segments:
                return "No segments found in m3u8 playlist. URL might be invalid or expired."
            total_duration = segments[-1]['end']
            print(f"   Found {len(segments)} segments ({seconds_to_hms(int(total_duration))} total)")
        except Exception as e:
            traceback.print_exc()
            return f"Failed to parse m3u8 playlist: {str(e)}"

        if start_sec >= total_duration:
            return f"Start time {start_time} is beyond stream end ({seconds_to_hms(int(total_duration))})"

        if end_sec > total_duration:
            print(f"⚠️ Capping end time to {seconds_to_hms(int(total_duration))}")
            end_sec = total_duration
            clip_duration_sec = end_sec - start_sec

        if progress_callback:
            progress_callback(f"📥 Downloading {seconds_to_hms(int(clip_duration_sec))} clip...")

        print(f"📥 Downloading segments...")
        try:
            success, trim_start, clip_duration = download_needed_segments(
                segments, start_sec, end_sec, temp_ts, progress_callback
            )
        except Exception as e:
            traceback.print_exc()
            cleanup_files([temp_ts])
            return f"Failed to download segments: {str(e)}"

        if not success:
            cleanup_files([temp_ts])
            return "Failed to download segments. Not enough disk space or too many failures."

        if not os.path.exists(temp_ts) or os.path.getsize(temp_ts) == 0:
            cleanup_files([temp_ts])
            return "Downloaded segment file is empty."

        size_mb = os.path.getsize(temp_ts) / (1024 * 1024)
        print(f"✅ Downloaded: {temp_ts} ({size_mb:.2f} MB)")

        if progress_callback:
            progress_callback(f"✅ Downloaded {size_mb:.1f} MB. Converting to MP4...")

        # =========================================================
        # Step 1.5: Convert .ts to .mp4 — Method 1: Copy video
        # =========================================================
        # Dynamic timeout based on clip length
        if clip_duration_sec <= 300:
            convert_timeout = 300
        elif clip_duration_sec <= 1800:
            convert_timeout = 600
        elif clip_duration_sec <= 7200:
            convert_timeout = 1200
        else:
            convert_timeout = 3600

        print(f"🔧 Step 1.5: Converting (copy mode, timeout={convert_timeout}s)...")

        convert_cmd = [
            "ffmpeg",
            "-y",
            "-err_detect", "ignore_err",
            "-fflags", "+genpts+discardcorrupt",
            "-i", temp_ts,
            "-ss", str(trim_start),
            "-t", str(clip_duration),
            "-c:v", "copy",
            "-c:a", "aac",
            "-ac", "2",
            "-ar", "48000",
            "-b:a", "128k",
            "-avoid_negative_ts", "make_zero",
            "-max_muxing_queue_size", "4096",
            "-movflags", "+faststart",
            raw_video
        ]

        conversion_success = False

        try:
            result = subprocess.run(
                convert_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=convert_timeout
            )
            output = result.stdout.decode()

            if result.returncode == 0 and os.path.exists(raw_video) and os.path.getsize(raw_video) > 1024:
                conversion_success = True
                print("✅ Copy mode conversion successful!")
            else:
                print(f"⚠️ Copy mode failed (returncode={result.returncode})")
                print(f"   Output: {output[-500:]}")

        except subprocess.TimeoutExpired:
            print(f"⚠️ Copy mode timed out after {convert_timeout}s")
            kill_ffmpeg()
        except Exception as e:
            print(f"⚠️ Copy mode error: {e}")

        # =========================================================
        # Step 1.5 Fallback: Re-encode at 720p
        # =========================================================
        if not conversion_success:
            print("🔧 Trying fallback: re-encode at 720p...")
            if progress_callback:
                progress_callback("⚠️ Copy failed, re-encoding at 720p...")

            if os.path.exists(raw_video):
                os.remove(raw_video)

            fallback_timeout = max(convert_timeout * 2, 1800)

            fallback_cmd = [
                "ffmpeg",
                "-y",
                "-err_detect", "ignore_err",
                "-fflags", "+genpts+discardcorrupt",
                "-i", temp_ts,
                "-ss", str(trim_start),
                "-t", str(clip_duration),
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-crf", "28",
                "-vf", "scale=1280:720",
                "-c:a", "aac",
                "-ac", "2",
                "-ar", "48000",
                "-b:a", "128k",
                "-avoid_negative_ts", "make_zero",
                "-max_muxing_queue_size", "4096",
                "-movflags", "+faststart",
                "-threads", "2",
                raw_video
            ]

            try:
                result2 = subprocess.run(
                    fallback_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=fallback_timeout
                )
                output2 = result2.stdout.decode()

                if result2.returncode == 0 and os.path.exists(raw_video) and os.path.getsize(raw_video) > 1024:
                    conversion_success = True
                    print("✅ Fallback 720p conversion successful!")
                else:
                    cleanup_files([temp_ts, raw_video])
                    return f"FFmpeg conversion failed (both methods):\n{output2[-500:]}"

            except subprocess.TimeoutExpired:
                kill_ffmpeg()
                cleanup_files([temp_ts, raw_video])
                return f"Conversion timed out ({fallback_timeout//60} min). Try a shorter clip."
            except Exception as e:
                cleanup_files([temp_ts, raw_video])
                return f"FFmpeg error: {str(e)}"

        # Clean up temp .ts
        cleanup_files([temp_ts])

        if not os.path.exists(raw_video) or os.path.getsize(raw_video) == 0:
            return "FFmpeg produced an empty video file"

        size_mb = os.path.getsize(raw_video) / (1024 * 1024)
        print(f"✅ Raw video: {raw_video} ({size_mb:.2f} MB)")

        if progress_callback:
            progress_callback(f"✅ Video converted ({size_mb:.1f} MB). Adding watermark...")

        # =========================================================
        # Step 2: Add watermark and scrolling text
        # =========================================================
        # Dynamic watermark settings
        if clip_duration_sec <= 300:
            wm_scale = None
            wm_preset = "ultrafast"
            wm_crf = "23"
            wm_timeout = 600
        elif clip_duration_sec <= 1800:
            wm_scale = "scale=1280:720"
            wm_preset = "ultrafast"
            wm_crf = "26"
            wm_timeout = 1800
        elif clip_duration_sec <= 7200:
            wm_scale = "scale=1280:720"
            wm_preset = "ultrafast"
            wm_crf = "28"
            wm_timeout = 3600
        else:
            wm_scale = "scale=854:480"
            wm_preset = "ultrafast"
            wm_crf = "30"
            wm_timeout = 7200

        print(f"🖼️ Step 2: Watermark (timeout={wm_timeout}s)...")

        if not os.path.exists(logo_path):
            print(f"⚠️ Logo not found: {logo_path}, skipping watermark")
            os.rename(raw_video, final_video)
        else:
            if font_path and not os.path.exists(font_path):
                print(f"⚠️ Font not found: {font_path}, using default")
                font_path = ""

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

            if wm_scale:
                filter_complex = f"[0]{wm_scale}[scaled];[1]scale=120:-1[logo];[scaled][logo]overlay={overlay_pos},{drawtext_filter}"
            else:
                filter_complex = f"[1]scale=180:-1[logo];[0][logo]overlay={overlay_pos},{drawtext_filter}"

            watermark_cmd = [
                "ffmpeg",
                "-y",
                "-i", raw_video,
                "-i", logo_path,
                "-filter_complex", filter_complex,
                "-c:v", "libx264",
                "-preset", wm_preset,
                "-crf", wm_crf,
                "-c:a", "copy",
                "-threads", "2",
                "-movflags", "+faststart",
                final_video
            ]

            try:
                result = subprocess.run(
                    watermark_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=wm_timeout
                )
                output = result.stdout.decode()

                if result.returncode != 0:
                    print(f"⚠️ Watermark failed, uploading without watermark")
                    print(f"   Error: {output[-500:]}")
                    if progress_callback:
                        progress_callback("⚠️ Watermark failed, uploading without it...")
                    if os.path.exists(final_video):
                        os.remove(final_video)
                    os.rename(raw_video, final_video)

            except subprocess.TimeoutExpired:
                print(f"⚠️ Watermark timed out, uploading without watermark")
                kill_ffmpeg()
                if progress_callback:
                    progress_callback("⚠️ Watermark timed out, uploading without it...")
                if os.path.exists(final_video):
                    os.remove(final_video)
                if os.path.exists(raw_video):
                    os.rename(raw_video, final_video)

            except Exception as e:
                print(f"⚠️ Watermark error: {e}, uploading without watermark")
                if os.path.exists(final_video):
                    os.remove(final_video)
                if os.path.exists(raw_video):
                    os.rename(raw_video, final_video)

        # Clean up raw if still exists
        if os.path.exists(raw_video) and raw_video != final_video:
            os.remove(raw_video)

        if not os.path.exists(final_video) or os.path.getsize(final_video) == 0:
            return "Final video is empty"

        size_mb = os.path.getsize(final_video) / (1024 * 1024)
        print(f"✅ Final video: {final_video} ({size_mb:.2f} MB)")

        if progress_callback:
            progress_callback(f"✅ Video ready ({size_mb:.1f} MB). Uploading to Drive...")

        # =========================================================
        # Step 3: Upload to Google Drive
        # =========================================================
        print("☁️ Step 3: Uploading to Google Drive...")
        try:
            upload_to_drive(final_video)
            print("✅ Upload complete!")
        except Exception as e:
            traceback.print_exc()
            return f"Google Drive upload failed: {str(e)}"
        finally:
            cleanup_files([raw_video, final_video, temp_ts])
            print("🧹 Cleaned up.")

        return True

    except Exception as e:
        traceback.print_exc()
        return f"Unexpected error: {str(e)}\n{traceback.format_exc()[-500:]}"