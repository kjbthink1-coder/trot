"""
test_collector_integration.py - Media Collector Agent Integration Test Suite
=============================================================================
Verifies:
1. save_curated_photos registers surviving curated photos into Media DB and logs project usage.
2. fetch_singer_photos prioritizes DB photos first when available.
3. fetch_singer_photos accurately calculates missing_count (target_count - DB_count) and fetches missing photos.
4. fetch_singer_photos seamlessly falls back to external crawl on DB failure or empty DB.
5. Deduplication prevents duplicate media rows for identical photo hashes.
6. parse_naver_news preserves exact return schema {"url", "title", "content", "images", "singer"}.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

# Ensure workspace root is in python path
sys.path.insert(0, os.path.abspath("."))

from engine.media_db import init_db, get_media_stats, query_singer_photos
from crawler.image_enricher import fetch_singer_photos, save_curated_photos, _crawl_external_singer_photos
from crawler.news_parser import parse_naver_news


class TestMediaCollectorIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="collector_test_")
        self.test_db = os.path.join(self.test_dir, "test_media_library.db")
        init_db(self.test_db)

        # Helper to create valid dummy JPEG photos
        self.created_files = []

    def tearDown(self):
        # Clean up files
        for f in self.created_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass
        try:
            os.rmdir(self.test_dir)
        except Exception:
            pass

    def _create_dummy_image(self, filename: str, color=(100, 150, 200), width=600, height=800) -> str:
        path = os.path.join(self.test_dir, filename)
        img = Image.new("RGB", (width, height), color=color)
        img.save(path, "JPEG")
        self.created_files.append(path)
        return os.path.abspath(path)

    def test_1_save_curated_photos(self):
        """Test user curation registration into Media DB and project history."""
        photo1 = self._create_dummy_image("hero_curated_1.jpg", color=(255, 0, 0))
        photo2 = self._create_dummy_image("hero_curated_2.jpg", color=(0, 255, 0))

        records = save_curated_photos(
            singer_name="임영웅",
            approved_photos=[photo1, photo2],
            project_id="proj_hero_001",
            db_path=self.test_db
        )

        self.assertEqual(len(records), 2, "Should register 2 curated photos")
        self.assertEqual(records[0]["singer_id"], 1)
        self.assertFalse(records[0]["is_duplicate"])

        # Check DB stats
        stats = get_media_stats(self.test_db)
        self.assertEqual(stats["total_singers"], 1)
        self.assertEqual(stats["total_photos"], 2)
        self.assertEqual(stats["total_projects"], 1)
        print("✓ Test 1: save_curated_photos passed (registered curated photos & tracked project)")

    def test_2_fetch_singer_photos_db_priority(self):
        """Test that fetch_singer_photos fulfills completely from DB when DB has enough photos."""
        p1 = self._create_dummy_image("hero_db_1.jpg", color=(10, 20, 30))
        p2 = self._create_dummy_image("hero_db_2.jpg", color=(40, 50, 60))
        p3 = self._create_dummy_image("hero_db_3.jpg", color=(70, 80, 90))

        save_curated_photos("임영웅", [p1, p2, p3], db_path=self.test_db)

        # Mock external crawl to ensure it is NOT called when DB has sufficient photos
        with patch("crawler.image_enricher._crawl_external_singer_photos") as mock_crawl:
            results = fetch_singer_photos(
                singer_name="임영웅",
                target_count=3,
                output_dir=self.test_dir,
                db_path=self.test_db
            )
            mock_crawl.assert_not_called()
            self.assertEqual(len(results), 3)
            self.assertEqual(results, [p1, p2, p3])
        print("✓ Test 2: fetch_singer_photos DB priority passed (0 external crawl needed)")

    def test_3_fetch_singer_photos_missing_count_crawling(self):
        """Test that fetch_singer_photos computes missing_count = target_count - N and crawls only the remainder."""
        p1 = self._create_dummy_image("seojin_db_1.jpg", color=(11, 22, 33))
        p2 = self._create_dummy_image("seojin_db_2.jpg", color=(44, 55, 66))

        save_curated_photos("박서진", [p1, p2], db_path=self.test_db)

        # We request 5 photos: DB has 2, missing is 3
        crawled_p1 = self._create_dummy_image("seojin_scraped_1.jpg", color=(100, 100, 100))
        crawled_p2 = self._create_dummy_image("seojin_scraped_2.jpg", color=(150, 150, 150))
        crawled_p3 = self._create_dummy_image("seojin_scraped_3.jpg", color=(200, 200, 200))

        with patch("crawler.image_enricher._crawl_external_singer_photos", return_value=[crawled_p1, crawled_p2, crawled_p3]) as mock_crawl:
            results = fetch_singer_photos(
                singer_name="박서진",
                target_count=5,
                output_dir=self.test_dir,
                db_path=self.test_db
            )
            # Verify mock_crawl was called with target_count = 3 (the exact missing_count!)
            mock_crawl.assert_called_once()
            _, kwargs = mock_crawl.call_args
            self.assertEqual(kwargs.get("target_count"), 3)

            # Combined list should contain all 5 photos with DB photos prioritized first
            self.assertEqual(len(results), 5)
            self.assertEqual(results[:2], [p1, p2])
            self.assertEqual(results[2:], [crawled_p1, crawled_p2, crawled_p3])
        print("✓ Test 3: fetch_singer_photos missing count calculation passed (DB 2 + crawled 3 = 5)")

    def test_4_seamless_fallback_on_db_failure(self):
        """Test that if DB query fails or DB is empty, it seamlessly falls back 100% to external crawl."""
        crawled_p1 = self._create_dummy_image("fallback_1.jpg", color=(1, 2, 3))
        crawled_p2 = self._create_dummy_image("fallback_2.jpg", color=(4, 5, 6))

        with patch("crawler.image_enricher._crawl_external_singer_photos", return_value=[crawled_p1, crawled_p2]) as mock_crawl:
            # Case A: Unknown singer (empty DB)
            results_empty = fetch_singer_photos(
                singer_name="새로운가수",
                target_count=2,
                output_dir=self.test_dir,
                db_path=self.test_db
            )
            self.assertEqual(len(results_empty), 2)
            self.assertEqual(results_empty, [crawled_p1, crawled_p2])

            # Case B: DB error / invalid DB path
            results_err = fetch_singer_photos(
                singer_name="임영웅",
                target_count=2,
                output_dir=self.test_dir,
                db_path="invalid_path_does_not_exist/corrupt.db"
            )
            self.assertEqual(len(results_err), 2)
        print("✓ Test 4: Seamless fallback on DB empty/error passed")

    def test_5_curation_deduplication(self):
        """Test that registering the same photo twice does not create duplicate entries in media table."""
        photo1 = self._create_dummy_image("dedup_test.jpg", color=(88, 99, 111))

        # First curation
        res1 = save_curated_photos("이찬원", [photo1], project_id="proj_cw_1", db_path=self.test_db)
        self.assertFalse(res1[0]["is_duplicate"])

        # Second curation with identical photo
        res2 = save_curated_photos("이찬원", [photo1], project_id="proj_cw_2", db_path=self.test_db)
        self.assertTrue(res2[0]["is_duplicate"])
        self.assertEqual(res1[0]["id"], res2[0]["id"], "Media ID must match existing record")

        stats = get_media_stats(self.test_db)
        self.assertEqual(stats["total_media"], 1, "Duplicate photo should not increment media count")
        print("✓ Test 5: Curation deduplication passed (hash deduplicated)")

    def test_6_news_parser_schema_preservation(self):
        """Test parse_naver_news return schema and parameter pass-through."""
        dummy_html = """
        <html>
            <head><title>임영웅 콘서트 전석 매진 신화</title></head>
            <body>
                <h2 id="title_area">임영웅 콘서트 전석 매진 신화</h2>
                <div id="dic_area">
                    <p>가수 임영웅이 전국 투어 콘서트에서 전석 매진을 기록했습니다. 팬들의 뜨거운 성원에 힘입어 화려한 무대를 선보였습니다.</p>
                </div>
            </body>
        </html>
        """
        # Patch urllib in news_parser to return dummy HTML without actual web request
        import urllib.request
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = dummy_html.encode("utf-8")

        p_db = self._create_dummy_image("news_test_p1.jpg")
        save_curated_photos("임영웅", [p_db], db_path=self.test_db)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            parsed = parse_naver_news(
                url="https://n.news.naver.com/article/123/456789",
                output_dir=self.test_dir,
                project_id="test_news_proj",
                db_path=self.test_db
            )

        # Check return schema
        expected_keys = {"url", "title", "content", "images", "singer"}
        self.assertTrue(expected_keys.issubset(parsed.keys()), f"Missing keys in schema: {expected_keys - parsed.keys()}")
        self.assertEqual(parsed["singer"], "임영웅")
        self.assertIn("임영웅", parsed["title"])
        self.assertIn(p_db, parsed["images"])
        print("✓ Test 6: parse_naver_news schema preservation passed")


if __name__ == "__main__":
    print("==================================================")
    print("STARTING MEDIA COLLECTOR INTEGRATION TEST SUITE")
    print("==================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMediaCollectorIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\nALL 6 MEDIA COLLECTOR INTEGRATION TESTS PASSED SUCCESSFULLY!")
    else:
        print("\nTEST FAILURES ENCOUNTERED.")
        sys.exit(1)
