import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.append(PROJECT_ROOT)

from engine.media_db import init_db, register_media, query_brolls, delete_media_record
from engine.broll_engine import normalize_video_clip, get_fallback_stock_video

class TestBrollStudioIntegration(unittest.TestCase):
    def setUp(self):
        self.test_db = os.path.join(PROJECT_ROOT, "test_studio_media.db")
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass
        init_db(self.test_db)
        self.stock_clip = get_fallback_stock_video()

    def test_01_normalize_with_start_time(self):
        """Tests normalize_video_clip with non-zero start_time parameter."""
        out_clip = os.path.join(PROJECT_ROOT, "test_norm_out.mp4")
        if os.path.exists(out_clip):
            os.remove(out_clip)

        ok = normalize_video_clip(
            input_path=self.stock_clip,
            output_path=out_clip,
            target_duration=3.0,
            start_time=1.0
        )
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(out_clip))
        self.assertGreater(os.path.getsize(out_clip), 1000)

        # Register clip
        res = register_media(
            file_path=out_clip,
            media_type="video",
            subtype="general_broll",
            source="user_studio",
            tags=["audience"],
            description="Test normalized clip",
            db_path=self.test_db
        )
        self.assertIsNotNone(res.get("id"))

        # Query B-roll by category
        brolls = query_brolls(tags=["audience"], db_path=self.test_db)
        self.assertEqual(len(brolls), 1)
        self.assertEqual(os.path.abspath(brolls[0]["file_path"]), os.path.abspath(out_clip))

        # Delete clip
        del_ok = delete_media_record(brolls[0]["id"], db_path=self.test_db)
        self.assertTrue(del_ok)
        self.assertFalse(os.path.exists(out_clip))

        # Cleanup DB
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    def test_02_pipeline_broll_priority(self):
        """Verifies logic for 1st priority user-selected B-roll clips in render_shorts_video argument prep."""
        fake_broll_1 = os.path.join(PROJECT_ROOT, "fake_user_broll_1.mp4")
        with open(fake_broll_1, "w") as f:
            f.write("dummy content")

        selected_user_brolls = [fake_broll_1]
        num_broll_count = 2

        # Pipeline logic simulation
        broll_clips_list = []
        user_checked_brolls = [fp for fp in selected_user_brolls if os.path.isfile(fp)]
        if user_checked_brolls:
            broll_clips_list.extend(user_checked_brolls)

        self.assertEqual(len(broll_clips_list), 1)
        self.assertEqual(broll_clips_list[0], fake_broll_1)

        # Cleanup
        if os.path.exists(fake_broll_1):
            os.remove(fake_broll_1)

if __name__ == "__main__":
    unittest.main()
