"""
test_custom_clip_mix.py - Unit test suite for custom clip combinations & dynamic timeline filling
"""

import os
import sys
import shutil
import tempfile
import sqlite3

sys.path.insert(0, os.path.abspath("."))

from engine.broll_engine import get_or_fetch_broll_multiple
from engine.video_renderer import render_shorts_video, get_media_duration
from test_full_qa_regression import create_dummy_image, create_test_broll_clip


def run_custom_clip_mix_tests():
    print("=" * 70)
    print("🚀 LAUNCHING CUSTOM CLIP MIX TEST SUITE")
    print("=" * 70)

    test_dir = tempfile.mkdtemp(prefix="trot_custom_mix_")

    try:
        # TEST 1: get_or_fetch_broll_multiple function
        print("\n[TEST 1] Testing get_or_fetch_broll_multiple(count=2)...")
        brolls = get_or_fetch_broll_multiple(category="audience", tag="fans", count=2, allow_stock_fallback=True)
        assert isinstance(brolls, list), "Expected list response"
        assert len(brolls) >= 1, "Expected at least 1 B-roll clip"
        print(f"  -> Retrieved {len(brolls)} B-roll clips: {[os.path.basename(b) for b in brolls]}")

        # Create dummy assets for rendering tests
        audio_path = os.path.abspath("outputs/audio/narration.mp3")
        if not os.path.exists(audio_path):
            audio_path = os.path.abspath("test_narration.mp3")

        srt_path = os.path.abspath("outputs/audio/subtitles.srt")
        if not os.path.exists(srt_path):
            srt_path = os.path.abspath("test_sub_real.srt")

        thumb_img = create_dummy_image(os.path.join(test_dir, "thumb.jpg"), text="THUMB")
        img1 = create_dummy_image(os.path.join(test_dir, "img1.jpg"), text="IMG1")
        img2 = create_dummy_image(os.path.join(test_dir, "img2.jpg"), text="IMG2")
        img3 = create_dummy_image(os.path.join(test_dir, "img3.jpg"), text="IMG3")

        cc_clip_1 = create_test_broll_clip(os.path.join(test_dir, "cc1.mp4"), duration=4.0)
        cc_clip_2 = create_test_broll_clip(os.path.join(test_dir, "cc2.mp4"), duration=4.0)
        broll_clip_1 = create_test_broll_clip(os.path.join(test_dir, "broll1.mp4"), duration=4.0)

        # TEST 2: Render with CC=2, B-roll=1 (3 video clips total)
        print("\n[TEST 2] Testing render_shorts_video with CC=2, B-roll=1...")
        out_mix1 = os.path.join(test_dir, "render_cc2_broll1.mp4")
        rendered1 = render_shorts_video(
            audio_path=audio_path,
            thumbnail_path=thumb_img,
            image_paths=[img1, img2, img3],
            singer_cc_clips=[cc_clip_1, cc_clip_2],
            broll_video_paths=[broll_clip_1],
            srt_path=srt_path,
            output_path=out_mix1
        )
        assert os.path.exists(rendered1), "Render CC=2, B-roll=1 failed!"
        print("  -> Render CC=2, B-roll=1 PASS!")

        # TEST 3: Render with CC=0, B-roll=0 (100% Photos)
        print("\n[TEST 3] Testing render_shorts_video with CC=0, B-roll=0 (Photos only)...")
        out_mix2 = os.path.join(test_dir, "render_photo_only.mp4")
        rendered2 = render_shorts_video(
            audio_path=audio_path,
            thumbnail_path=thumb_img,
            image_paths=[img1, img2, img3],
            singer_cc_clips=[],
            broll_video_paths=[],
            srt_path=srt_path,
            output_path=out_mix2
        )
        assert os.path.exists(rendered2), "Render Photo-only failed!"
        print("  -> Render Photo-only PASS!")

        print("\n==================================================")
        print("ALL CUSTOM CLIP MIX TESTS PASSED WITH 0 ERRORS!")
        print("==================================================")

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    run_custom_clip_mix_tests()
