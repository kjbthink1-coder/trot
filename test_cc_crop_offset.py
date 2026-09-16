"""
test_cc_crop_offset.py - Verification test suite for CC Video horizontal crop offset & face auto-centering
"""

import os
import sys
import shutil
import tempfile
import sqlite3

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath("."))

from engine.media_db import init_db
from engine.cc_video_engine import (
    trim_and_normalize_cc_clip,
    detect_video_face_center_percent,
    get_db_singer_cc_clips
)
from test_full_qa_regression import create_test_broll_clip, get_video_stream_info


def run_crop_offset_tests():
    print("=" * 70)
    print("🚀 LAUNCHING CC VIDEO HORIZONTAL CROP OFFSET TEST SUITE")
    print("=" * 70)

    test_dir = tempfile.mkdtemp(prefix="trot_crop_test_")
    test_db = os.path.join(test_dir, "test_crop_media.db")
    clips_dir = os.path.join(test_dir, "clips")

    try:
        init_db(test_db)
        raw_video = create_test_broll_clip(os.path.join(test_dir, "raw_sample.mp4"), duration=5.0)

        # TEST 1: detect_video_face_center_percent fallback & detection
        print("\n[TEST 1] Testing detect_video_face_center_percent...")
        center_pct = detect_video_face_center_percent(raw_video, sample_time=1.0)
        print(f"  -> Face center percent detected: {center_pct:.1f}%")
        assert 0.0 <= center_pct <= 100.0, "Percent out of bounds!"

        # TEST 2: Left Crop Offset (crop_x_percent = 20%)
        print("\n[TEST 2] Testing Left Crop Offset (crop_x_percent = 20%)...")
        meta1 = {"youtube_video_id": "test_left_001", "youtube_url": "https://youtube.com/watch?v=test_left_001"}
        res1 = trim_and_normalize_cc_clip(
            raw_video_path=raw_video,
            start_time=0.5,
            end_time=3.8,
            singer_name="임영웅",
            metadata=meta1,
            crop_x_percent=20.0,
            output_dir=clips_dir,
            db_path=test_db
        )
        assert os.path.exists(res1["file_path"]), "Left crop file not created!"
        info1 = get_video_stream_info(res1["file_path"])
        assert info1["width"] == 1080 and info1["height"] == 1920, "Dimensions mismatch!"
        print("  -> Left Crop 20% PASS!")

        # TEST 3: Right Crop Offset (crop_x_percent = 80%)
        print("\n[TEST 3] Testing Right Crop Offset (crop_x_percent = 80%)...")
        meta2 = {"youtube_video_id": "test_right_002", "youtube_url": "https://youtube.com/watch?v=test_right_002"}
        res2 = trim_and_normalize_cc_clip(
            raw_video_path=raw_video,
            start_time=0.5,
            end_time=3.8,
            singer_name="임영웅",
            metadata=meta2,
            crop_x_percent=80.0,
            output_dir=clips_dir,
            db_path=test_db
        )
        assert os.path.exists(res2["file_path"]), "Right crop file not created!"
        info2 = get_video_stream_info(res2["file_path"])
        assert info2["width"] == 1080 and info2["height"] == 1920, "Dimensions mismatch!"
        print("  -> Right Crop 80% PASS!")

        print("\n==================================================")
        print("ALL HORIZONTAL CROP OFFSET TESTS PASSED WITH 0 ERRORS!")
        print("==================================================")

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    run_crop_offset_tests()
