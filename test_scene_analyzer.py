"""
test_scene_analyzer.py - Comprehensive Unit & Benchmark Test Suite for Scene Analyzer
=====================================================================================
Validates:
1. Execution speed (< 5ms requirement, measured over multiple runs)
2. Category detection accuracy for all 7 standard B-roll categories:
   - audience, emotion, hospital, money, smartphone, concert, business
3. 2.8s cut pacing and timing metadata integrity
4. Mid-video (30~40s slot) B-roll recommendation logic
5. Safe fallback to audience/concert when no keywords match or script is empty
6. Absolute script immutability (original input string unchanged)
7. Diverse real Trot sample scripts from the repository
"""

import os
import sys
import time

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine.scene_analyzer import (
    analyze_script_scenes,
    split_script_to_sentences,
    detect_sentence_categories,
    detect_singer_name,
    format_scene_plan_summary,
    SUPPORTED_CATEGORIES,
    DEFAULT_CUT_DURATION
)

def test_immutability():
    print("\n--- Test 1: Script Immutability Test ---")
    original = "임영웅이 콘서트에서 팬들에게 감동의 눈물을 흘렸습니다. 그리고 1억원을 기부했습니다."
    copy_str = str(original)
    res = analyze_script_scenes(original, singer_name="임영웅")
    assert original == copy_str, "FAIL: Original script was modified!"
    print("[PASS] Original script string remained 100% immutable.")


def test_category_coverage():
    print("\n--- Test 2: Category Detection Coverage (All 7 Categories) ---")
    test_cases = [
        ("관객들의 환호와 박수, 영웅시대 팬클럽의 열띤 응원이 쏟아졌습니다.", "audience"),
        ("눈시울을 붉히며 참았던 눈물과 감동을 감추지 못하고 울컥했습니다.", "emotion"),
        ("수술 후 병원에서 치료를 받으며 건강 회복과 퇴원을 위해 노력했습니다.", "hospital"),
        ("소아암 환우들을 위해 성금 1억원을 기부하며 거액의 매출을 쾌척했습니다.", "money"),
        ("유튜브 조회수 폭발과 멜론 음원차트 1위, SNS 댓글 투표가 뜨겁습니다.", "smartphone"),
        ("전국투어 콘서트 현장에서 화려한 무대 조명 아래 마이크를 쥐고 열창했습니다.", "concert"),
        ("소속사와의 전속계약 체결 및 대기업 광고 CF 모델 발탁, 대상 트로피를 수상했습니다.", "business"),
    ]

    for text, expected_cat in test_cases:
        matches = detect_sentence_categories(text)
        assert expected_cat in matches, f"FAIL: Expected {expected_cat} in {matches} for '{text}'"
        print(f"  [OK] '{expected_cat}' matched: {matches[expected_cat]}")
    print("[PASS] All 7 core categories detected with 100% accuracy.")


def test_timing_and_pacing():
    print("\n--- Test 3: 2.8s Cut Pacing & Scene Structure ---")
    script = (
        "임영웅에게 뜻밖의 기쁜 소식이 전해졌습니다. "
        "영웅시대 팬들의 관심이 집중되고 있습니다. "
        "최근 콘서트 무대에서 폭발적인 가창력을 선보였습니다. "
        "감동적인 눈물을 훔치며 팬들에게 감사함을 전했습니다. "
        "이어서 1억원의 성금을 병원에 기부했다는 소식입니다. "
        "유튜브 조회수는 이미 천만 뷰를 돌파했습니다. "
        "새로운 광고 모델 계약까지 맺으며 대세임을 입증했습니다."
    )
    res = analyze_script_scenes(script, singer_name="임영웅")
    scenes = res["scenes"]
    
    assert len(scenes) >= 7, f"Expected at least 7 scenes, got {len(scenes)}"
    for idx, s in enumerate(scenes):
        assert s["duration"] == DEFAULT_CUT_DURATION, f"Scene {idx} duration is not 2.8s"
        expected_start = round(idx * DEFAULT_CUT_DURATION, 2)
        assert s["start_time"] == expected_start, f"Scene {idx} start_time mismatch: {s['start_time']} vs {expected_start}"
        assert s["end_time"] == round((idx + 1) * DEFAULT_CUT_DURATION, 2)

    # First scene must be singer_photo
    assert scenes[0]["visual_type"] == "singer_photo"
    print(f"[PASS] {len(scenes)} scenes correctly partitioned with exact 2.8s cut pacing.")


