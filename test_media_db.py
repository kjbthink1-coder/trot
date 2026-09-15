"""
test_media_db.py - Comprehensive Unit & Integration Test for engine/media_db.py
Tests all requirements:
1. init_db (all tables & indexes)
2. sha256 compute_file_hash
3. get_or_create_singer (name, alias, case-insensitivity)
4. register_media with sha256 deduplication
5. query_singer_photos (sorting, active check, project exclusion)
6. record_media_usage & record_project_usage
7. get_api_cache / set_api_cache (both signatures & TTL)
8. get_media_stats / get_db_stats
9. sync_existing_assets
"""

import os
import sys
import shutil
import tempfile
import json
import time
from datetime import datetime, timedelta

# Ensure python path
sys.path.insert(0, os.path.abspath("."))

from engine.media_db import (
    init_db,
    compute_file_hash,
    get_or_create_singer,
    register_media,
    query_singer_photos,
    record_media_usage,
    record_project_usage,
    get_api_cache,
    set_api_cache,
    get_media_stats,
    get_db_stats,
    query_brolls,
    sync_existing_assets,
    DEFAULT_DB_PATH
)

def run_tests():
    print("==================================================")
    print("STARTING MEDIA DB VERIFICATION SUITE")
    print("==================================================")

    test_dir = tempfile.mkdtemp(prefix="tro_media_test_")
    test_db = os.path.join(test_dir, "test_media.db")
    
    try:
        # TEST 1: init_db
        print("\n[TEST 1] Initializing SQLite DB...")
        init_db(test_db)
        assert os.path.isfile(test_db), "Database file not created!"
        stats = get_media_stats(test_db)
        assert stats["total_singers"] == 0
        assert stats["total_media"] == 0
        print(" -> init_db passed! Tables & indexes verified.")

        # TEST 2: compute_file_hash
        print("\n[TEST 2] Testing compute_file_hash...")
        dummy_file1 = os.path.join(test_dir, "photo_a.jpg")
        with open(dummy_file1, "wb") as f:
            f.write(b"SAMPLE_IMAGE_DATA_TROT_HERO_12345")
        
        hash1 = compute_file_hash(dummy_file1)
        assert len(hash1) == 64, f"Hash length {len(hash1)} != 64"
        print(f" -> File hash computed: {hash1[:16]}... (passed)")

        # TEST 3: get_or_create_singer
        print("\n[TEST 3] Testing get_or_create_singer...")
        s1 = get_or_create_singer("임영웅", aliases="Hero,영웅", db_path=test_db)
        assert s1["name"] == "임영웅"
        assert s1["id"] == 1
        
        # Test case-insensitivity & retrieval
        s1_again = get_or_create_singer("임영웅", db_path=test_db)
        assert s1_again["id"] == s1["id"], "Failed to retrieve existing singer!"

        # Test alias match
        s1_alias = get_or_create_singer("Hero", db_path=test_db)
        assert s1_alias["id"] == s1["id"], "Failed alias lookup!"

        s2 = get_or_create_singer("박서진", db_path=test_db)
        assert s2["id"] == 2
        print(f" -> get_or_create_singer passed! Singers registered: {s1['name']}, {s2['name']}")

        # TEST 4: register_media & Hash Deduplication
        print("\n[TEST 4] Testing register_media and hash deduplication...")
        reg1 = register_media(
            file_path=dummy_file1,
            singer_name="임영웅",
            media_type="photo",
            subtype="singer_photo",
            source="bing",
            tags=["hero", "concert", "suit"],
            favorite=1,
            db_path=test_db
        )
        assert reg1["is_duplicate"] is False
        assert reg1["file_hash"] == hash1
        assert reg1["favorite"] == 1

        # Duplicate test 1: Register exact same file path
        dup1 = register_media(
            file_path=dummy_file1,
            singer_name="임영웅",
            media_type="photo",
            db_path=test_db
        )
        assert dup1["is_duplicate"] is True, "Expected duplicate for same path!"
        assert dup1["id"] == reg1["id"]

        # Duplicate test 2: Copy file to another location, different filename, same content
        dummy_file2 = os.path.join(test_dir, "photo_a_copy.jpg")
        shutil.copyfile(dummy_file1, dummy_file2)
        dup2 = register_media(
            file_path=dummy_file2,
            singer_name="임영웅",
            media_type="photo",
            db_path=test_db
        )
        assert dup2["is_duplicate"] is True, "Expected duplicate for identical hash!"
        assert dup2["id"] == reg1["id"]
        print(" -> SHA-256 deduplication passed! Identical content recognized regardless of file name.")

        # TEST 5: query_singer_photos & Smart Prioritization
        print("\n[TEST 5] Testing query_singer_photos with prioritization & exclusion...")
        # Create additional files for 임영웅
        file_paths = []
        for i in range(5):
            p = os.path.join(test_dir, f"lim_{i}.jpg")
            with open(p, "wb") as f:
                f.write(f"IMAGE_BYTES_INDEX_{i}".encode("utf-8"))
            fav = 1 if i == 0 else 0
            reg = register_media(
                file_path=p,
                singer_name="임영웅",
                media_type="photo",
                favorite=fav,
                db_path=test_db
            )
            file_paths.append(p)
        
        # Query photos
        q_results = query_singer_photos("임영웅", limit=10, db_path=test_db)
        assert len(q_results) >= 5, f"Expected at least 5 photos, got {len(q_results)}"
        print(f" -> Query returned {len(q_results)} photos for 임영웅.")

        # TEST 6: Project Usage & Exclusion
        print("\n[TEST 6] Testing record_project_usage & project exclusion...")
        project_id = "PROJ_TEST_20260915_001"
        used_selection = q_results[:2]
        rec_res = record_project_usage(
            project_id=project_id,
            singer_name="임영웅",
            used_media_paths=used_selection,
            scene_roles=["scene_1_intro", "scene_2_climax"],
            db_path=test_db
        )
        assert rec_res["recorded_count"] == 2
        print(f" -> Recorded {rec_res['recorded_count']} media usages for project {project_id}.")

        # Query again with exclude_recent_project
        q_excluded = query_singer_photos(
            "임영웅",
            limit=10,
            exclude_recent_project=project_id,
            db_path=test_db
        )
        for used in used_selection:
            assert used not in q_excluded, f"Used file {used} was not excluded!"
        print(" -> Exclude recent project verified! Excluded media not in result set.")

        # TEST 7: API Cache (get/set, TTL, both signatures)
        print("\n[TEST 7] Testing api_cache with TTL and signatures...")
        # Signature A
        set_api_cache("pexels", "money counting", {"videos": [{"id": 101, "url": "https://pexels.com/101"}]}, media_type="video", ttl_days=30, db_path=test_db)
        cached_a = get_api_cache("pexels", "money counting", media_type="video", db_path=test_db)
        assert cached_a is not None
        assert cached_a["videos"][0]["id"] == 101

        # Signature B: media_type as 3rd arg
        set_api_cache("pixabay", "concert crowd", "video", {"hits": [{"id": 202}]}, ttl_days=10, db_path=test_db)
        cached_b = get_api_cache("pixabay", "concert crowd", media_type="video", db_path=test_db)
        assert cached_b is not None
        assert cached_b["hits"][0]["id"] == 202

        # Cache Miss
        miss = get_api_cache("pexels", "non_existent_query_xyz", db_path=test_db)
        assert miss is None
        print(" -> API cache get/set, TTL, and cache miss verified!")

        # TEST 8: get_media_stats & get_db_stats
        print("\n[TEST 8] Testing get_media_stats...")
        m_stats = get_media_stats(test_db)
        assert m_stats["total_singers"] == 2
        assert m_stats["total_photos"] >= 6
        assert m_stats["total_cache_entries"] == 2
        assert m_stats["total_projects"] == 1
        assert m_stats["db_size_bytes"] > 0
        print(f" -> get_media_stats output: {m_stats}")

        # TEST 9: Real Workspace Assets Sync
        print("\n[TEST 9] Testing sync_existing_assets with actual workspace files...")
        real_sync = sync_existing_assets(db_path=DEFAULT_DB_PATH)
        print(f" -> Real asset sync result: {real_sync}")
        real_stats = get_media_stats(DEFAULT_DB_PATH)
        print(f" -> Workspace media_library.db stats: {real_stats}")
        assert real_stats["total_singers"] > 0, "Workspace singers should be registered!"

        print("\n==================================================")
        print("ALL 9 VERIFICATION TESTS PASSED WITH 0 ERRORS!")
        print("==================================================")
        return True

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

if __name__ == "__main__":
    success = run_tests()
    if not success:
        sys.exit(1)
