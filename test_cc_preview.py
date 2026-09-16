"""
test_cc_preview.py - Verification test suite for CC Video 9:16 real-time crop preview extraction
"""

import os
import sys
import shutil
import tempfile

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath("."))

from engine.cc_video_engine import get_cc_crop_preview_frame
from test_full_qa_regression import create_test_broll_clip
from PIL import Image


def run_preview_tests():
    print("=" * 70)
    print("🚀 LAUNCHING CC VIDEO REAL-TIME CROP PREVIEW TEST SUITE")
    print("=" * 70)

    test_dir = tempfile.mkdtemp(prefix="trot_pv_test_")

    try:
        raw_video = create_test_broll_clip(os.path.join(test_dir, "raw_sample.mp4"), duration=4.0)

        # TEST 1: Extract Crop Preview Frame (Center 50%)
        print("\n[TEST 1] Testing get_cc_crop_preview_frame at crop_x = 50%...")
        pv_path1 = get_cc_crop_preview_frame(raw_video, sample_time=1.0, crop_x_percent=50.0, output_dir=test_dir)
        assert pv_path1 is not None and os.path.exists(pv_path1), "Preview JPEG 50% not created!"
        with Image.open(pv_path1) as im:
            w, h = im.size
            assert w == 1080 and h == 1920, f"Unexpected dimensions {w}x{h}, expected 1080x1920!"
        print(f"  -> Preview 50% PASS! Dimensions: {w}x{h}")

        # TEST 2: Extract Crop Preview Frame (Left 20%)
        print("\n[TEST 2] Testing get_cc_crop_preview_frame at crop_x = 20%...")
        pv_path2 = get_cc_crop_preview_frame(raw_video, sample_time=1.0, crop_x_percent=20.0, output_dir=test_dir)
        assert pv_path2 is not None and os.path.exists(pv_path2), "Preview JPEG 20% not created!"
        with Image.open(pv_path2) as im:
            w, h = im.size
            assert w == 1080 and h == 1920, f"Unexpected dimensions {w}x{h}, expected 1080x1920!"
        print(f"  -> Preview 20% PASS! Dimensions: {w}x{h}")

        print("\n==================================================")
        print("ALL CC CROP PREVIEW TESTS PASSED WITH 0 ERRORS!")
        print("==================================================")

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    run_preview_tests()
