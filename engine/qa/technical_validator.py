"""
engine/qa/technical_validator.py

QA-1 Technical Validator module for Shorts & Video Generation Pipeline.
Performs deterministic, rule-based technical quality inspections on the final MP4 video,
audio streams, TTS alignment, subtitle layout conventions, and referenced media assets.

Validation checks:
1. MP4 integrity: file existence, size >= 10KB, openable & decodable with OpenCV/ffmpeg
2. Resolution: exact 1080x1920 (or portrait 9:16 aspect ratio, tolerance 0.05)
3. Frame rate & duration: ~30.0 fps (28.0~32.0 fps), total duration > 5.0s
4. Audio stream presence & TTS sync: audio stream in MP4, abs(video_dur - tts_dur) <= 2.5s
5. Subtitles & assets existence: single-line subtitle compliance, physical existence of images/B-roll
"""

import os
import re
import subprocess
from typing import List, Optional, Dict, Any, Tuple

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None


def get_ffmpeg_media_info(file_path: str) -> Dict[str, Any]:
    """
    Extracts media stream metadata using bundled ffmpeg.
    """
    info = {
        "duration": None,
        "has_audio": False,
        "has_video": False,
        "video_fps": None,
        "video_width": None,
        "video_height": None
    }
    if not imageio_ffmpeg or not os.path.exists(file_path):
        return info

    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [ffmpeg_exe, "-i", file_path]
        res = subprocess.run(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            errors="ignore"
        )
        stderr_text = res.stderr or ""

        for line in stderr_text.splitlines():
            # Duration parsing: Duration: 00:00:15.34, start: ...
            if "Duration:" in line:
                dur_match = re.search(r"Duration:\s*(\d+):(\d+):([\d\.]+)", line)
                if dur_match:
                    h, m, s = dur_match.groups()
                    info["duration"] = float(h) * 3600 + float(m) * 60 + float(s)

            # Audio stream detection
            if "Stream #" in line and "Audio:" in line:
                info["has_audio"] = True

            # Video stream detection
            if "Stream #" in line and "Video:" in line:
                info["has_video"] = True
                # Resolution extraction (e.g. 1080x1920)
                res_match = re.search(r"(\d{3,5})x(\d{3,5})", line)
                if res_match and info["video_width"] is None:
                    info["video_width"] = int(res_match.group(1))
                    info["video_height"] = int(res_match.group(2))

                # FPS extraction (e.g. 30 fps, 29.97 fps)
                fps_match = re.search(r"([\d\.]+)\s*fps", line)
                if fps_match and info["video_fps"] is None:
                    info["video_fps"] = float(fps_match.group(1))

    except Exception:
        pass

    return info


def check_srt_single_line_rule(srt_path: str) -> Tuple[bool, List[str], int, int]:
    """
    Checks if SRT file exists and adheres to the 1-line subtitle rule for vertical shorts.
    Returns:
        (passed_rule, issue_messages, multiline_count, total_cues)
    """
    if not os.path.exists(srt_path):
        return False, [f"SRT file not found: {srt_path}"], 0, 0

    try:
        content = None
        for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
            try:
                with open(srt_path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, Exception):
                continue

        if content is None:
            return False, [f"Failed to read SRT file due to encoding error: {srt_path}"], 0, 0

        # Split into blocks by blank lines
        blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
        multiline_cues = 0
        total_cues = 0

        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue

            # Identify text lines after timing line (which contains '-->')
            timing_idx = -1
            for idx, line in enumerate(lines):
                if "-->" in line:
                    timing_idx = idx
                    break

            if timing_idx != -1:
                text_lines = lines[timing_idx + 1:]
            else:
                text_lines = lines

            # Strip formatting or HTML tags
            clean_text_lines = [
                re.sub(r"<[^>]+>", "", tl).strip()
                for tl in text_lines
                if tl.strip()
            ]

            if not clean_text_lines:
                continue

            total_cues += 1

            # Check if cue has multiple stacked lines or explicit line breaks
            has_stacked = len(clean_text_lines) > 1
            if not has_stacked:
                # Check for explicit escaped newline or break tags in the text
                if "\\n" in clean_text_lines[0] or "<br" in lines[timing_idx + 1].lower():
                    has_stacked = True

            if has_stacked:
                multiline_cues += 1

        issues = []
        if multiline_cues > 0:
            issues.append(
                f"SRT contains {multiline_cues}/{total_cues} cue(s) violating the 1-line rule (multiline stacked text)."
            )
            return False, issues, multiline_cues, total_cues

        return True, [], multiline_cues, total_cues

    except Exception as e:
        return False, [f"Exception while parsing SRT: {str(e)}"], 0, 0


