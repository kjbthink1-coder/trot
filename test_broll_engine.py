"""
test_broll_engine.py - Standalone Unit & Integration Tests for B-roll Engine
============================================================================
Verifies:
  1. Category directory initialization (7 core categories)
  2. Korean and English category normalization
  3. Fallback mechanism to stock reaction video (0 crash guarantee)
  4. FFmpeg video normalization to 1080x1920, 30fps, muted audio (-an)
  5. SQLite DB registration and metadata tracking
  6. Local DB query priority (Step 1 instant reuse without network)
  7. API Cache hit simulation (Step 2)
"""

import os
import sys
import shutil
import unittest
import tempfile
import subprocess

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine import media_db
from engine import broll_engine


class TestBrollEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_broll_")
        self.test_db = os.path.join(self.test_dir, "test_media.db")
        self.test_broll_dir = os.path.join(self.test_dir, "general_broll")
        media_db.init_db(self.test_db)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_directory_creation_and_supported_categories(self):
        """Verify that ensure_broll_directories creates all 7 core categories."""
        ensured = broll_engine.ensure_broll_directories(self.test_broll_dir)
        self.assertTrue(os.path.isdir(ensured))

        for cat in broll_engine.SUPPORTED_CATEGORIES:
            cat_path = os.path.join(self.test_broll_dir, cat)
            self.assertTrue(os.path.isdir(cat_path), f"Category dir missing: {cat}")

    def test_02_category_normalization(self):
        """Verify English and Korean category normalization."""
        self.assertEqual(broll_engine.normalize_category_name("audience"), "audience")
        self.assertEqual(broll_engine.normalize_category_name("관객"), "audience")
        self.assertEqual(broll_engine.normalize_category_name("병원"), "hospital")
        self.assertEqual(broll_engine.normalize_category_name("돈"), "money")
        self.assertEqual(broll_engine.normalize_category_name("스마트폰"), "smartphone")
        self.assertEqual(broll_engine.normalize_category_name("공연"), "concert")
        self.assertEqual(broll_engine.normalize_category_name("눈물"), "emotion")
        self.assertEqual(broll_engine.normalize_category_name("비즈니스"), "business")

    def test_03_seamless_fallback_to_stock_video(self):
        """Verify that when no API keys are present, fallback to stock reaction clip succeeds."""
        # Unset env vars for this test
        orig_pex = os.environ.pop("PEXELS_API_KEY", None)
        orig_pix = os.environ.pop("PIXABAY_API_KEY", None)

        try:
            fallback = broll_engine.get_or_fetch_broll(
                category="money",
                tag="cash",
                target_duration=3.5,
                db_path=self.test_db
            )
            self.assertTrue(os.path.isfile(fallback), f"Fallback file not found: {fallback}")
            self.assertTrue(fallback.endswith(".mp4"))
            self.assertGreater(os.path.getsize(fallback), 1000)
        finally:
            if orig_pex:
                os.environ["PEXELS_API_KEY"] = orig_pex
            if orig_pix:
                os.environ["PIXABAY_API_KEY"] = orig_pix

    def test_04_ffmpeg_normalization(self):
        """Verify normalization produces 1080x1920 30fps muted MP4."""
        stock_fallback = broll_engine.get_fallback_stock_video()
        self.assertTrue(os.path.isfile(stock_fallback))

        output_path = os.path.join(self.test_dir, "normalized_test.mp4")
        success = broll_engine.normalize_video_clip(
            input_path=stock_fallback,
            output_path=output_path,
            target_duration=2.0
        )
        self.assertTrue(success)
        self.assertTrue(os.path.isfile(output_path))
        self.assertGreater(os.path.getsize(output_path), 1000)

        # Inspect dimensions via ffprobe / ffmpeg
        ffmpeg_exe = broll_engine.get_ffmpeg_exe()
        cmd = [ffmpeg_exe, "-i", output_path]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        output_info = res.stderr

        self.assertIn("1080x1920", output_info, "Output video is not 1080x1920!")
        self.assertIn("30 fps", output_info, "Output video is not 30 fps!")
        # Confirm no audio stream
        self.assertNotIn("Audio:", output_info, "Output video has unmuted audio stream!")

    def test_05_local_db_reuse_hierarchy(self):
        """Verify strict hierarchy Step 1: local DB clip is returned directly without API call."""
        # Create a mock normalized B-roll clip in test dir
        dummy_clip = os.path.join(self.test_dir, "mock_hospital_clip.mp4")
        broll_engine.normalize_video_clip(
            input_path=broll_engine.get_fallback_stock_video(),
            output_path=dummy_clip,
            target_duration=3.0
        )

        # Register it in DB
        reg = media_db.register_media(
            file_path=dummy_clip,
            media_type="video",
            subtype="general_broll",
            source="local_test",
            tags=["hospital", "surgery"],
            db_path=self.test_db
        )
        self.assertFalse(reg["is_duplicate"])

        # Now query via get_or_fetch_broll
        fetched = broll_engine.get_or_fetch_broll(
            category="hospital",
            tag="surgery",
            target_duration=3.0,
            db_path=self.test_db
        )

        self.assertEqual(os.path.abspath(fetched), os.path.abspath(dummy_clip))

    def test_06_api_cache_storage_and_retrieval(self):
        """Verify Step 2 API Cache mechanism in SQLite DB."""
        mock_pexels_response = {
            "page": 1,
            "per_page": 5,
            "videos": [
                {
                    "id": 99999,
                    "url": "https://www.pexels.com/video/99999/",
                    "user": {"name": "Test Filmmaker"},
                    "video_files": [
                        {
                            "id": 88888,
                            "quality": "hd",
                            "file_type": "video/mp4",
                            "width": 1080,
                            "height": 1920,
                            "fps": 30,
                            "link": "https://sample-videos.com/video123/mp4/720/big_buck_bunny_720p_1mb.mp4"
                        }
                    ]
                }
            ]
        }

        # Cache it
        query_str = "counting money cash finance currency"
        media_db.set_api_cache("pexels", query_str, mock_pexels_response, media_type="video", ttl_days=30, db_path=self.test_db)

        # Retrieve cache
        cached = media_db.get_api_cache("pexels", query_str, media_type="video", db_path=self.test_db)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["videos"][0]["id"], 99999)

        # Extract candidate
        candidate = broll_engine.extract_best_video_candidate("pexels", cached)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["provider_media_id"], "99999")
        self.assertEqual(candidate["author"], "Test Filmmaker")
        self.assertEqual(candidate["license"], "Pexels License")


if __name__ == "__main__":
    print("=== Running Standalone B-roll Engine Verification ===")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBrollEngine)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\nALL 6 B-ROLL ENGINE TEST CASES PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("\nTESTS FAILED!")
        sys.exit(1)