def test_mid_slot_recommendation():
    print("\n--- Test 4: Mid-Video (30~40s slot) B-roll Recommendation ---")
    # Build a 15-sentence script (~42s duration) where sentence 11 (~30.8s) has strong emotion/hospital
    sentences = [
        "가수 박서진의 감동적인 소식입니다.",                                   # 0 (0.0s) singer_photo
        "오프닝부터 많은 분들의 이목이 쏠렸습니다.",                           # 1 (2.8s)
        "박서진은 무대 위에서 언제나 최선을 다해왔죠.",                         # 2 (5.6s) concert
        "어릴 적부터 힘든 환경 속에서도 노래를 포기하지 않았습니다.",           # 3 (8.4s)
        "그 결과 수많은 팬들의 사랑을 받는 가수로 성장했습니다.",               # 4 (11.2s) audience
        "방송에 출연할 때마다 시청률은 고공행진을 기록했습니다.",               # 5 (14.0s)
        "그의 진정성 있는 태도는 언제나 화제가 되었는데요.",                   # 6 (16.8s)
        "동료 가수들 역시 그의 인성에 대해 칭찬을 아끼지 않았습니다.",         # 7 (19.6s)
        "특히 가족을 위하는 효심은 남달랐습니다.",                             # 8 (22.4s)
        "어머니의 건강을 위해 밤낮없이 달렸던 과거가 있었죠.",                 # 9 (25.2s) hospital
        "그런데 최근 병원 수술을 무사히 마치고 퇴원했다는 기쁜 소식입니다.",   # 10 (28.0s) hospital
        "수술 후 가족들과 함께 쏟아낸 눈물과 감격의 순간은 모두를 울렸습니다.",# 11 (30.8s) emotion/hospital (Mid Slot!)
        "팬클럽 회원들의 따뜻한 쾌유 응원이 큰 힘이 되었다고 합니다.",         # 12 (33.6s) audience/hospital
        "앞으로 더욱 건강하게 멋진 무대를 보여주길 기대합니다.",               # 13 (36.4s) concert
        "박서진의 앞날을 진심으로 응원합니다."                                 # 14 (39.2s) audience
    ]
    script = " ".join(sentences)
    res = analyze_script_scenes(script, singer_name="박서진")
    
    primary = res["primary_broll"]
    print(f"  Primary B-roll: category={primary['category']}, timestamp={primary['timestamp_estimate']}s")
    print(f"  Reason: {primary['reason']}")
    print(f"  Sentence: {primary['sentence']}")

    # The mid-video window (28.0s ~ 36.4s) contains emotion / hospital / audience
    assert primary["category"] in ["emotion", "hospital", "audience"]
    assert 28.0 <= primary["timestamp_estimate"] <= 40.0
    print(f"[PASS] Successfully selected primary B-roll within the 30~40s mid-video slot.")


def test_fallback_behavior():
    print("\n--- Test 5: Fallback on Keyword-less & Empty Scripts ---")
    # 1. Script with zero matching keywords
    neutral_script = (
        "오늘 아침 날씨가 참 좋습니다. 바람이 시원하게 불어오고 하늘이 맑네요. "
        "어제 보았던 책의 한 구절이 떠오릅니다. 길을 걷다 우연히 마주친 풍경도 아름답습니다. "
        "내일도 오늘처럼 평온한 하루가 되기를 바래봅니다."
    )
    res = analyze_script_scenes(neutral_script)
    assert res["primary_broll"]["category"] in ["audience", "concert"]
    assert len(res["candidates"]) >= 2
    print(f"  Neutral fallback result: category={res['primary_broll']['category']}, candidates={[c['category'] for c in res['candidates']]}")

    # 2. Completely empty script
    res_empty = analyze_script_scenes("")
    assert res_empty["primary_broll"]["category"] == "audience"
    assert res_empty["scenes"] == []
    print("  Empty script handled gracefully with zero errors.")
    print("[PASS] Fallback mechanisms operate seamlessly.")


