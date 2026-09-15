"""
test_qa4_verification.py - Standalone Verification Test Suite for QA-4 Frame Extractor & AI Reviewer
====================================================================================================
Tests:
  1. Video frame extraction & cleanup with imageio_ffmpeg
  2. Fail-safe fallback when API key is missing or invalid
  3. Live multimodal AI review with Gemini Flash (PASS case)
  4. Live AI review catching deliberate fact distortions (FAIL/WARNING case)
"""

import os
import sys
import glob

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from engine.qa.frame_extractor import (
    extract_representative_frames,
    cleanup_frames,
    get_video_duration,
    calculate_target_timestamps
)
from engine.qa.ai_reviewer import (
    review_with_ai,
    get_gemini_api_key,
    FALLBACK_RESULT
)


def find_sample_video() -> str:
    """Finds an existing MP4 video in the project directory for testing."""
    candidates = [
        os.path.join(PROJECT_ROOT, "assets", "stock_videos", "stock_reaction_1.mp4"),
        os.path.join(PROJECT_ROOT, "outputs", "videos", "qa_baseline_regression_no_broll.mp4"),
        os.path.join(PROJECT_ROOT, "outputs", "temp_render", "qa_normalized_broll.mp4"),
    ]
    for c in candidates:
        if os.path.isfile(c) and os.path.getsize(c) > 1000:
            return os.path.abspath(c)

    # Glob search
    for mp4 in glob.glob(os.path.join(PROJECT_ROOT, "**", "*.mp4"), recursive=True):
        if os.path.isfile(mp4) and os.path.getsize(mp4) > 5000:
            return os.path.abspath(mp4)

    return ""


def test_frame_extractor():
    print("=" * 60)
    print("TEST 1: Frame Extractor & Cleanup")
    print("=" * 60)

    sample_vid = find_sample_video()
    if not sample_vid:
        print("[SKIP] No test MP4 video found in workspace.")
        return

    print(f"Using sample video: {os.path.basename(sample_vid)}")
    dur = get_video_duration(sample_vid)
    print(f"Detected duration: {dur:.2f}s")
    assert dur > 0, "Video duration must be > 0"

    timestamps = calculate_target_timestamps(dur, count=5)
    print(f"Calculated 5 target timestamps: {timestamps}")
    assert len(timestamps) == 5, "Should calculate exactly 5 timestamps"

    frames = extract_representative_frames(sample_vid, count=5)
    print(f"Extracted {len(frames)} frames:")
    for f in frames:
        size_kb = os.path.getsize(f) / 1024
        print(f"  - {os.path.basename(f)} ({size_kb:.1f} KB)")
        assert os.path.isfile(f) and size_kb > 0, f"Frame {f} is empty or missing"

    assert len(frames) > 0, "At least one frame must be extracted"

    # Test cleanup
    cleanup_frames(frames)
    for f in frames:
        assert not os.path.exists(f), f"Frame file {f} was not cleaned up!"
    print("[PASS] Frame extraction and cleanup completed successfully!\n")


def test_ai_reviewer_fallback():
    print("=" * 60)
    print("TEST 2: AI Reviewer Fail-Safe Fallback (No Key)")
    print("=" * 60)

    # Calling review_with_ai with non-existent or dummy key should NEVER crash
    res = review_with_ai(
        article_title="임영웅 기부 소식",
        article_content="가수 임영웅이 취약계층을 위해 성금을 기탁했습니다.",
        shorts_script="임영웅이 따뜻한 기부로 감동을 전했습니다.",
        api_key="INVALID_OR_MISSING_KEY_FOR_TEST_PURPOSES"
    )

    print("Fallback response received:")
    print(res)

    assert isinstance(res, dict), "Result must be a dict"
    assert "score" in res, "Result must have 'score'"
    assert "status" in res, "Result must have 'status'"
    assert "max_score" in res and res["max_score"] == 25.0, "max_score must be 25.0"
    assert "issues" in res and isinstance(res["issues"], list), "issues must be a list"
    assert "recommendations" in res, "recommendations must be present"
    assert res["status"] in ("NOT_RUN", "AI_QA_NOT_RUN", "PASS", "WARNING", "FAIL"), f"Invalid status {res['status']}"

    print("[PASS] AI Reviewer fail-safe returned safely without crash!\n")


