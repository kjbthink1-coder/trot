"""
engine/qa/frame_extractor.py - Video Frame Extraction Module for QA Inspection
============================================================================
Extracts representative keyframes across video duration using FFmpeg for
visual QA review, multimodal AI inspection, and scene alignment checks.
"""

import os
import json
import shutil
import tempfile
import subprocess
import logging
from typing import List, Optional

logger = logging.getLogger("qa.frame_extractor")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def get_ffmpeg_exe() -> str:
    """
    Locates the FFmpeg executable from imageio_ffmpeg, system PATH, or default.
    """
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    return "ffmpeg"


def get_video_duration(video_path: str) -> float:
    """
    Retrieves the total duration (in seconds) of a video using FFmpeg.
    Returns 60.0 as fallback if probing fails.
    """
    if not video_path or not os.path.exists(video_path):
        return 0.0

    ffmpeg_exe = get_ffmpeg_exe()
    cmd = [ffmpeg_exe, "-i", video_path]
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="ignore",
            timeout=15
        )
        for line in res.stderr.split("\n"):
            if "Duration:" in line:
                # Example: Duration: 00:00:58.45, start: 0.000000, bitrate: 2450 kb/s
                parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                hours = float(parts[0])
                mins = float(parts[1])
                secs = float(parts[2])
                dur = hours * 3600 + mins * 60 + secs
                if dur > 0:
                    return dur
    except Exception as e:
        logger.warning(f"Failed to probe video duration for {video_path}: {e}")

    return 60.0


def calculate_target_timestamps(
    total_dur: float,
    count: int = 5,
    timeline_segments: Optional[list] = None,
    max_frames: int = 10
) -> List[float]:
    """
    Calculates representative extraction timestamps based on video duration.
    - Base frames: 0.5s, 15.0s, 30.0s, 45.0s, and (total_dur - 1.0)s.
    - Transition frames: If timeline_segments is provided, adds boundary points:
      - 'stage_clip' or 'broll': start_time + 0.2s and end_time - 0.2s
      - 1-2 photo cut transitions
    - Deduplicates timestamps to maintain a minimum 1.5s gap.
    - Extracts up to 8-10 high-value frames.
    - Gracefully falls back to standard distribution if no timeline segments.
    """
    if total_dur <= 1.0:
        return [0.1 * total_dur] if total_dur > 0 else [0.0]

    # Standard base anchors
    if total_dur >= 48.0:
        last_ts = max(0.5, total_dur - 1.0)
        base_candidates = [0.5, 15.0, 30.0, 45.0, round(last_ts, 2)]
    else:
        start_ts = min(0.5, total_dur * 0.1)
        end_ts = max(start_ts + 0.1, total_dur - 0.5)
        if count <= 1:
            base_candidates = [round(total_dur / 2.0, 2)]
        else:
            step = (end_ts - start_ts) / (count - 1)
            base_candidates = [round(start_ts + i * step, 2) for i in range(count)]

    # Fallback to basic distribution if timeline_segments is not provided
    if not timeline_segments:
        return base_candidates[:count]

    # Timeline-based smart transition frames
    selected: List[float] = []
    # Seed with base anchors that have at least 1.5s gap
    for b_ts in base_candidates:
        if 0.1 <= b_ts <= total_dur - 0.1:
            if not selected or all(abs(b_ts - s) >= 1.5 for s in selected):
                selected.append(b_ts)

    stage_broll_candidates: List[float] = []
    photo_candidates: List[float] = []

    for seg in timeline_segments:
        if not isinstance(seg, dict):
            continue
        stype = seg.get("type", "")
        t0 = float(seg.get("start_time", 0.0))
        t1 = float(seg.get("end_time", 0.0))

        if stype in ("stage_clip", "broll", "singer", "stock"):
            cand_start = round(t0 + 0.2, 2)
            cand_end = round(t1 - 0.2, 2)
            if 0.2 <= cand_start <= total_dur - 0.2:
                stage_broll_candidates.append(cand_start)
            if 0.2 <= cand_end <= total_dur - 0.2 and cand_end > cand_start + 0.4:
                stage_broll_candidates.append(cand_end)
        elif stype in ("photo", "thumb", "thumbnail"):
            if 2.0 <= t0 <= total_dur - 2.0:
                photo_candidates.append(round(t0 + 0.2, 2))

    # Add 1-2 photo cut transitions
    selected_photo_cuts: List[float] = []
    if len(photo_candidates) >= 2:
        idx1 = len(photo_candidates) // 3
        idx2 = (2 * len(photo_candidates)) // 3
        if idx1 == idx2 and len(photo_candidates) > 1:
            idx2 = min(len(photo_candidates) - 1, idx1 + 1)
        selected_photo_cuts = [photo_candidates[idx1], photo_candidates[idx2]]
    elif photo_candidates:
        selected_photo_cuts = [photo_candidates[0]]

    # Prioritize stage / broll transitions, then photo cuts with minimum 1.5s gap deduplication
    for cand in stage_broll_candidates:
        if len(selected) >= max_frames:
            break
        if 0.2 <= cand <= total_dur - 0.2:
            if all(abs(cand - s) >= 1.5 for s in selected):
                selected.append(cand)

    for cand in selected_photo_cuts:
        if len(selected) >= max_frames:
            break
        if 0.2 <= cand <= total_dur - 0.2:
            if all(abs(cand - s) >= 1.5 for s in selected):
                selected.append(cand)

    selected.sort()
    return selected


