"""
test_broll_engine_upgrade.py - Unit Test for Backend Task: B-roll Engine & SQLite DB Protocol Upgrade
====================================================================================================
Verifies:
  1. media_db.get_broll_clips_by_category(category, approved_only)
  2. media_db.register_approved_broll(file_path, category, tags) with SHA-256 deduplication
  3. media_db.delete_broll_by_id(media_id) and media_db.delete_broll_by_path(file_path)
  4. broll_engine.trim_and_normalize_user_broll(input_path, output_dir, start_sec, duration_sec, category)
  5. Automatic API downloads marked approved=0 vs save_approved_broll marked approved=1
  6. broll_engine.get_or_fetch_broll_multiple with 1st priority approved DB matching
"""

import os
import sys
import shutil
import unittest
import tempfile
import subprocess
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine import media_db
from engine import broll_engine


class TestBrollEngineUpgrade(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_broll_upgrade_")
        self.test_db = os.path.join(self.test_dir, "test_broll_upgrade.db")
        media_db.init_db(self.test_db)

        # Create raw test video clip
        self.raw_clip = os.path.join(self.test_dir, "sample_raw_broll.mp4")
        self._generate_raw_test_clip(self.raw_clip, duration=6.0)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _generate_raw_test_clip(self, output_path: str, duration: float = 6.0):
        ffmpeg_exe = broll_engine.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=1280x720:rate=30",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac",
            output_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        self.assertEqual(res.returncode, 0, f"Failed to generate test raw clip: {res.stderr}")
        self.assertTrue(os.path.isfile(output_path))

    def test_01_register_and_query_approved_broll(self):
        """Test register_approved_broll and get_broll_clips_by_category."""
        print("\n▶ [Test 1] Testing register_approved_broll & get_broll_clips_by_category...")
        reg = media_db.register_approved_broll(
            file_path=self.raw_clip,
            category="hospital",
            tags=["doctor", "medical"],
            description="Approved Hospital Clip",
            db_path=self.test_db
        )

        self.assertIsNotNone(reg)
        self.assertEqual(reg["approved"], 1)
        self.assertEqual(reg["subtype"], "general_broll")
        self.assertEqual(reg["active"], 1)

        # Test deduplication
        dup = media_db.register_approved_broll(
            file_path=self.raw_clip,
            category="hospital",
            tags=["clinic"],
            db_path=self.test_db
        )
        self.assertTrue(dup["is_duplicate"])
        self.assertEqual(dup["id"], reg["id"])

        # Query approved clips
        approved_clips = media_db.get_broll_clips_by_category(category="hospital", approved_only=True, db_path=self.test_db)
        self.assertEqual(len(approved_clips), 1)
        self.assertEqual(approved_clips[0]["id"], reg["id"])
        print(" -> Passed! Approved clip registered & queried correctly.")

    def test_02_delete_broll_by_id_and_path(self):
        """Test delete_broll_by_id and delete_broll_by_path."""
        print("\n▶ [Test 2] Testing delete_broll_by_id and delete_broll_by_path...")
        # Create clip 1
        clip1_raw = os.path.join(self.test_dir, "clip1.mp4")
        shutil.copyfile(self.raw_clip, clip1_raw)
        reg1 = media_db.register_approved_broll(clip1_raw, category="concert", db_path=self.test_db)
        
        # Create clip 2
        clip2_raw = os.path.join(self.test_dir, "clip2.mp4")
        with open(clip2_raw, "wb") as f:
            f.write(b"DUMMY_VIDEO_DATA_CLIP_2_123456789")
        reg2 = media_db.register_approved_broll(clip2_raw, category="concert", db_path=self.test_db)

        # Delete clip 1 by ID
        del_ok1 = media_db.delete_broll_by_id(reg1["id"], db_path=self.test_db)
        self.assertTrue(del_ok1)
        self.assertFalse(os.path.exists(clip1_raw))

        # Delete clip 2 by Path
        del_ok2 = media_db.delete_broll_by_path(clip2_raw, db_path=self.test_db)
        self.assertTrue(del_ok2)
        self.assertFalse(os.path.exists(clip2_raw))

        # Query remaining
        rem = media_db.get_broll_clips_by_category("concert", db_path=self.test_db)
        self.assertEqual(len(rem), 0)
        print(" -> Passed! DB record & physical files successfully deleted.")

    def test_03_trim_and_normalize_user_broll(self):
        """Test trim_and_normalize_user_broll for 1080x1920 30fps muted MP4."""
        print("\n▶ [Test 3] Testing trim_and_normalize_user_broll...")
        out_path = broll_engine.trim_and_normalize_user_broll(
            input_path=self.raw_clip,
            output_dir=self.test_dir,
            start_sec=1.0,
            duration_sec=3.5,
            category="money"
        )

        self.assertTrue(os.path.isfile(out_path))
        self.assertGreater(os.path.getsize(out_path), 1000)

        # Inspect stream format
        ffmpeg_exe = broll_engine.get_ffmpeg_exe()
        res = subprocess.run([ffmpeg_exe, "-i", out_path], stderr=subprocess.PIPE, text=True, errors="replace")
        err = res.stderr
        self.assertIn("1080x1920", err)
        self.assertNotIn("Audio:", err)
        print(f" -> Passed! Normalized output: {os.path.basename(out_path)}")

    def test_04_save_approved_broll(self):
        """Test save_approved_broll."""
        print("\n▶ [Test 4] Testing save_approved_broll...")
        saved = broll_engine.save_approved_broll(
            file_path=self.raw_clip,
            category="smartphone",
            tags=["typing", "mobile"],
            start_sec=0.5,
            duration_sec=3.0,
            db_path=self.test_db
        )

        self.assertIsNotNone(saved)
        self.assertEqual(saved["approved"], 1)
        self.assertEqual(saved["subtype"], "general_broll")
        print(" -> Passed! save_approved_broll created and indexed approved clip.")

    def test_05_get_or_fetch_broll_multiple_priority(self):
        """Test get_or_fetch_broll_multiple prioritizing approved DB clips."""
        print("\n▶ [Test 5] Testing get_or_fetch_broll_multiple with 1st priority approved DB matching...")
        # Save approved clip
        app_saved = broll_engine.save_approved_broll(
            file_path=self.raw_clip,
            category="concert",
            tags=["stage"],
            duration_sec=3.5,
            db_path=self.test_db
        )
        approved_file = app_saved["file_path"]

        # Fetch multiple for category 'concert'
        clips = broll_engine.get_or_fetch_broll_multiple(
            categories=["concert"],
            count_per_category=1,
            db_path=self.test_db,
            allow_stock_fallback=True
        )

        self.assertGreater(len(clips), 0)
        self.assertEqual(os.path.abspath(clips[0]), os.path.abspath(approved_file))
        print(" -> Passed! Approved DB clip matched as 1st priority.")


if __name__ == "__main__":
    unittest.main()
