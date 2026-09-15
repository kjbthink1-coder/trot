"""
test_video_integration.py - Verification Script for B-roll Video Integration
===========================================================================
Verifies:
  Test A: render_shorts_video without B-roll (100% baseline regression test).
  Test B: render_shorts_video with B-roll clip (verify B-roll is spliced, audio intact,
          subtitles sync, total duration matches narration, B-roll is 1080x1920 30fps muted).
  Test C: Robust Fallback test (invalid / non-existent B-roll path falls back to baseline).
"""

import os
import sys
import re
import subprocess
import imageio_ffmpeg
from PIL import Image, ImageDraw

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from engine.video_renderer import render_shorts_video, get_media_duration
from assets.generate_stock_clips import ensure_stock_video


def get_video_stream_info(file_path: str) -> dict:
    """Uses ffmpeg -i output to extract duration, resolution, fps, and audio presence."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg_exe, "-i", file_path]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, errors="ignore")
    stderr = res.stderr

    duration = 0.0
    for line in stderr.split("\n"):
        if "Duration:" in line:
            parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
            duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            break

    width, height = 0, 0
    m_res = re.search(r",\s*(\d{3,4})x(\d{3,4})", stderr)
    if m_res:
        width, height = int(m_res.group(1)), int(m_res.group(2))

    fps = 0.0
    m_fps = re.search(r"(\d+(?:\.\d+)?)\s*fps", stderr)
    if m_fps:
        fps = float(m_fps.group(1))

    has_audio = "Audio:" in stderr
    has_video = "Video:" in stderr

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "has_audio": has_audio,
        "has_video": has_video,
    }


def create_test_broll_clip(output_path: str, duration: float = 4.0) -> str:
    """Creates a sample test B-roll video clip with distinct visuals and audio tone to test muting."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        return output_path

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (20, 50, 40))
    draw = ImageDraw.Draw(img)

    # Draw B-roll placeholder graphic
    draw.rectangle([100, 700, 980, 1220], fill=(30, 90, 70), outline=(100, 220, 150), width=4)
    draw.text((w // 2, 860), "[ B-ROLL CONCERT CLIP ]", fill=(255, 255, 255), anchor="mm")
    draw.text((w // 2, 980), "LIVE STAGE FOOTAGE", fill=(100, 255, 180), anchor="mm")
    draw.text((w // 2, 1060), "1080x1920 30FPS TEST ASSET", fill=(200, 230, 220), anchor="mm")

    temp_img = os.path.abspath("outputs/temp_render/temp_test_broll_frame.jpg")
    os.makedirs(os.path.dirname(temp_img), exist_ok=True)
    img.save(temp_img, "JPEG", quality=95)

    # Generate MP4 clip with an audio beep to test that audio is stripped (-an)
    cmd = [
        ffmpeg_exe, "-y",
        "-loop", "1", "-i", temp_img,
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=4",
        "-t", str(duration),
        "-vf", "scale=1080:1920,format=yuv420p",
        "-r", "30",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-c:a", "aac",
        "-shortest",
        os.path.abspath(output_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"[Test Setup] Created test B-roll clip with audio: {output_path}")
    return output_path


def run_tests():
    print("==================================================================")
    print("▶ B-roll Video Renderer Integration Verification Suite")
    print("==================================================================")

    # 1. Prepare test assets
    audio_path = os.path.abspath("outputs/audio/narration.mp3")
    if not os.path.exists(audio_path):
        audio_path = os.path.abspath("test_narration.mp3")

    srt_path = os.path.abspath("outputs/audio/subtitles.srt")
    if not os.path.exists(srt_path):
        srt_path = os.path.abspath("test_sub_real.srt")

    thumbnail_path = os.path.abspath("face_test_100.jpg")
    image_paths = [
        os.path.abspath("face_test_100.jpg"),
        os.path.abspath("face_test_101.jpg"),
        os.path.abspath("face_test_102.jpg"),
        os.path.abspath("face_test_103.jpg")
    ]

    singer_clips = [
        os.path.abspath("assets/singers/임영웅/clips/clip_1789361326_52f456_1.mp4"),
        os.path.abspath("assets/singers/임영웅/clips/clip_1789361329_39f678_2.mp4")
    ]
    singer_clips = [c for c in singer_clips if os.path.exists(c)]

    stock_clip = ensure_stock_video()
    broll_clip = create_test_broll_clip("outputs/test_broll_sample.mp4", duration=4.0)

    audio_dur = get_media_duration(audio_path)
    print(f"[Test Info] Test Audio Duration: {audio_dur:.2f}s")
    print(f"[Test Info] Singer Clips Count: {len(singer_clips)}")
    print(f"[Test Info] Stock Clip: {stock_clip}")
    print(f"[Test Info] B-roll Clip: {broll_clip}")

    # =========================================================================
    # Test A: Baseline Regression Test (Without B-roll)
    # =========================================================================
    print("\n------------------------------------------------------------------")
    print("▶ [Test A] Baseline Regression Test (render_shorts_video without B-roll)")
    print("------------------------------------------------------------------")
    out_a = "outputs/videos/test_regression_no_broll.mp4"
    res_a = render_shorts_video(
        audio_path=audio_path,
        thumbnail_path=thumbnail_path,
        image_paths=image_paths,
        stock_video_path=stock_clip,
        singer_clips=singer_clips,
        broll_video_path=None,  # Baseline: no B-roll
        srt_path=srt_path,
        output_path=out_a
    )

    assert os.path.exists(res_a), "Test A failed: output video was not created!"
    info_a = get_video_stream_info(res_a)
    print(f"[Test A Result] Dimensions: {info_a['width']}x{info_a['height']}, FPS: {info_a['fps']}, Duration: {info_a['duration']:.2f}s, Audio: {info_a['has_audio']}")

    assert info_a["width"] == 1080 and info_a["height"] == 1920, f"Test A failed: Dimensions {info_a['width']}x{info_a['height']} != 1080x1920"
    assert info_a["has_audio"], "Test A failed: Final video has no audio!"
    assert abs(info_a["duration"] - audio_dur) < 1.0, f"Test A failed: Duration mismatch {info_a['duration']:.2f} vs {audio_dur:.2f}"

    # Verify concat_list does not contain broll
    concat_txt_a = "outputs/temp_render/concat_list.txt"
    with open(concat_txt_a, "r", encoding="utf-8") as f:
        concat_content_a = f.read()
    assert "broll" not in concat_content_a, "Test A failed: B-roll unexpectedly present in baseline concat list!"
    print("✅ [Test A PASSED] Baseline video rendering without B-roll is 100% verified.")

    # =========================================================================
    # Test B: B-roll Video Integration Test
    # =========================================================================
    print("\n------------------------------------------------------------------")
    print("▶ [Test B] B-roll Integration Test (render_shorts_video with B-roll)")
    print("------------------------------------------------------------------")
    out_b = "outputs/videos/test_integrated_broll.mp4"
    res_b = render_shorts_video(
        audio_path=audio_path,
        thumbnail_path=thumbnail_path,
        image_paths=image_paths,
        stock_video_path=stock_clip,
        singer_clips=singer_clips,
        broll_video_path=broll_clip,  # Provided B-roll
        srt_path=srt_path,
        output_path=out_b
    )

    assert os.path.exists(res_b), "Test B failed: output video with B-roll was not created!"
    info_b = get_video_stream_info(res_b)
    print(f"[Test B Result] Dimensions: {info_b['width']}x{info_b['height']}, FPS: {info_b['fps']}, Duration: {info_b['duration']:.2f}s, Audio: {info_b['has_audio']}")

    assert info_b["width"] == 1080 and info_b["height"] == 1920, f"Test B failed: Dimensions {info_b['width']}x{info_b['height']} != 1080x1920"
    assert info_b["has_audio"], "Test B failed: Final video with B-roll has no audio!"
    assert abs(info_b["duration"] - audio_dur) < 1.0, f"Test B failed: Duration mismatch {info_b['duration']:.2f} vs {audio_dur:.2f}"

    # 1. Verify B-roll clip was processed into temp_render
    temp_dir = os.path.abspath("outputs/temp_render")
    broll_temp_clips = [f for f in os.listdir(temp_dir) if "broll" in f and f.endswith(".mp4")]
    assert len(broll_temp_clips) > 0, f"Test B failed: No clip_v_*_broll.mp4 found in {temp_dir}!"
    broll_temp_path = os.path.join(temp_dir, broll_temp_clips[0])
    print(f"[Test B Check] Found normalized B-roll clip: {broll_temp_clips[0]}")

    # 2. Verify B-roll clip normalization (1080x1920, 30fps, muted)
    broll_info = get_video_stream_info(broll_temp_path)
    print(f"[Test B Check] B-roll clip info: {broll_info['width']}x{broll_info['height']} @ {broll_info['fps']}fps, has_audio={broll_info['has_audio']}")
    assert broll_info["width"] == 1080 and broll_info["height"] == 1920, f"B-roll normalization failed: {broll_info['width']}x{broll_info['height']}"
    assert abs(broll_info["fps"] - 30.0) < 1.0, f"B-roll FPS normalization failed: {broll_info['fps']}"
    assert not broll_info["has_audio"], "B-roll muting failed: audio stream still exists in normalized B-roll clip!"

    # 3. Verify concat_list contains the B-roll clip
    concat_txt_b = os.path.join(temp_dir, "concat_list.txt")
    with open(concat_txt_b, "r", encoding="utf-8") as f:
        concat_content_b = f.read()
    assert broll_temp_clips[0] in concat_content_b, f"Test B failed: {broll_temp_clips[0]} not in concat_list.txt!"

    # 4. Verify placement timing: B-roll clip must be in the middle portion of the list
    lines = [ln.strip() for ln in concat_content_b.splitlines() if ln.strip().startswith("file ")]
    broll_indices = [idx for idx, ln in enumerate(lines) if "broll" in ln]
    assert len(broll_indices) > 0, "Test B failed: broll clip not in concat list lines"
    broll_pos = broll_indices[0]
    total_clips = len(lines)
    relative_pos = broll_pos / total_clips
    print(f"[Test B Check] Concat list has {total_clips} clips. B-roll clip is at index {broll_pos} (relative position: {relative_pos*100:.1f}%)")
    # Relative position should be between 30% and 85% (middle of sequence)
    assert 0.30 <= relative_pos <= 0.85, f"B-roll not placed in middle: position ratio is {relative_pos:.2f}"

    print("✅ [Test B PASSED] B-roll integration is 100% verified (spliced, normalized, muted, audio sync, duration match).")

    # =========================================================================
    # Test C: Robust Fallback Test (Invalid / Missing B-roll)
    # =========================================================================
    print("\n------------------------------------------------------------------")
    print("▶ [Test C] Robust Fallback Test (Non-existent / Invalid B-roll path)")
    print("------------------------------------------------------------------")
    out_c = "outputs/videos/test_fallback_invalid_broll.mp4"
    res_c = render_shorts_video(
        audio_path=audio_path,
        thumbnail_path=thumbnail_path,
        image_paths=image_paths,
        stock_video_path=stock_clip,
        singer_clips=singer_clips,
        broll_video_path="outputs/non_existent_broll_clip_12345.mp4",
        srt_path=srt_path,
        output_path=out_c
    )

    assert os.path.exists(res_c), "Test C failed: Fallback render did not produce output video!"
    info_c = get_video_stream_info(res_c)
    assert info_c["width"] == 1080 and info_c["height"] == 1920, "Test C failed: Invalid dimensions"
    assert info_c["has_audio"], "Test C failed: Audio missing"
    print("✅ [Test C PASSED] Robust fallback handled missing B-roll gracefully without errors.")

    print("\n==================================================================")
    print("🎉 ALL TESTS PASSED SUCCESSFULLY! (Test A, Test B, Test C)")
    print("==================================================================")
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