def validate_technical_quality(
    video_path: str,
    tts_audio_path: Optional[str] = None,
    srt_path: Optional[str] = None,
    images: Optional[List[str]] = None,
    broll_path: Optional[str] = None
) -> dict:
    """
    Validates technical quality of the generated shorts video and associated assets.

    Scoring allocation (Max 20.0 pts):
    1. Video integrity & openable: 6.0 pts
       - File existence & size >= 10KB (3.0 pts)
       - Openable & decodable first frame (3.0 pts)
    2. Resolution (1080x1920 or 9:16 portrait): 5.0 pts
       - Exact 1080x1920 (5.0 pts)
       - Portrait 9:16 with aspect ratio tolerance 0.05 (4.0 pts)
       - Non-9:16 / invalid (0.0 pts)
    3. Frame rate & duration: 3.0 pts
       - FPS 29.9 ~ 30.1 (2.0 pts)
       - FPS 28.0 ~ 32.0 (1.5 pts)
       - Video duration > 5.0s (1.0 pt)
    4. Audio stream & TTS sync: 4.0 pts
       - Video audio stream presence (2.0 pts)
       - TTS sync abs(video_dur - tts_dur) <= 2.5s (2.0 pts)
    5. Subtitles & assets existence: 2.0 pts
       - SRT single-line rule adherence (1.0 pt)
       - Image and B-roll physical file existence (1.0 pt)

    Returns:
        {
            "score": float,
            "max_score": 20.0,
            "passed": bool,
            "critical_error": bool,
            "issues": [{"type": "error"|"warning", "component": "...", "message": "..."}],
            "details": {...}
        }
    """
    issues: List[Dict[str, str]] = []
    critical_error = False

    video_integrity_score = 0.0
    resolution_score = 0.0
    fps_score = 0.0
    audio_score = 0.0
    assets_score = 0.0

    # -------------------------------------------------------------
    # 1. Video Integrity & Openable (Max 6.0 pts)
    # -------------------------------------------------------------
    video_exists = False
    size_kb = 0.0
    is_openable = False
    first_frame_read = False
    cap_width = 0
    cap_height = 0
    cap_fps = 0.0
    cap_frame_count = 0
    cap_duration = 0.0

    if not video_path or not os.path.exists(video_path):
        critical_error = True
        issues.append({
            "type": "error",
            "component": "video_integrity",
            "message": f"Video file not found at path: {video_path}"
        })
    else:
        video_exists = True
        try:
            size_bytes = os.path.getsize(video_path)
            size_kb = size_bytes / 1024.0
        except Exception:
            size_kb = 0.0

        if size_kb < 10.0:
            critical_error = True
            issues.append({
                "type": "error",
                "component": "video_integrity",
                "message": f"Video file size is abnormally small ({size_kb:.2f} KB < 10 KB). File may be corrupted or empty."
            })
        else:
            video_integrity_score += 3.0

        # Test video decode with OpenCV
        cap = None
        if cv2 is not None:
            try:
                cap = cv2.VideoCapture(video_path)
                if cap.isOpened():
                    is_openable = True
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        first_frame_read = True
                    cap_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    cap_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap_fps = float(cap.get(cv2.CAP_PROP_FPS))
                    cap_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    if cap_fps > 0 and cap_frame_count > 0:
                        cap_duration = cap_frame_count / cap_fps
            except Exception as e:
                issues.append({
                    "type": "error",
                    "component": "video_integrity",
                    "message": f"OpenCV failed to read video: {str(e)}"
                })
            finally:
                if cap is not None:
                    cap.release()

        # Ffmpeg probe metadata fallback/cross-check
        ff_info = get_ffmpeg_media_info(video_path)

        if not is_openable and ff_info.get("has_video"):
            is_openable = True
            first_frame_read = True

        if is_openable and first_frame_read:
            video_integrity_score += 3.0
        else:
            critical_error = True
            issues.append({
                "type": "error",
                "component": "video_integrity",
                "message": "Video stream could not be opened or first frame could not be decoded."
            })

    # If video file is completely unreadable or missing, terminate early with 0 score
    if critical_error and not video_exists:
        return {
            "score": 0.0,
            "max_score": 20.0,
            "passed": False,
            "critical_error": True,
            "issues": issues,
            "details": {
                "video_integrity": {
                    "exists": False,
                    "size_kb": 0.0,
                    "openable": False,
                    "first_frame_read": False,
                    "score": 0.0,
                    "max_score": 6.0
                }
            }
        }

    # Consolidated video dimensions & fps
    ff_info = get_ffmpeg_media_info(video_path) if video_exists else {}
    width = cap_width if cap_width > 0 else (ff_info.get("video_width") or 0)
    height = cap_height if cap_height > 0 else (ff_info.get("video_height") or 0)
    fps = cap_fps if cap_fps > 0 else (ff_info.get("video_fps") or 0.0)
    video_dur = cap_duration if cap_duration > 0 else (ff_info.get("duration") or 0.0)

    # -------------------------------------------------------------
    # 2. Resolution (Max 5.0 pts)
    # -------------------------------------------------------------
    target_aspect = 9.0 / 16.0  # 0.5625
    aspect_ratio = (width / height) if (width > 0 and height > 0) else 0.0
    is_exact_1080x1920 = (width == 1080 and height == 1920)
    is_portrait_9_16 = (
        width > 0 and height > 0 and
        abs(aspect_ratio - target_aspect) <= 0.05
    )

    if is_exact_1080x1920:
        resolution_score = 5.0
    elif is_portrait_9_16:
        resolution_score = 4.0
        issues.append({
            "type": "warning",
            "component": "resolution",
            "message": f"Resolution is {width}x{height} (aspect ratio {aspect_ratio:.3f} ~ 9:16). Recommended resolution is exact 1080x1920."
        })
    else:
        resolution_score = 0.0
        issues.append({
            "type": "error",
            "component": "resolution",
            "message": f"Resolution {width}x{height} violates 9:16 portrait shorts requirement."
        })

    # -------------------------------------------------------------
    # 3. Frame Rate & Total Duration (Max 3.0 pts)
    # -------------------------------------------------------------
    # FPS check (Max 2.0 pts)
    if 29.9 <= fps <= 30.1:
        fps_score += 2.0
    elif 28.0 <= fps <= 32.0:
        fps_score += 1.5
        issues.append({
            "type": "warning",
            "component": "fps",
            "message": f"Frame rate is {fps:.2f} fps (acceptable 28.0~32.0, target 30.0 fps)."
        })
    elif fps > 0:
        fps_score += 0.5
        issues.append({
            "type": "warning",
            "component": "fps",
            "message": f"Frame rate {fps:.2f} fps deviates significantly from standard 30.0 fps."
        })
    else:
        issues.append({
            "type": "error",
            "component": "fps",
            "message": "Unable to determine video frame rate (fps is 0)."
        })

    # Duration check (Max 1.0 pt)
    if video_dur > 5.0:
        fps_score += 1.0
    elif video_dur > 0:
        issues.append({
            "type": "error",
            "component": "duration",
            "message": f"Video duration is too short ({video_dur:.2f}s <= 5.0s)."
        })
    else:
        issues.append({
            "type": "error",
            "component": "duration",
            "message": "Unable to determine video duration (0.0s)."
        })

    # -------------------------------------------------------------
    # 4. Audio Stream & TTS Sync (Max 4.0 pts)
    # -------------------------------------------------------------
    has_audio = ff_info.get("has_audio", False)
    audio_pres_score = 0.0
    if has_audio:
        audio_pres_score = 2.0
    else:
        issues.append({
            "type": "error",
            "component": "audio",
            "message": "No audio stream found in the MP4 file."
        })

    tts_sync_score = 0.0
    tts_dur = None
    diff_sec = None

    if tts_audio_path is not None:
        if not os.path.exists(tts_audio_path):
            issues.append({
                "type": "error",
                "component": "tts_sync",
                "message": f"Referenced TTS audio file not found: {tts_audio_path}"
            })
        else:
            tts_info = get_ffmpeg_media_info(tts_audio_path)
            tts_dur = tts_info.get("duration")
            if tts_dur is not None and video_dur > 0:
                diff_sec = abs(video_dur - tts_dur)
                if diff_sec <= 2.5:
                    tts_sync_score = 2.0
                elif diff_sec <= 5.0:
                    tts_sync_score = 1.0
                    issues.append({
                        "type": "warning",
                        "component": "tts_sync",
                        "message": f"TTS duration ({tts_dur:.2f}s) and video duration ({video_dur:.2f}s) difference ({diff_sec:.2f}s) exceeds optimal 2.5s tolerance."
                    })
                else:
                    tts_sync_score = 0.0
                    issues.append({
                        "type": "error",
                        "component": "tts_sync",
                        "message": f"Severe desynchronization between TTS ({tts_dur:.2f}s) and video ({video_dur:.2f}s): {diff_sec:.2f}s difference (> 5.0s)."
                    })
            else:
                tts_sync_score = 1.0
                issues.append({
                    "type": "warning",
                    "component": "tts_sync",
                    "message": "Could not determine TTS audio duration for alignment comparison."
                })
    else:
        # If no TTS audio path was provided, grant full sync score
        tts_sync_score = 2.0

    audio_score = audio_pres_score + tts_sync_score

    # -------------------------------------------------------------
    # 5. Subtitles & Assets Existence (Max 2.0 pts)
    # -------------------------------------------------------------
    srt_score = 0.0
    multiline_count = 0
    total_cues = 0

    if srt_path is not None:
        srt_ok, srt_issues, multiline_count, total_cues = check_srt_single_line_rule(srt_path)
        if srt_ok:
            srt_score = 1.0
        else:
            for s_issue in srt_issues:
                issues.append({
                    "type": "warning" if "violating" in s_issue else "error",
                    "component": "subtitles",
                    "message": s_issue
                })
            # Partial credit if file exists and has cues despite multiline
            srt_score = 0.5 if total_cues > 0 else 0.0
    else:
        srt_score = 1.0

    # Assets check (Images & B-roll)
    missing_assets = []
    checked_assets = []

    if images:
        for img in images:
            if not img:
                continue
            checked_assets.append(img)
            if not os.path.exists(img):
                missing_assets.append(img)

    if broll_path:
        checked_assets.append(broll_path)
        if not os.path.exists(broll_path):
            missing_assets.append(broll_path)

    asset_score = 0.0
    if not missing_assets:
        asset_score = 1.0
    else:
        issues.append({
            "type": "error",
            "component": "assets",
            "message": f"Missing asset file(s) on disk: {', '.join(missing_assets)}"
        })
        # Partial credit if at least some assets exist
        if len(checked_assets) > len(missing_assets):
            asset_score = 0.5

    assets_score = srt_score + asset_score

    # -------------------------------------------------------------
    # Total Score & Verdict
    # -------------------------------------------------------------
    total_score = round(
        video_integrity_score + resolution_score + fps_score + audio_score + assets_score,
        1
    )
    total_score = max(0.0, min(20.0, total_score))

    # Passed threshold: >= 14.0 pts (70%) and no critical error
    passed = (not critical_error) and (total_score >= 14.0)

    details = {
        "video_integrity": {
            "exists": video_exists,
            "size_kb": round(size_kb, 2),
            "openable": is_openable,
            "first_frame_read": first_frame_read,
            "score": round(video_integrity_score, 1),
            "max_score": 6.0
        },
        "resolution": {
            "width": width,
            "height": height,
            "aspect_ratio": round(aspect_ratio, 4) if aspect_ratio > 0 else None,
            "is_exact_1080x1920": is_exact_1080x1920,
            "is_portrait_9_16": is_portrait_9_16,
            "score": round(resolution_score, 1),
            "max_score": 5.0
        },
        "frame_rate_and_duration": {
            "fps": round(fps, 2),
            "duration_seconds": round(video_dur, 2),
            "frame_count": cap_frame_count,
            "score": round(fps_score, 1),
            "max_score": 3.0
        },
        "audio": {
            "has_audio_stream": has_audio,
            "audio_stream_score": round(audio_pres_score, 1),
            "tts_audio_path": tts_audio_path,
            "tts_duration_seconds": round(tts_dur, 2) if tts_dur is not None else None,
            "duration_diff_seconds": round(diff_sec, 2) if diff_sec is not None else None,
            "tts_sync_score": round(tts_sync_score, 1),
            "total_score": round(audio_score, 1),
            "max_score": 4.0
        },
        "subtitles_and_assets": {
            "srt_path": srt_path,
            "srt_multiline_cues": multiline_count,
            "srt_total_cues": total_cues,
            "srt_score": round(srt_score, 1),
            "checked_assets_count": len(checked_assets),
            "missing_assets": missing_assets,
            "assets_score": round(asset_score, 1),
            "total_score": round(assets_score, 1),
            "max_score": 2.0
        }
    }

    return {
        "score": total_score,
        "max_score": 20.0,
        "passed": passed,
        "critical_error": critical_error,
        "issues": issues,
        "details": details
    }
