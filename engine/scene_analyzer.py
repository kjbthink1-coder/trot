"""
engine/scene_analyzer.py - Local Keyword/Regex Scene Analyzer for Trot Shorts
=============================================================================
Implementation of Phase 4 Scene Analyzer for Trot/Celebrity Shorts Automation:
- Strict local processing: 0 external LLM calls, 0 network latency, 0 cost.
- Absolute script immutability: The Gemini-generated script is NEVER modified.
- High-precision Korean keyword & regex matching across 7 standard B-roll categories:
    1. audience   (팬, 관객, 환호, 박수, 팬클럽, 응원, 함성, 떼창, 영웅시대, 팬덤 등)
    2. emotion    (눈물, 감동, 감격, 울컥, 가슴, 뭉클, 기쁨, 환희, 위로 등)
    3. hospital   (병원, 치료, 건강, 수술, 회복, 퇴원, 입원, 쾌유 등)
    4. money      (기부, 성금, 매출, 수익, 상금, 계약금, 억, 만원, 재산, 플렉스 등)
    5. smartphone (음원차트, 멜론, 유튜브, 조회수, 스트리밍, 투표, 검색어, SNS 등)
    6. concert    (콘서트, 무대, 공연, 가요제, 전국투어, 마이크, 조명, 열창 등)
    7. business   (계약, 전속, 소속사, 광고, CF, 모델, 대상, 시상식, 트로피, 1위 등)
- 2.8s cut timing calculation adhering to existing video engine specifications.
- Intelligent mid-video (30~40s slot) primary B-roll recommendation + candidates.
- Safe fallback to audience/concert sentiment when no specific keywords match.
"""

import re
import time
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("scene_analyzer")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Default cut duration in seconds (preserving existing video engine timing)
DEFAULT_CUT_DURATION: float = 2.8

# Standard 7 B-roll categories supported across media_db, broll_engine, and scene_analyzer
SUPPORTED_CATEGORIES: List[str] = [
    "audience",
    "emotion",
    "hospital",
    "money",
    "smartphone",
    "concert",
    "business"
]

# Query expansion mapping for high-quality portrait video search (matches broll_engine.py)
CATEGORY_QUERY_MAP: Dict[str, str] = {
    "audience": "cheering audience concert crowd fans",
    "emotion": "crying emotional tears touching moment",
    "hospital": "hospital doctor medical healthcare room",
    "money": "counting money cash finance currency",
    "smartphone": "smartphone screen browsing mobile typing",
    "concert": "concert music stage performance spotlight",
    "business": "business meeting discussion handshake office",
}

# Category priority weights for scoring mid-slot importance
CATEGORY_WEIGHTS: Dict[str, float] = {
    "hospital": 1.5,
    "money": 1.4,
    "emotion": 1.3,
    "smartphone": 1.2,
    "business": 1.1,
    "concert": 1.0,
    "audience": 1.0,
}

# Known Trot singers for automatic singer detection when query is not specified
POPULAR_TROT_SINGERS: List[str] = [
    "임영웅", "박서진", "이찬원", "영탁", "정동원", "김호중", "송가인", "장민호",
    "안성훈", "진해성", "김용빈", "손태진", "배아현", "오유진", "김태연", "전유진",
    "마이진", "박지현", "최수호", "나상도", "김희재", "홍지윤", "양지은", "강혜연",
    "황영웅", "에녹", "신성", "민수현", "박성온", "정서주", "미스김"
]

