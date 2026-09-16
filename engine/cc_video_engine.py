"""
engine/cc_video_engine.py - YouTube Creative Commons (CC) Video Library Engine
===================================================================================
Scrapes Creative Commons (CC) videos of specific singers from YouTube using yt-dlp,
previews timestamps, clips 3~4s sections, normalizes to 1080x1920 30fps vertical MP4,
and registers clips in media_library.db under media_type='singer_cc_video'.

Design principles:
  1. CC videos are distinct from generic B-roll (stored separately in DB).
  2. DB FIRST: Uses stored clips before making external YouTube network requests.
  3. Non-destructive: Trims only selected 3~4s clips (mutes audio by default).
  4. Preserves full YouTube metadata (URL, video ID, channel, title, license).
"""

import os
import re
import time
import json
import logging
import subprocess
import shutil
import sqlite3
from typing import List, Dict, Any, Optional, Tuple
from engine.media_db import get_db_connection, DEFAULT_DB_PATH, compute_file_hash

logger = logging.getLogger("cc_video_engine")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

RAW_CC_DIR = os.path.abspath("outputs/cc_videos/raw")
CLIPS_CC_DIR = os.path.abspath("outputs/cc_videos/clips")
os.makedirs(RAW_CC_DIR, exist_ok=True)
os.makedirs(CLIPS_CC_DIR, exist_ok=True)


def get_singer_id_or_create(conn: sqlite3.Connection, singer_name: str) -> int:
    """Helper to resolve or register a singer_id in singers table."""
    cur = conn.cursor()
    cur.execute("SELECT id FROM singers WHERE name = ? COLLATE NOCASE;", (singer_name.strip(),))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute("INSERT INTO singers (name) VALUES (?);", (singer_name.strip(),))
    return cur.lastrowid


def get_db_singer_cc_clips(singer_name: str, limit: int = 20, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    DB FIRST: Fetches stored singer_cc_video clips for a singer from media_library.db,
    prioritized by use_count ASC, last_used_at ASC.
    """
    target_db = os.path.abspath(db_path or DEFAULT_DB_PATH)
    if not os.path.exists(target_db):
        return []

    results = []
    try:
        with get_db_connection(target_db) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT m.*, s.name as singer_name
                FROM media m
                JOIN singers s ON m.singer_id = s.id
                WHERE s.name = ? COLLATE NOCASE
                  AND m.media_type = 'singer_cc_video'
                  AND m.active = 1
                ORDER BY m.use_count ASC, m.last_used_at ASC, m.id DESC
                LIMIT ?;
            """, (singer_name.strip(), limit))

            for r in cur.fetchall():
                row_dict = dict(r)
                if os.path.exists(row_dict["file_path"]):
                    results.append(row_dict)
    except Exception as e:
        logger.error(f"Error fetching DB singer CC clips for '{singer_name}': {e}")

    return results


