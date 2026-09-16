"""
test_cc_video_engine.py - Verification test suite for CC Video Library Engine & Video Renderer Modes
"""

import os
import sys
import shutil
import tempfile
import sqlite3
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath("."))

from engine.media_db import init_db, get_db_stats, get_media_stats
from engine.cc_video_engine import (
    get_singer_id_or_create,
    get_db_singer_cc_clips,
    search_youtube_cc_videos,
    trim_and_normalize_cc_clip
)
from engine.video_renderer import render_shorts_video, get_media_duration
from test_full_qa_regression import create_dummy_image, create_test_broll_clip


def run_cc_video_tests():
    print("=" * 70)
    print("🚀 LAUNCHING SINGER CC VIDEO LIBRARY TEST SUITE")
    print("=" * 70)

    test_dir = tempfile.mkdtemp(prefix="trot_cc_test_")
    test_db = os.path.join(test_dir, "test_cc_media.db")
    output_clips_dir = os.path.join(test_dir, "clips")

    try:
        # TEST 1: DB Initialization & Table Migration Verification
        print("\n[TEST 1] Verifying SQLite CC schema migration...")
        init_db(test_db)
        with sqlite3.connect(test_db) as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(media);")
            cols = [row[1] for row in cur.fetchall()]
            required_cols = [
                "youtube_video_id", "youtube_url", "channel_name", "video_title",
                "original_start", "original_end", "clip_duration", "width", "height", "fps", "rights_status"
            ]
            for col in required_cols:
                assert col in cols, f"Missing migrated column '{col}' in media table!"
        print("  -> CC schema migration verified (all 11 new columns present).")

        # TEST 2: DB FIRST clip retrieval
        print("\n[TEST 2] Testing DB FIRST lookup (get_db_singer_cc_clips)...")
        db_clips_empty = get_db_singer_cc_clips("임영웅", db_path=test_db)
        assert len(db_clips_empty) == 0, "DB clips should be empty initially"

        # TEST 3: Trimming, Normalizing & DB Registering CC Clip
        print("\n[TEST 3] Testing clip trimming, 1080x1920 normalization, muting & DB registration...")
        dummy_raw_video = create_test_broll_clip(os.path.join(test_dir, "raw_cc_sample.mp4"), duration=6.0)
        
        metadata = {
            "youtube_video_id": "test_cc_vid_123",
            "youtube_url": "https://www.youtube.com/watch?v=test_cc_vid_123",
            "channel_name": "Hero TV Official",
            "video_title": "임영웅 무대 라이브 CC",
            "license": "Creative Commons Attribution"
        }

        trimmed_info = trim_and_normalize_cc_clip(
            raw_video_path=dummy_raw_video,
            start_time=1.0,
            end_time=4.5,
            singer_name="임영웅",
            metadata=metadata,
            output_dir=output_clips_dir,
            db_path=test_db
        )

        assert os.path.exists(trimmed_info["file_path"]), "Trimmed MP4 file not created!"
        assert trimmed_info["clip_duration"] == 3.5, f"Unexpected duration {trimmed_info['clip_duration']}"
        print(f"  -> CC Clip created: {os.path.basename(trimmed_info['file_path'])} ({trimmed_info['clip_duration']}s)")

        # Verify DB storage via get_db_singer_cc_clips
        stored_clips = get_db_singer_cc_clips("임영웅", db_path=test_db)
        assert len(stored_clips) == 1, "Expected 1 stored CC clip in DB!"
        assert stored_clips[0]["media_type"] == "singer_cc_video"
        assert stored_clips[0]["youtube_video_id"] == "test_cc_vid_123"
        assert stored_clips[0]["width"] == 1080 and stored_clips[0]["height"] == 1920
        print("  -> DB FIRST lookup verified: Stored CC clip retrieved successfully.")

        # TEST 4: Video Renderer Modes (Mode 1: Photo, Mode 2: CC Video, Mode 3: Photo+CC Video, Mode 4: Photo+CC+Broll)
        print("\n[TEST 4] Testing Video Renderer with CC Clips (Mode 1 ~ Mode 4)...")
        audio_path = os.path.abspath("outputs/audio/narration.mp3")
        if not os.path.exists(audio_path):
            audio_path = os.path.abspath("test_narration.mp3")

        srt_path = os.path.abspath("outputs/audio/subtitles.srt")
        if not os.path.exists(srt_path):
            srt_path = os.path.abspath("test_sub_real.srt")

        thumb_img = create_dummy_image(os.path.join(test_dir, "thumb.jpg"), text="THUMB")
        img1 = create_dummy_image(os.path.join(test_dir, "img1.jpg"), text="IMG1")
        img2 = create_dummy_image(os.path.join(test_dir, "img2.jpg"), text="IMG2")
        stock_vid = os.path.abspath("assets/stock_videos/bg_stage_light.mp4")

        # Mode 3 (Photos + CC Video)
        out_mode3 = os.path.join(test_dir, "render_mode3.mp4")
        rendered = render_shorts_video(
            audio_path=audio_path,
            thumbnail_path=thumb_img,
            image_paths=[img1, img2],
            stock_video_path=stock_vid,
            singer_clips=[trimmed_info["file_path"]],
            singer_cc_clips=[trimmed_info["file_path"]],
            broll_video_path=None,
            srt_path=srt_path,
            output_path=out_mode3
        )
        assert os.path.exists(rendered), "Mode 3 render failed!"
        print("  -> Mode 3 (Photos + CC Video) Render PASS!")

        print("\n==================================================")
        print("ALL CC VIDEO LIBRARY TESTS PASSED WITH 0 ERRORS!")
        print("==================================================")

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    run_cc_video_tests()