# Pre-compiled Regex patterns for each category (Zero-overhead, microsecond matching)
# Careful boundary handling prevents false positives (e.g., '기억' does not match '억', 'CF' matches word boundary)
CATEGORY_PATTERNS: Dict[str, re.Pattern] = {
    "hospital": re.compile(
        r"(?:병원|치료|수술|입원|퇴원|회복|쾌유|의사|간호|투병|완치|부상|통증|응급실|"
        r"건강검진|환[고자아]|진료|진단|건강\s*(?:이상|악화|관리|회복|문제|주의))",
        re.IGNORECASE
    ),
    "money": re.compile(
        r"(?:기부(?:금|자|액)?|성금|쾌척|매출|수익(?:금)?|상금|계약금|재산|플렉스|"
        r"건물(?:주)?|부동산|자산|거액|잭팟|부자|억만장자|"
        r"(?:\d+|몇|수십|수백|수천)\s*억(?![가-힣])|"
        r"(?:\d+|몇|수십|수백)\s*만\s*원)",
        re.IGNORECASE
    ),
    "smartphone": re.compile(
        r"(?:음원차트|멜론|유튜브|조회수|스트리밍|투표|검색어|\bSNS\b|인터넷|댓글|실검|"
        r"모바일|스마트폰|핸드폰|휴대폰|인스타그램|틱톡|온라인|네티즌|차트\s*1위|차트\s*올킬)",
        re.IGNORECASE
    ),
    "emotion": re.compile(
        r"(?:눈물(?:바다)?|감동(?:적)?|감격|울컥|가슴\s*(?:이|속|깊이|뭉클|벅찬)|뭉클|"
        r"기쁨|환희|위로|슬픔|오열|벅찬|먹먹|눈시울|애절|눈물을\s*참|가슴이\s*찢)",
        re.IGNORECASE
    ),
    "business": re.compile(
        r"(?:전속계약|계약(?:서)?|전속|소속사|광고|(?:\bCF\b)|모델|대상(?:을|을받은|수상)?|"
        r"시상식|트로피|1위|일위|1등|일등|수상(?:식)?|우승|브랜드|완판|홍보대사|석권)",
        re.IGNORECASE
    ),
    "concert": re.compile(
        r"(?:콘서트|공연|가요제|전국투어|마이크|조명|열창|무대매너|무대|축제|페스티벌|"
        r"라이브|가창력|앙코르|엔딩무대|현장열기)",
        re.IGNORECASE
    ),
    "audience": re.compile(
        r"(?:팬클럽|팬덤|영웅시대|환호|박수|응원(?:가|봉)?|함성|떼창|관객|관중|"
        r"기립박수|팬분(?:들)?|팬들|열성팬|\b팬\b)",
        re.IGNORECASE
    )
}


def detect_singer_name(script_text: str) -> str:
    """
    Detects the primary Trot singer name mentioned in the script.
    Returns empty string if not found.
    """
    if not script_text:
        return ""
    
    # Check frequency of known Trot singers
    counts: Dict[str, int] = {}
    for singer in POPULAR_TROT_SINGERS:
        cnt = script_text.count(singer)
        if cnt > 0:
            counts[singer] = cnt
            
    if counts:
        return max(counts, key=counts.get)
    
    # Fallback to Korean name pattern in opening clause
    m = re.search(r"^([가-힣]{2,4})(?:이|가|의|은|는)?\s*(?:가수|콘서트|신곡|무대|소속사)", script_text[:80])
    if m:
        return m.group(1)
        
    return ""


def split_script_to_sentences(script_text: str) -> List[str]:
    """
    Splits the script into natural sentences / cut units honoring ~2.8s pacing.
    CRITICAL RULE: The text content itself is NEVER modified.
    Preserves exact characters while grouping into natural spoken sentences.
    """
    if not script_text or not script_text.strip():
        return []

    # 문장 끝 문장부호(. ? ! ~) 및 개행 기준 안전 분할 (Python 3.14+ look-behind 호환성 완벽 보장)
    lines = [line.strip() for line in script_text.split('\n') if line.strip()]
    sentences = []

    for line in lines:
        chunks = re.findall(r'[^.?!~]+(?:[.?!~]+|$)', line)
        for chunk in chunks:
            c = chunk.strip()
            if c:
                sentences.append(c)

    # 문장부호 없이 한 덩어리로 길게 이어진 경우 (> 80자), 종결어미 기준 보조 분할
    if len(sentences) <= 1 and len(script_text) > 80:
        cleaned_subs = []
        for s in sentences:
            sub_chunks = re.findall(r'[^다요죠군네까]+[다요죠군네까]+(?:[.?!~]*)|.+', s)
            for sc in sub_chunks:
                sc = sc.strip()
                if sc:
                    cleaned_subs.append(sc)
        if len(cleaned_subs) > 1:
            sentences = cleaned_subs

    return sentences if sentences else [script_text.strip()]