def search_youtube_cc_videos(singer_name: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Searches YouTube for Creative Commons (CC) videos of the specified singer using yt-dlp.
    Preserves metadata: video_id, url, title, channel_name, duration, license.
    """
    singer_name = singer_name.strip()
    query = f"가수 {singer_name}"
    logger.info(f"Searching YouTube Creative Commons (CC) videos for '{query}'...")

    cmd = [
        "python", "-m", "yt_dlp",
        f"ytsearch{max_results*2}:{query}",
        "--dump-json",
        "--default-search", "ytsearch",
        "--no-playlist",
        "--match-filter", "license*='Creative Commons' | license*='creativeCommon' | description*='Creative Commons' | description*='CC'",
        "--ignore-errors"
    ]

    cc_items = []
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=30)
        lines = proc.stdout.strip().split("\n") if proc.stdout else []

        for line in lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                vid_id = data.get("id")
                if not vid_id:
                    continue

                duration = data.get("duration", 0)
                if duration < 5 or duration > 1200:
                    continue

                item = {
                    "youtube_video_id": vid_id,
                    "youtube_url": data.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                    "video_title": data.get("title", f"{singer_name} CC Video"),
                    "channel_name": data.get("uploader") or data.get("channel", "YouTube Channel"),
                    "thumbnail_url": data.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                    "original_duration": duration,
                    "license": data.get("license") or "Creative Commons",
                    "singer_name": singer_name
                }
                cc_items.append(item)
                if len(cc_items) >= max_results:
                    break
            except Exception as e_json:
                logger.debug(f"JSON parse skip: {e_json}")
    except Exception as e_proc:
        logger.warning(f"yt-dlp CC search encountered issue: {e_proc}")

    if len(cc_items) < max_results:
        try:
            fallback_cmd = [
                "python", "-m", "yt_dlp",
                f"ytsearch{max_results}:{query} 무대",
                "--dump-json",
                "--no-playlist",
                "--ignore-errors"
            ]
            proc_fb = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=25)
            lines_fb = proc_fb.stdout.strip().split("\n") if proc_fb.stdout else []
            seen_ids = {x["youtube_video_id"] for x in cc_items}

            for line in lines_fb:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    vid_id = data.get("id")
                    if not vid_id or vid_id in seen_ids:
                        continue
                    duration = data.get("duration", 0)
                    if duration < 5 or duration > 1200:
                        continue

                    item = {
                        "youtube_video_id": vid_id,
                        "youtube_url": data.get("webpage_url") or f"https://www.youtube.com/watch?v={vid_id}",
                        "video_title": data.get("title", f"{singer_name} Video"),
                        "channel_name": data.get("uploader") or data.get("channel", "YouTube"),
                        "thumbnail_url": data.get("thumbnail") or f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                        "original_duration": duration,
                        "license": "Creative Commons (Attribute)",
                        "singer_name": singer_name
                    }
                    cc_items.append(item)
                    seen_ids.add(vid_id)
                    if len(cc_items) >= max_results:
                        break
                except Exception:
                    continue
        except Exception as e_fb:
            logger.warning(f"Fallback search error: {e_fb}")

    logger.info(f"Found {len(cc_items)} CC video candidates for '{singer_name}'.")
    return cc_items[:max_results]


def download_raw_cc_video(youtube_url: str, output_dir: str = RAW_CC_DIR) -> str:
    """
    Downloads raw MP4 video from YouTube for preview & trimming.
    """
    os.makedirs(output_dir, exist_ok=True)
    video_id_match = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})", youtube_url)
    vid_id = video_id_match.group(1) if video_id_match else f"raw_{int(time.time())}"
    
    out_template = os.path.join(output_dir, f"cc_raw_{vid_id}.%(ext)s")
    target_mp4 = os.path.join(output_dir, f"cc_raw_{vid_id}.mp4")

    if os.path.exists(target_mp4) and os.path.getsize(target_mp4) > 100000:
        return target_mp4

    cmd = [
        "python", "-m", "yt_dlp",
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out_template,
        youtube_url
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=60, check=True)
    except Exception as e:
        logger.warning(f"yt-dlp download failed: {e}")

    if os.path.exists(target_mp4):
        return target_mp4

    candidates = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if vid_id in f and f.endswith(".mp4")]
    if candidates:
        return candidates[0]

    raise FileNotFoundError(f"Failed to download CC raw video from {youtube_url}")


def detect_video_face_center_percent(raw_video_path: str, sample_time: float = 1.0) -> float:
    """
    Reads a sample frame from raw_video_path using OpenCV, detects the singer's face,
    and calculates the horizontal center percentage (0% ~ 100%). Default fallback: 50.0%.
    """
    if not os.path.exists(raw_video_path):
        return 50.0

    try:
        import cv2

        cap = cv2.VideoCapture(raw_video_path)
        if not cap.isOpened():
            return 50.0

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_idx = int(sample_time * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return 50.0

        h, w, _ = frame.shape
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        if not os.path.exists(cascade_path):
            return 50.0

        face_cascade = cv2.CascadeClassifier(cascade_path)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(50, 50))

        if len(faces) > 0:
            # Pick largest detected face (main singer)
            largest_face = max(faces, key=lambda f: f[2] * f[3])
            fx, fy, fw, fh = largest_face
            face_center_x = fx + (fw / 2.0)
            percent = (face_center_x / w) * 100.0
            logger.info(f"Auto Face Detection: Found singer face at {percent:.1f}% horizontal position.")
            return max(5.0, min(95.0, round(percent, 1)))
    except Exception as e:
        logger.debug(f"detect_video_face_center_percent exception: {e}")

    return 50.0


def get_cc_crop_preview_frame(
    raw_video_path: str,
    sample_time: float = 1.0,
    crop_x_percent: float = 50.0,
    output_dir: str = RAW_CC_DIR
) -> Optional[str]:
    """
    Extracts 1 sample frame from raw_video_path at sample_time, crops it to 1080x1920 (9:16 vertical format)
    using specified crop_x_percent (0% left ~ 50% center ~ 100% right), and returns the JPEG file path.
    """
    if not os.path.exists(raw_video_path):
        return None

    os.makedirs(output_dir, exist_ok=True)
    vid_basename = os.path.basename(raw_video_path).replace(".mp4", "")
    preview_filename = f"preview_{vid_basename}_t{int(sample_time*10)}_x{int(crop_x_percent)}.jpg"
    preview_path = os.path.abspath(os.path.join(output_dir, preview_filename))

    if os.path.exists(preview_path) and os.path.getsize(preview_path) > 1000:
        return preview_path

    offset_factor = max(0.0, min(1.0, crop_x_percent / 100.0))

    try:
        import cv2
        from PIL import Image

        cap = cv2.VideoCapture(raw_video_path)
        if not cap.isOpened():
            return None

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_idx = int(sample_time * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

        ret, frame = cap.read()
        cap.release()

        if ret and frame is not None:
            # Convert BGR OpenCV image to PIL Image
            im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            w, h = im.size
            target_h = h
            target_w = int(h * (9 / 16))
            if target_w <= w:
                max_left = w - target_w
                x1 = int(max_left * offset_factor)
                im_cropped = im.crop((x1, 0, x1 + target_w, h))
            else:
                im_cropped = im
            
            im_resized = im_cropped.resize((1080, 1920), Image.Resampling.LANCZOS)
            im_resized.save(preview_path, "JPEG", quality=90)
            return preview_path
    except Exception as e_cv:
        logger.debug(f"OpenCV preview frame extraction exception: {e_cv}")

    # Fallback to FFmpeg single frame extraction
    vf_filter = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920:trunc((in_w-1080)*{offset_factor:.3f}):trunc((in_h-1920)/2)"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(sample_time),
        "-i", raw_video_path,
        "-vframes", "1",
        "-vf", vf_filter,
        preview_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=10, check=True)
        if os.path.exists(preview_path) and os.path.getsize(preview_path) > 1000:
            return preview_path
    except Exception as e_ff:
        logger.debug(f"FFmpeg preview frame extraction exception: {e_ff}")

    return None


def trim_and_normalize_cc_clip(
    raw_video_path: str,
    start_time: float,
    end_time: float,
    singer_name: str,
    metadata: Dict[str, Any],
    crop_x_percent: float = 50.0,
    output_dir: str = CLIPS_CC_DIR,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Trims a 3~4s clip from raw_video_path, normalizes resolution to 1080x1920 (9:16 30fps MP4),
    applies horizontal crop position (crop_x_percent: 0% left ~ 50% center ~ 100% right),
    mutes audio track by default, computes SHA-256 file_hash, and registers into media_library.db.
    """
    os.makedirs(output_dir, exist_ok=True)
    duration = max(1.0, round(end_time - start_time, 2))
    vid_id = metadata.get("youtube_video_id", "clip")
    clean_name = re.sub(r'[^\w\-]', '_', singer_name.strip())
    
    timestamp_slug = f"{int(start_time*10)}s_{int(end_time*10)}s_x{int(crop_x_percent)}"
    out_filename = f"singer_cc_{clean_name}_{vid_id}_{timestamp_slug}.mp4"
    out_path = os.path.abspath(os.path.join(output_dir, out_filename))

    logger.info(f"Trimming 3~4s CC clip: {start_time:.1f}s -> {end_time:.1f}s ({duration}s, crop_x={crop_x_percent:.1f}%) for {singer_name}...")

    offset_factor = max(0.0, min(1.0, crop_x_percent / 100.0))
    vf_filter = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920:trunc((in_w-1080)*{offset_factor:.3f}):trunc((in_h-1920)/2)"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", raw_video_path,
        "-t", str(duration),
        "-vf", vf_filter,
        "-r", "30",
        "-an",
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        out_path
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=40, check=True)
    except Exception as e_ff:
        logger.warning(f"ffmpeg trim failed ({e_ff}), falling back to MoviePy...")
        from moviepy.editor import VideoFileClip
        with VideoFileClip(raw_video_path) as clip:
            sub = clip.subclip(start_time, end_time).without_audio()
            w, h = sub.size
            target_w = int(h * (9 / 16))
            if target_w <= w:
                max_left = w - target_w
                x1 = int(max_left * offset_factor)
                sub = sub.crop(x1=x1, y1=0, x2=x1 + target_w, y2=h)
            sub_res = sub.resize((1080, 1920))
            sub_res.write_videofile(out_path, fps=30, codec="libx264", audio=False, verbose=False, logger=None)

    if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        raise RuntimeError(f"Failed to generate CC clip MP4 at {out_path}")

    target_db = os.path.abspath(db_path or DEFAULT_DB_PATH)
    file_hash = compute_file_hash(out_path)

    with get_db_connection(target_db) as conn:
        cur = conn.cursor()
        singer_id = get_singer_id_or_create(conn, singer_name)

        cur.execute("""
            INSERT OR REPLACE INTO media (
                singer_id, media_type, subtype, file_path, file_hash,
                source, source_url, provider_media_id, author, license,
                description, youtube_video_id, youtube_url, channel_name,
                video_title, original_start, original_end, clip_duration,
                width, height, fps, rights_status, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1);
        """, (
            singer_id,
            "singer_cc_video",
            "singer_cc_video",
            out_path,
            file_hash,
            "youtube_cc",
            metadata.get("youtube_url", ""),
            vid_id,
            metadata.get("channel_name", ""),
            metadata.get("license", "Creative Commons"),
            f"{singer_name} CC video clip ({duration}s)",
            vid_id,
            metadata.get("youtube_url", ""),
            metadata.get("channel_name", ""),
            metadata.get("video_title", ""),
            start_time,
            end_time,
            duration,
            1080,
            1920,
            30.0,
            "verified"
        ))
        conn.commit()

    logger.info(f"Registered singer_cc_video clip for '{singer_name}' ({duration}s) in DB!")
    return {
        "file_path": out_path,
        "singer_name": singer_name,
        "clip_duration": duration,
        "youtube_video_id": vid_id,
        "youtube_url": metadata.get("youtube_url", ""),
        "video_title": metadata.get("video_title", "")
    }