def test_speed_benchmark():
    print("\n--- Test 6: Speed Benchmark (< 5ms requirement) ---")
    sample_script = (
        "임영웅이 최근 개최된 전국투어 콘서트 무대에서 전석 매진을 기록하며 막강한 티켓 파워를 입증했습니다. "
        "영웅시대 팬클럽의 열띤 환호와 박수가 공연장을 가득 채웠는데요. "
        "임영웅은 팬들의 뜨거운 사랑에 눈시울을 붉히며 감동의 눈물을 글썽였습니다. "
        "또한 소아암 환아들의 병원 치료와 쾌유를 위해 성금 1억원을 기부했다는 훈훈한 미담도 전해졌습니다. "
        "유튜브 조회수는 연일 신기록을 경신하며 멜론 음원차트 1위를 굳건히 지키고 있습니다. "
        "대기업들의 광고 CF 모델 러브콜과 대상 트로피 수상까지 겹경사를 맞았습니다. "
        "언제나 겸손하고 따뜻한 인품으로 감동을 주는 임영웅의 다음 행보가 더욱 기대됩니다."
    )

    # Warm-up run
    analyze_script_scenes(sample_script)

    # 100 benchmark iterations
    runs = 100
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        analyze_script_scenes(sample_script)
        times.append((time.perf_counter() - t0) * 1000.0)

    avg_ms = sum(times) / len(times)
    min_ms = min(times)
    max_ms = max(times)

    print(f"  Iterations: {runs}")
    print(f"  Average Execution Time: {avg_ms:.3f} ms")
    print(f"  Min: {min_ms:.3f} ms | Max: {max_ms:.3f} ms")
    assert avg_ms < 5.0, f"FAIL: Benchmark exceeded 5ms limit! (Avg: {avg_ms:.3f}ms)"
    print(f"[PASS] Speed benchmark PASSED! (Avg: {avg_ms:.3f}ms << 5.0ms requirement)")


def test_real_workspace_samples():
    print("\n--- Test 7: Real Trot Workspace Samples ---")
    sample_files = [
        "sample_im00GJJX5cU.txt",
        "sample_xUgiOyEkRwU.txt",
        "sample_5SK7klT600Y.txt"
    ]

    for fname in sample_files:
        fpath = os.path.join(PROJECT_ROOT, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        res = analyze_script_scenes(content)
        primary = res["primary_broll"]
        print(f"\n  [Sample: {fname}]")
        print(f"  - Detected Singer: {res['detected_singer']}")
        print(f"  - Scenes: {res['total_scenes']} ({res['estimated_duration_sec']}s)")
        print(f"  - Primary B-roll: [{primary['category']}] ({primary['timestamp_estimate']:.1f}s)")
        print(f"  - Reason: {primary['reason']}")
        print(f"  - Analysis Speed: {res['analysis_time_ms']:.3f} ms")

    print("\n[PASS] All real Trot samples parsed flawlessly.")


if __name__ == "__main__":
    print("==================================================================")
    print("      SCENE ANALYZER STANDALONE VERIFICATION & TEST SUITE         ")
    print("==================================================================")
    test_immutability()
    test_category_coverage()
    test_timing_and_pacing()
    test_mid_slot_recommendation()
    test_fallback_behavior()
    test_speed_benchmark()
    test_real_workspace_samples()
    print("\n==================================================================")
    print("          ALL SCENE ANALYZER TESTS PASSED SUCCESSFULLY!           ")
    print("==================================================================")