def detect_sentence_categories(sentence: str) -> Dict[str, List[str]]:
    """
    Scans a single sentence across all 7 B-roll categories using pre-compiled regexes.
    Returns a dict mapping category name -> list of matched keyword strings.
    """
    results: Dict[str, List[str]] = {}
    for cat in SUPPORTED_CATEGORIES:
        pattern = CATEGORY_PATTERNS.get(cat)
        if pattern:
            matches = pattern.findall(sentence)
            if matches:
                # Deduplicate matched keywords preserving order
                unique_matches = []
                for m in matches:
                    norm = m.strip()
                    if norm and norm not in unique_matches:
                        unique_matches.append(norm)
                if unique_matches:
                    results[cat] = unique_matches
    return results


def analyze_script_scenes(
    script_text: str,
    singer_name: Optional[str] = None,
    cut_duration: float = DEFAULT_CUT_DURATION
) -> Dict[str, Any]:
    """
    Main entry point for Scene Analyzer (Phase 4).
    
    Performs instant local keyword & regex analysis on the Shorts script.
    - Zero external API/LLM calls (0s latency, 0 cost).
    - Absolute script immutability (input string is unmodified).
    - Returns structured scene plan with exact 2.8s cut timing.
    - Identifies the single best B-roll category for the mid-video slot (30~40s mark),
      along with alternative candidates.
    - Safely falls back to audience/concert sentiment if no specific keywords match.
    
    Args:
        script_text: The complete Gemini Shorts narration script.
        singer_name: Optional singer name override. If None, auto-detected from script.
        cut_duration: Cut duration per scene in seconds (default: 2.8s).
        
    Returns:
        {
            "primary_broll": {
                "category": "audience",
                "tag": "audience",
                "reason": "...",
                "sentence": "...",
                "scene_index": 12,
                "timestamp_estimate": 33.6
            },
            "candidates": [
                {"category": "...", "tag": "...", "reason": "...", "sentence": "...", "score": 2.4},
                ...
            ],
            "scenes": [
                {
                    "index": 0,
                    "scene_index": 1,
                    "text": "...",
                    "visual_type": "singer_photo",
                    "category": None,
                    "query": "...",
                    "start_time": 0.0,
                    "end_time": 2.8,
                    "duration": 2.8,
                    "matched_keywords": []
                },
                ...
            ]
        }
    """
    t_start = time.perf_counter()

    # Input validation & safe fallback for empty input
    if not script_text or not script_text.strip():
        return {
            "primary_broll": {
                "category": "audience",
                "tag": "audience",
                "reason": "대본이 비어 있어 기본 관객 B-roll 적용",
                "sentence": "",
                "scene_index": 1,
                "timestamp_estimate": 0.0
            },
            "candidates": [
                {"category": "audience", "tag": "audience", "reason": "기본 관객 환호", "sentence": "", "score": 1.0},
                {"category": "concert", "tag": "concert", "reason": "기본 콘서트 무대", "sentence": "", "score": 0.8}
            ],
            "scenes": [],
            "analysis_time_ms": 0.0
        }

    detected_singer = singer_name or detect_singer_name(script_text) or "가수"
    sentences = split_script_to_sentences(script_text)
    
    total_scenes = len(sentences)
    total_estimated_duration = total_scenes * cut_duration

    # Ideal target timestamp for mid-video B-roll insertion (30~40s window)
    if total_estimated_duration >= 45.0:
        ideal_mid_time = 34.0
    else:
        ideal_mid_time = max(cut_duration * 2.0, total_estimated_duration * 0.55)

    scenes: List[Dict[str, Any]] = []
    scored_candidates: List[Dict[str, Any]] = []

    for idx, sentence in enumerate(sentences):
        start_t = round(idx * cut_duration, 2)
        end_t = round((idx + 1) * cut_duration, 2)
        
        cat_matches = detect_sentence_categories(sentence)
        
        # Opening scene (index 0, 0~2.8s) is the crucial hook & intro: always singer photo
        if idx == 0:
            scene_info = {
                "index": idx,
                "scene_index": idx + 1,
                "text": sentence,
                "visual_type": "singer_photo",
                "category": None,
                "query": detected_singer,
                "start_time": start_t,
                "end_time": end_t,
                "duration": cut_duration,
                "matched_keywords": []
            }
            scenes.append(scene_info)
            continue

        if cat_matches:
            # Pick the highest weight category present in this sentence
            best_cat = max(
                cat_matches.keys(),
                key=lambda c: len(cat_matches[c]) * CATEGORY_WEIGHTS.get(c, 1.0)
            )
            matched_kws = cat_matches[best_cat]
            broll_query = CATEGORY_QUERY_MAP.get(best_cat, f"{best_cat} trot stage")

            scene_info = {
                "index": idx,
                "scene_index": idx + 1,
                "text": sentence,
                "visual_type": "broll",
                "category": best_cat,
                "query": broll_query,
                "start_time": start_t,
                "end_time": end_t,
                "duration": cut_duration,
                "matched_keywords": matched_kws
            }
            scenes.append(scene_info)

            # Evaluate suitability for mid-video B-roll slot (30~40s mark)
            time_diff = abs(start_t - ideal_mid_time)
            timing_factor = max(0.2, 1.0 - (time_diff / max(15.0, total_estimated_duration)))
            
            # Bonus if falling directly within the 28.0s ~ 42.0s golden window
            if 28.0 <= start_t <= 42.0:
                timing_factor += 0.35
            # Penalty for scenes too early in narration (< 10s)
            elif start_t < 10.0:
                timing_factor *= 0.4

            cat_weight = CATEGORY_WEIGHTS.get(best_cat, 1.0)
            candidate_score = round((len(matched_kws) * 1.2 + cat_weight) * timing_factor, 3)

            scored_candidates.append({
                "category": best_cat,
                "tag": best_cat,
                "reason": (
                    f"장면 {idx + 1} ({start_t:.1f}초): "
                    f"키워드 [{', '.join(matched_kws)}] 감지"
                ),
                "sentence": sentence,
                "score": candidate_score,
                "scene_index": idx + 1,
                "timestamp_estimate": start_t,
                "matched_keywords": matched_kws
            })

            # Also register secondary matches in the same sentence as alternative candidates
            for alt_cat, alt_kws in cat_matches.items():
                if alt_cat != best_cat:
                    alt_weight = CATEGORY_WEIGHTS.get(alt_cat, 1.0)
                    alt_score = round((len(alt_kws) * 0.8 + alt_weight) * timing_factor * 0.85, 3)
                    scored_candidates.append({
                        "category": alt_cat,
                        "tag": alt_cat,
                        "reason": (
                            f"장면 {idx + 1} ({start_t:.1f}초 보조): "
                            f"키워드 [{', '.join(alt_kws)}] 감지"
                        ),
                        "sentence": sentence,
                        "score": alt_score,
                        "scene_index": idx + 1,
                        "timestamp_estimate": start_t,
                        "matched_keywords": alt_kws
                    })
        else:
            # Default to singer photo
            scene_info = {
                "index": idx,
                "scene_index": idx + 1,
                "text": sentence,
                "visual_type": "singer_photo",
                "category": None,
                "query": detected_singer,
                "start_time": start_t,
                "end_time": end_t,
                "duration": cut_duration,
                "matched_keywords": []
            }
            scenes.append(scene_info)

    # Determine Primary B-roll and Candidates
    # Deduplicate candidates by category, keeping the highest score for each unique category
    unique_candidates: Dict[str, Dict[str, Any]] = {}
    for cand in sorted(scored_candidates, key=lambda x: x["score"], reverse=True):
        cat = cand["category"]
        if cat not in unique_candidates:
            unique_candidates[cat] = cand

    ranked_candidates = list(unique_candidates.values())

    # Fallback Handling if no keywords or insufficient candidates
    if not ranked_candidates:
        # Find sentence closest to the mid-video slot
        mid_idx = max(0, min(total_scenes - 1, int(round(ideal_mid_time / cut_duration))))
        mid_sentence = sentences[mid_idx] if sentences else ""
        mid_timestamp = round(mid_idx * cut_duration, 2)

        primary_broll = {
            "category": "audience",
            "tag": "audience",
            "reason": "대본 내 특이 키워드 미감지 - 트로트 쇼츠 기본 정서(audience: 팬/관객 환호) B-roll 자동 배정",
            "sentence": mid_sentence,
            "scene_index": mid_idx + 1,
            "timestamp_estimate": mid_timestamp
        }
        candidates_list = [
            {
                "category": "audience",
                "tag": "audience",
                "reason": f"관객 및 팬덤 환호 (중반 {mid_timestamp:.1f}초 슬롯 기본 추천)",
                "sentence": mid_sentence,
                "score": 1.0,
                "scene_index": mid_idx + 1,
                "timestamp_estimate": mid_timestamp
            },
            {
                "category": "concert",
                "tag": "concert",
                "reason": f"화려한 무대 및 콘서트 열기 (대체 추천)",
                "sentence": mid_sentence,
                "score": 0.85,
                "scene_index": mid_idx + 1,
                "timestamp_estimate": mid_timestamp
            }
        ]
    else:
        top_cand = ranked_candidates[0]
        primary_broll = {
            "category": top_cand["category"],
            "tag": top_cand["tag"],
            "reason": (
                f"[{top_cand['category']}] 추천 ({top_cand['reason']} | "
                f"30~40초 중반 영상 삽입 슬롯 적합도 1위)"
            ),
            "sentence": top_cand["sentence"],
            "scene_index": top_cand["scene_index"],
            "timestamp_estimate": top_cand["timestamp_estimate"]
        }
        
        # Ensure we offer at least 2 distinct candidates by appending general fallbacks if needed
        candidates_list = list(ranked_candidates)
        present_cats = {c["category"] for c in candidates_list}
        fallback_cats = ["audience", "concert", "emotion"]
        
        for fb in fallback_cats:
            if fb not in present_cats and len(candidates_list) < 3:
                mid_idx = max(0, min(total_scenes - 1, int(round(ideal_mid_time / cut_duration))))
                mid_sent = sentences[mid_idx] if sentences else ""
                candidates_list.append({
                    "category": fb,
                    "tag": fb,
                    "reason": f"기본 트로트 감성 [{fb}] 추천",
                    "sentence": mid_sent,
                    "score": 0.5,
                    "scene_index": mid_idx + 1,
                    "timestamp_estimate": round(mid_idx * cut_duration, 2)
                })

    analysis_elapsed_ms = (time.perf_counter() - t_start) * 1000.0

    return {
        "primary_broll": primary_broll,
        "candidates": candidates_list,
        "scenes": scenes,
        "total_scenes": total_scenes,
        "estimated_duration_sec": round(total_estimated_duration, 2),
        "detected_singer": detected_singer,
        "analysis_time_ms": round(analysis_elapsed_ms, 3)
    }