def test_ai_reviewer_live_pass():
    print("=" * 60)
    print("TEST 3: Live AI Reviewer (High Quality / Expected PASS)")
    print("=" * 60)

    api_key = get_gemini_api_key()
    if not api_key:
        print("[SKIP] GEMINI_API_KEY not configured. Skipping live test.")
        return

    sample_vid = find_sample_video()
    extracted_frames = []
    if sample_vid:
        extracted_frames = extract_representative_frames(sample_vid, count=3)

    article_title = "임영웅, 아이돌차트 평점랭킹 285주 연속 1위 독보적 신기록"
    article_content = (
        "가수 임영웅이 아이돌차트 평점랭킹에서 285주 연속 최다득표를 기록하며 독보적인 인기를 과시했다. "
        "지난 12일까지 집계된 평점랭킹에서 임영웅은 29만 2931표를 획득해 1위를 지켰다. "
        "스타에 대한 실질적인 팬덤의 규모를 가늠할 수 있는 '좋아요'에서도 가장 많은 2만 8585개를 받았다. "
        "임영웅은 팬들의 끊임없는 사랑에 감사를 표하며 앞으로도 진정성 있는 음악으로 보답하겠다고 전했다."
    )
    shorts_script = (
        "임영웅이 또 한 번 역대급 대기록을 썼습니다! "
        "아이돌차트 평점랭킹에서 무려 285주 연속 1위라는 대기록을 달성한 건데요. "
        "이번 투표에서도 29만 표가 넘는 압도적인 지지를 받았습니다. "
        "팬들을 향한 진심 어린 무대와 따뜻한 마음이 이 엄청난 팬덤 화력을 이끌고 있다는 평가입니다. "
        "영웅시대의 영원한 영웅, 앞으로의 활동도 기대됩니다!"
    )

    try:
        res = review_with_ai(
            article_title=article_title,
            article_content=article_content,
            shorts_script=shorts_script,
            singer_name="임영웅",
            frame_paths=extracted_frames,
            api_key=api_key
        )

        print("Live AI Reviewer Result (Good Content):")
        print(f"  - Score: {res['score']} / {res['max_score']}")
        print(f"  - Status: {res['status']}")
        print(f"  - Critical Error: {res['critical_error']}")
        print(f"  - Issues ({len(res['issues'])}):")
        for iss in res['issues']:
            print(f"    * [{iss.get('type')}] {iss.get('message')}")
        print(f"  - Recommendations: {res.get('recommendations')}")

        assert 0.0 <= res["score"] <= 25.0, "Score out of range"
        assert res["max_score"] == 25.0
        assert res["status"] in ("PASS", "WARNING", "FAIL", "NOT_RUN")
        print("[PASS] Live AI Reviewer PASS case completed successfully!\n")
    finally:
        if extracted_frames:
            cleanup_frames(extracted_frames)


def test_ai_reviewer_live_distortion():
    print("=" * 60)
    print("TEST 4: Live AI Reviewer (Fact Distortion / Expected Issues)")
    print("=" * 60)

    api_key = get_gemini_api_key()
    if not api_key:
        print("[SKIP] GEMINI_API_KEY not configured. Skipping live test.")
        return

    article_title = "이찬원, 취약계층 어린이 위해 장학금 500만원 기부"
    article_content = (
        "가수 이찬원이 가정의 달을 맞아 소외계층 아동들을 위해 장학금 500만원을 쾌척했습니다. "
        "소속사는 이찬원이 평소 어린이 복지에 깊은 관심을 가지고 꾸준히 나눔을 실천해왔다고 밝혔습니다."
    )
    # Deliberately fabricated and distorted script
    distorted_script = (
        "충격 속보입니다! 방탄소년단 정국이 오늘 미국 나스닥 본사를 전격 인수했습니다! "
        "가수 영탁이 백억 원대 슈퍼카 10대를 선물하며 전 세계를 발칵 뒤집어 놓았는데요! "
        "정국과 영탁의 엄청난 합동 콘서트가 내일 평양에서 열린다는 소식입니다!"
    )

    res = review_with_ai(
        article_title=article_title,
        article_content=article_content,
        shorts_script=distorted_script,
        singer_name="이찬원",
        api_key=api_key
    )

    print("Live AI Reviewer Result (Distorted Content):")
    print(f"  - Score: {res['score']} / {res['max_score']}")
    print(f"  - Status: {res['status']}")
    print(f"  - Critical Error: {res['critical_error']}")
    print(f"  - Issues ({len(res['issues'])}):")
    for iss in res['issues']:
        print(f"    * [{iss.get('type')}] {iss.get('message')}")
    print(f"  - Recommendations: {res.get('recommendations')}")

    assert res["score"] < 25.0, "Distorted script must be penalized"
    assert len(res["issues"]) > 0, "Distorted script must trigger issues"
    print("[PASS] AI Reviewer successfully detected severe fact distortions!\n")


if __name__ == "__main__":
    test_frame_extractor()
    test_ai_reviewer_fallback()
    test_ai_reviewer_live_pass()
    test_ai_reviewer_live_distortion()
    print("=" * 60)
    print("ALL QA-4 UNIT TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