def extract_representative_frames(
    video_path: str,
    count: int = 5,
    timeline_segments: Optional[list] = None,
    output_dir: Optional[str] = None
) -> List[str]:
    """
    Extracts representative frames from a video file at target timestamps.
    - Default intervals: 0.5s, 15s, 30s, 45s, and (total_dur - 1)s.
    - Smart transition frames: If timeline_segments is provided or shorts_timeline.json
      is found, extracts frames at transition boundaries (up to 8-10 high-value frames).
    - Graceful fallback: If only video_path is provided, extracts standard count frames.

    Args:
        video_path: Path to the source MP4/video file.
        count: Target number of frames to extract (default 5).
        timeline_segments: Optional list of timeline segment dictionaries.
        output_dir: Directory where JPEG frames will be saved.
                    If None, a temporary directory prefixed with 'qa_frames_' is created.

    Returns:
        List of absolute file paths to the successfully extracted JPEG frames.
    """
    # Defensive handling if 3rd positional argument was passed as output_dir
    if isinstance(timeline_segments, str) and output_dir is None:
        output_dir = timeline_segments
        timeline_segments = None

    if not video_path or not os.path.isfile(video_path):
        logger.warning(f"Video file not found or invalid: {video_path}")
        return []

    if os.path.getsize(video_path) == 0:
        logger.warning(f"Video file is empty: {video_path}")
        return []

    total_dur = get_video_duration(video_path)
    if total_dur <= 0.0:
        logger.warning(f"Video duration is 0 for {video_path}")
        return []

    # Attempt to load timeline_segments if not provided and standard frame count requested
    if timeline_segments is None and count >= 5:
        video_dir = os.path.dirname(os.path.abspath(video_path))
        cand_paths = [
            os.path.join(video_dir, "shorts_timeline.json"),
            os.path.abspath("outputs/videos/shorts_timeline.json")
        ]
        for cp in cand_paths:
            if os.path.isfile(cp):
                try:
                    with open(cp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        vid_meta = data.get("video_path")
                        dur_meta = data.get("total_duration")
                        if vid_meta and os.path.basename(vid_meta) == os.path.basename(video_path):
                            timeline_segments = data.get("segments", [])
                            break
                        elif dur_meta and abs(dur_meta - total_dur) < 2.0:
                            timeline_segments = data.get("segments", [])
                            break
                    elif isinstance(data, list):
                        timeline_segments = data
                        break
                except Exception as e:
                    logger.debug(f"Failed to load timeline JSON from {cp}: {e}")

    eff_max = count if count < 5 else 10
    timestamps = calculate_target_timestamps(
        total_dur=total_dur,
        count=count,
        timeline_segments=timeline_segments,
        max_frames=eff_max
    )
    ffmpeg_exe = get_ffmpeg_exe()

    # Determine destination directory
    is_temp_dir = False
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        target_dir = os.path.abspath(output_dir)
    else:
        target_dir = tempfile.mkdtemp(prefix="qa_frames_")
        is_temp_dir = True

    extracted_frames: List[str] = []

    for idx, ts in enumerate(timestamps):
        out_filename = f"frame_{idx + 1:02d}_{ts:.1f}s.jpg"
        out_filepath = os.path.join(target_dir, out_filename)

        # Fast seek with -ss before -i, extracting exactly 1 frame with high JPEG quality (-q:v 2)
        cmd = [
            ffmpeg_exe,
            "-ss", str(ts),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            "-y",
            out_filepath
        ]

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False
            )
            if os.path.isfile(out_filepath) and os.path.getsize(out_filepath) > 0:
                extracted_frames.append(out_filepath)
            else:
                logger.debug(f"Frame extraction at {ts}s did not produce output: {res.stderr[:200]}")
        except subprocess.TimeoutExpired:
            logger.warning(f"FFmpeg timeout extracting frame at {ts}s from {video_path}")
        except Exception as e:
            logger.warning(f"Error extracting frame at {ts}s: {e}")

    logger.info(
        f"Extracted {len(extracted_frames)}/{len(timestamps)} frames from {os.path.basename(video_path)} "
        f"(total duration: {total_dur:.1f}s) to {target_dir}"
    )

    return extracted_frames


def cleanup_frames(frame_paths: List[str]) -> None:
    """
    Deletes the extracted frame files and removes their parent directory
    if it was a temporary directory created during extraction.

    Args:
        frame_paths: List of file paths previously returned by extract_representative_frames.
    """
    if not frame_paths:
        return

    dirs_to_clean = set()
    for fp in frame_paths:
        if fp and os.path.isfile(fp):
            try:
                parent_dir = os.path.dirname(fp)
                os.remove(fp)
                # If directory name begins with 'qa_frames_', mark for folder cleanup
                if os.path.basename(parent_dir).startswith("qa_frames_"):
                    dirs_to_clean.add(parent_dir)
            except Exception as e:
                logger.debug(f"Error removing frame file {fp}: {e}")

    for d in dirs_to_clean:
        try:
            if os.path.exists(d) and not os.listdir(d):
                os.rmdir(d)
        except Exception as e:
            logger.debug(f"Error cleaning temporary directory {d}: {e}")