def format_scene_plan_summary(analysis_result: Dict[str, Any]) -> str:
    """
    Generates a concise, human-readable summary of the scene analysis plan.
    Useful for logging and UI preview.
    """
    primary = analysis_result.get("primary_broll", {})
    scenes = analysis_result.get("scenes", [])
    total_scenes = len(scenes)
    duration = analysis_result.get("estimated_duration_sec", 0.0)
    time_ms = analysis_result.get("analysis_time_ms", 0.0)
    singer = analysis_result.get("detected_singer", "가수")

    lines = [
        f"=== [Scene Analyzer Plan] 총 {total_scenes}장면 ({duration:.1f}초, 분석속도 {time_ms:.2f}ms) ===",
        f"▶ 대상 가수: {singer}",
        f"▶ 30~40s 추천 B-roll: [{primary.get('category', 'audience')}]",
        f"   - 이유: {primary.get('reason', '')}",
        f"   - 해당 문장 ({primary.get('timestamp_estimate', 0.0):.1f}초): \"{primary.get('sentence', '')[:45]}...\"",
        "▶ 전체 컷 구성 (2.8초 기준):"
    ]

    for s in scenes:
        vtype = s.get("visual_type", "singer_photo")
        cat = s.get("category")
        marker = f"[{cat}]" if cat else "[사진]"
        lines.append(
            f"  - Cut {s.get('index', 0):02d} ({s.get('start_time', 0.0):4.1f}s~{s.get('end_time', 0.0):4.1f}s) "
            f"{marker:10s} | {s.get('text', '')[:35]}"
        )

    return "\n".join(lines)
