"""
engine/qa/factual_validator.py - QA-2 Factual & Content Consistency Validator
=============================================================================
Phase 5 QA Module: Independent Factual Grounding & Hallucination Detection.
- Evaluates Gemini/AI-generated shorts scripts and blog articles against original news articles.
- 100% local, deterministic, rule-based verification (0 external LLM self-grading, 0 network latency).
- Checks:
  1. Singer name & core subject grounding (8.0 pts)
  2. Number, views, rank & statistical fidelity (10.0 pts)
  3. Sensationalism / extreme clickbait / fake news distortion (8.0 pts)
  4. Blog article structure, length & factual cohesion (4.0 pts)
  5. Shorts narration script length synchronization (400~500 chars)
- Max score: 30.0 points.
- Strict Pass threshold: >= 21.0 pts (70%) and zero critical errors.
"""

import re
from typing import Dict, List, Any, Optional, Set, Tuple


# =============================================================================
# Standard Length Requirements (100% Synchronized with engine/ai_generator.py)
# =============================================================================
SHORTS_MIN_CHARS: int = 400
SHORTS_MAX_CHARS: int = 500
BLOG_TARGET_CHARS: int = 2400
BLOG_TOLERANCE_RATIO: float = 0.10  # ±10%
BLOG_MIN_CHARS: int = int(BLOG_TARGET_CHARS * (1.0 - BLOG_TOLERANCE_RATIO))  # 2,160
BLOG_MAX_CHARS: int = int(BLOG_TARGET_CHARS * (1.0 + BLOG_TOLERANCE_RATIO))  # 2,640


# Known popular Trot singers for subject grounding & alias expansion
POPULAR_TROT_SINGERS: List[str] = [
    "임영웅", "박서진", "이찬원", "영탁", "정동원", "김호중", "송가인", "장민호",
    "안성훈", "진해성", "김용빈", "손태진", "배아현", "오유진", "김태연", "전유진",
    "마이진", "박지현", "최수호", "나상도", "김희재", "홍지윤", "양지은", "강혜연",
    "황영웅", "에녹", "신성", "민수현", "박성온", "정서주", "미스김"
]

# Aliases and fandom honorifics for trot singers
SINGER_ALIASES: Dict[str, List[str]] = {
    "임영웅": ["영웅", "영웅시대", "히어로", "HERO", "임히어로", "영웅님", "영웅씨"],
    "박서진": ["서진", "닻별", "장구의 신", "서진이", "서진님", "박서진님"],
    "이찬원": ["찬원", "찬또배기", "찬또", "찬스", "찬원님", "이찬원님"],
    "영탁": ["박영탁", "탁이", "영탁님", "영탁이", "탁쇼"],
    "정동원": ["동원", "동원이", "우주총동원", "정동원군", "동원군"],
    "김호중": ["호중", "트바로티", "아리스", "호중님", "김호중님"],
    "송가인": ["가인", "가인이", "어게인", "송가인이어라", "가인님"],
    "장민호": ["민호", "민호오빠", "민호님", "장민호님"],
    "안성훈": ["성훈", "후니용이", "안성훈님"],
    "진해성": ["해성", "진해성님"],
    "김용빈": ["용빈", "김용빈님"],
    "손태진": ["태진", "손태진님"],
    "배아현": ["아현", "배아현님"],
    "오유진": ["유진", "오유진양"],
    "김태연": ["태연", "김태연양"],
    "전유진": ["전유진양"],
    "마이진": ["화진", "마이진님"],
    "박지현": ["지현", "박지현님"],
    "최수호": ["수호", "최수호님"],
    "나상도": ["상도", "나상도님"],
    "김희재": ["희재", "김희재님", "희랑별"],
    "홍지윤": ["지윤", "홍지윤님"],
    "양지은": ["지은", "양지은님"],
    "강혜연": ["혜연", "강혜연님"],
    "황영웅": ["황영웅님"],
}

# Extreme fake news / severe distortion terms (Causes critical error if hallucinated)
CRITICAL_SENSATIONAL_TERMS: List[str] = [
    "사망", "은퇴", "퇴출", "파문", "불화", "비난 폭주", "폭로",
    "참변", "비보", "구속", "음주운전", "도박", "피소", "체포"
]

# Hyperbolic clickbait phrases (Causes warning & score deduction if hallucinated)
CLICKBAIT_PHRASES: List[str] = [
    "전 국민 충격", "경악", "충격적인", "발칵", "눈물바다", "오열",
    "충격 고백", "경악을 금치", "충격에 빠", "전 국민이 경악",
    "충격 실체", "눈물 겨운"
]

# Popular broadcast programs & music shows to verify grounding
KNOWN_PROGRAMS_AND_ENTITIES: List[str] = [
    "미스터트롯", "미스트롯", "불후의 명곡", "현역가왕", "사랑의 콜센타",
    "아침마당", "살림남", "뽕숭아학당", "트롯 전국체전", "복면가왕",
    "골든걸스", "미스터로또", "음악중심", "인기가요", "뮤직뱅크", "더트롯쇼"
]

# Numbers that are benign/meta in shorts narration and shouldn't trigger hallucination penalties
BENIGN_META_NUMBERS: Set[str] = {
    "60초", "3초", "10초", "30초", "1초", "2초", "5초",
    "1분", "2분", "3분", "5070",
    "1단계", "2단계", "3단계",
    "첫번째", "두번째", "세번째", "1번째", "2번째", "3번째"
}


def _detect_singer(article_title: str, article_content: str, singer_name: Optional[str] = None) -> Optional[str]:
    """Detects or confirms the primary trot singer subject from article content."""
    if singer_name and singer_name.strip():
        return singer_name.strip()

    combined_text = f"{article_title}\n{article_content}"

    # 1. Check title first (highest priority)
    for s in POPULAR_TROT_SINGERS:
        if s in article_title:
            return s

    # 2. Check full article frequency
    counts = {}
    for s in POPULAR_TROT_SINGERS:
        cnt = combined_text.count(s)
        if cnt > 0:
            counts[s] = cnt

    if counts:
        return max(counts, key=counts.get)

    return None


def _check_singer_grounding(
    article_title: str,
    article_content: str,
    shorts_script: str,
    target_singer: Optional[str]
) -> Tuple[float, List[Dict[str, Any]], bool, Dict[str, Any]]:
    """
    Evaluates singer name grounding and detects singer mismatch.
    Returns: (score, issues, critical_error, details)
    """
    max_pts = 8.0
    score = max_pts
    issues: List[Dict[str, Any]] = []
    critical_error = False

    details = {
        "score": max_pts,
        "max_score": max_pts,
        "target_singer": target_singer,
        "script_singer_found": False,
        "mismatched_singers": [],
    }

    if not target_singer:
        # If no singer identified in article or parameter, check general entity consistency
        return score, issues, critical_error, details

    # Build valid alias set for the target singer
    valid_names = {target_singer}
    if target_singer in SINGER_ALIASES:
        valid_names.update(SINGER_ALIASES[target_singer])

    # Check if target singer or any valid alias appears in script
    script_singer_found = any(alias in shorts_script for alias in valid_names)
    details["script_singer_found"] = script_singer_found

    # Check if a DIFFERENT prominent singer appears in script who was NOT in article
    article_combined = f"{article_title} {article_content}"
    mismatched = []
    for other_s in POPULAR_TROT_SINGERS:
        if other_s != target_singer and other_s in shorts_script:
            if other_s not in article_combined:
                mismatched.append(other_s)

    details["mismatched_singers"] = mismatched

    if mismatched and not script_singer_found:
        # Severe distortion: Article about singer A, but script exclusively about singer B!
        score = 0.0
        critical_error = True
        issues.append({
            "type": "error",
            "component": "factual",
            "message": (
                f"원문 기사의 주인공은 '{target_singer}'이나, 쇼츠 대본은 전혀 다른 가수 "
                f"'{', '.join(mismatched)}'을(를) 다루고 있어 중대한 왜곡이 발생했습니다."
            )
        })
    elif mismatched and script_singer_found:
        # Script mentions both target singer and another ungrounded singer
        score = max(0.0, score - 3.0)
        issues.append({
            "type": "warning",
            "component": "factual",
            "message": (
                f"원문에 언급되지 않은 타 가수 '{', '.join(mismatched)}'이(가) 대본에 등장합니다."
            )
        })
    elif not script_singer_found:
        # Target singer name is completely missing from script
        score = max(0.0, score - 4.0)
        issues.append({
            "type": "warning",
            "component": "factual",
            "message": (
                f"원문 기사의 핵심 인물인 '{target_singer}'의 이름 또는 별칭이 "
                f"쇼츠 대본에 직접 명시되지 않았습니다."
            )
        })

    # Check quoted entities / program titles in script
    # Matches: ‘...’, “...”, 「...」, 『...』, <...>, "..."
    quoted_matches = re.findall(r"['\"‘“「『<]([^'\"’”」』>]{2,25})['\"‘“「『>]", shorts_script)
    for q_entity in quoted_matches:
        q_clean = q_entity.strip()
        if len(q_clean) >= 2 and q_clean not in article_combined:
            score = max(0.0, score - 1.0)
            issues.append({
                "type": "warning",
                "component": "factual",
                "message": f"대본에 인용된 고유명사/제목 '{q_clean}'이(가) 원문 기사에서 확인되지 않습니다."
            })

    # Check known programs mentioned in script
    for prog in KNOWN_PROGRAMS_AND_ENTITIES:
        if prog in shorts_script and prog not in article_combined:
            score = max(0.0, score - 1.5)
            issues.append({
                "type": "warning",
                "component": "factual",
                "message": f"대본에 언급된 방송/프로그램명 '{prog}'이(가) 원문 기사에 없습니다 (환각 가능성)."
            })

    details["score"] = round(score, 1)
    return details["score"], issues, critical_error, details


def _extract_numbers_with_units(text: str) -> List[Tuple[str, str, str]]:
    """
    Extracts numbers with quantitative units from Korean text.
    Returns list of tuples: (full_token, numeric_part, unit_part)
    Examples:
      - "1300만 뷰" -> ("1300만 뷰", "1300", "만 뷰")
      - "100억 원"  -> ("100억 원", "100", "억 원")
      - "1위"       -> ("1위", "1", "위")
      - "5월 12일"  -> ("5월 12일", "5/12", "월일")
    """
    results: List[Tuple[str, str, str]] = []

    # 1. Dates: e.g. 5월 12일, 2024년 5월, 2024년
    date_pattern = re.compile(r"(\d{1,4})\s*년(?:\s*(\d{1,2})\s*월(?:\s*(\d{1,2})\s*일)?)?|(\d{1,2})\s*월\s*(\d{1,2})\s*일")
    for m in date_pattern.finditer(text):
        full_match = m.group(0).strip()
        results.append((full_match, full_match, "date"))

    # 2. Ranks: 1위, 2등, TOP 10
    rank_pattern = re.compile(r"(?:TOP\s*|top\s*)?(\d+)\s*(?:위|등)")
    for m in rank_pattern.finditer(text):
        full_match = m.group(0).strip()
        num = m.group(1)
        results.append((full_match, num, "rank"))

    # 3. Currency / Views / Counts / Percentages
    # e.g. 1300만, 100억, 5000만원, 1,300만뷰, 95%
    stat_pattern = re.compile(
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(조|억|만|천|백)?\s*(원|회|뷰|명|표|곡|장|개|점|석|%|퍼센트|세|달러)?"
    )
    for m in stat_pattern.finditer(text):
        full_match = m.group(0).strip()
        num_str = m.group(1).replace(",", "")
        scale = m.group(2) or ""
        unit = m.group(3) or ""

        # Skip if no scale and no unit (plain lone digit like '1', '2' in regular speech)
        if not scale and not unit:
            continue

        if full_match in BENIGN_META_NUMBERS:
            continue

        results.append((full_match, num_str + scale, unit))

    return results


def _is_number_grounded(full_token: str, num_scale: str, unit: str, article_text: str) -> bool:
    """
    Checks whether a number expression from the script is grounded in the article.
    Performs normalized matching, substring matching, and semantic equivalences.
    """
    # Direct substring match
    if full_token in article_text:
        return True

    # Strip spaces and commas
    clean_article = article_text.replace(" ", "").replace(",", "")
    clean_token = full_token.replace(" ", "").replace(",", "")
    if clean_token in clean_article:
        return True

    # Rank normalization (e.g. 1위 <-> 1등 <-> 일위 <-> 1 위 <-> 정상 <-> 우승)
    if unit == "rank":
        num_match = re.search(r"\d+", full_token)
        if num_match:
            rank_num = num_match.group(0)
            # If 1위: also check "1등", "1위", "우승", "정상", "단독 1위"
            if rank_num == "1":
                if any(w in article_text for w in ["1위", "1등", "일위", "우승", "정상", "1 위", "1 등"]):
                    return True
            else:
                if f"{rank_num}위" in clean_article or f"{rank_num}등" in clean_article:
                    return True

    # Numeric part with scale check (e.g. "1300만" -> check if "1300만" or "1,300만" is in article)
    clean_num_scale = num_scale.replace(" ", "").replace(",", "")
    if clean_num_scale and clean_num_scale in clean_article:
        return True

    # Check raw digits
    digits_only = re.sub(r"[^\d]", "", num_scale)
    if digits_only and len(digits_only) >= 3 and digits_only in clean_article:
        return True

    return False


def _check_numbers_fidelity(
    article_title: str,
    article_content: str,
    shorts_script: str
) -> Tuple[float, List[Dict[str, Any]], bool, Dict[str, Any]]:
    """
    Extracts quantitative numbers, statistics, rankings, views from script
    and verifies grounding in original article text.
    Returns: (score, issues, critical_error, details)
    """
    max_pts = 10.0
    score = max_pts
    issues: List[Dict[str, Any]] = []
    critical_error = False

    article_combined = f"{article_title}\n{article_content}"

    script_numbers = _extract_numbers_with_units(shorts_script)

    verified: List[str] = []
    hallucinated: List[str] = []
    major_hallucinations: List[str] = []

    # De-duplicate tokens
    seen_tokens = set()
    unique_tokens = []
    for full_token, num_scale, unit in script_numbers:
        if full_token not in seen_tokens and full_token not in BENIGN_META_NUMBERS:
            seen_tokens.add(full_token)
            unique_tokens.append((full_token, num_scale, unit))

    for full_token, num_scale, unit in unique_tokens:
        grounded = _is_number_grounded(full_token, num_scale, unit, article_combined)
        if grounded:
            verified.append(full_token)
        else:
            hallucinated.append(full_token)
            # Determine if major statistical claim
            is_major = False
            if any(s in full_token for s in ["억", "조"]):
                is_major = True
            elif "만" in full_token and any(u in full_token for u in ["회", "뷰", "원", "명", "표", "스트리밍"]):
                is_major = True
            elif unit == "rank":
                is_major = True

            if is_major:
                major_hallucinations.append(full_token)
                score = max(0.0, score - 3.0)
                issues.append({
                    "type": "error" if len(major_hallucinations) >= 2 else "warning",
                    "component": "factual",
                    "message": f"원문 기사에 근거가 없는 주요 통계/수치 표현 '{full_token}'이(가) 쇼츠 대본에 사용되었습니다."
                })
            else:
                score = max(0.0, score - 1.5)
                issues.append({
                    "type": "warning",
                    "component": "factual",
                    "message": f"원문 기사에서 확인되지 않는 수치/날짜 표현 '{full_token}'이(가) 대본에 포함되었습니다."
                })

    if len(major_hallucinations) >= 2:
        critical_error = True

    details = {
        "score": round(score, 1),
        "max_score": max_pts,
        "total_extracted": len(unique_tokens),
        "verified_numbers": verified,
        "hallucinated_numbers": hallucinated,
        "major_hallucinations": major_hallucinations,
    }

    return details["score"], issues, critical_error, details


def _check_sensationalism_and_distortion(
    article_title: str,
    article_content: str,
    shorts_script: str
) -> Tuple[float, List[Dict[str, Any]], bool, Dict[str, Any]]:
    """
    Detects ungrounded clickbait, sensational vocabulary, and fake news terms
    that are present in shorts_script but NOT in the original article.
    Returns: (score, issues, critical_error, details)
    """
    max_pts = 8.0
    score = max_pts
    issues: List[Dict[str, Any]] = []
    critical_error = False

    article_combined = f"{article_title}\n{article_content}"

    detected_critical = []
    detected_clickbait = []

    # 1. Critical fake news terms (death, retirement, lawsuit, scandal)
    for term in CRITICAL_SENSATIONAL_TERMS:
        if term in shorts_script and term not in article_combined:
            detected_critical.append(term)
            score = max(0.0, score - 4.0)
            critical_error = True
            issues.append({
                "type": "error",
                "component": "factual",
                "message": f"원문에 전혀 없는 치명적 왜곡/가짜뉴스성 표현 '{term}'이(가) 대본에서 감지되었습니다."
            })

    # 2. Hyperbolic clickbait / shock phrases
    for phrase in CLICKBAIT_PHRASES:
        if phrase in shorts_script and phrase not in article_combined:
            detected_clickbait.append(phrase)
            score = max(0.0, score - 2.0)
            issues.append({
                "type": "warning",
                "component": "factual",
                "message": f"원문에 없는 과장/어그로성 클릭베이트 표현 '{phrase}'이(가) 대본에 포함되었습니다."
            })

    details = {
        "score": round(score, 1),
        "max_score": max_pts,
        "detected_critical": detected_critical,
        "detected_clickbait": detected_clickbait,
    }

    return details["score"], issues, critical_error, details


def validate_shorts_length(shorts_script: Optional[str]) -> Dict[str, Any]:
    """
    Validates shorts narration script length against standardized requirement:
    - Target: 400 ~ 500 Korean characters (including spaces).
    - Expected: 400 <= length <= 500 chars.
    - If length < 400: slight shortage (350~399, -1.0 pt) or serious shortage (<350, -2.0 pts).
    - If length > 500: slight excess (501~550, warning) or excessive (>550, -1.0 pt).
    """
    if not shorts_script or not shorts_script.strip():
        return {
            "length": 0,
            "expected_range": (SHORTS_MIN_CHARS, SHORTS_MAX_CHARS),
            "passed": False,
            "status": "empty",
            "penalty": 2.0,
            "issues": [{
                "type": "error",
                "component": "shorts_length",
                "message": "쇼츠 대본이 비어 있습니다."
            }]
        }

    length = len(shorts_script.strip())
    passed = SHORTS_MIN_CHARS <= length <= SHORTS_MAX_CHARS
    penalty = 0.0
    issues: List[Dict[str, Any]] = []

    if length < 350:
        status = "serious_shortage"
        penalty = 2.0
        issues.append({
            "type": "warning",
            "component": "shorts_length",
            "message": (
                f"쇼츠 대본 분량이 기준({SHORTS_MIN_CHARS}~{SHORTS_MAX_CHARS}자)보다 심각하게 부족합니다 "
                f"({length}자 / 최소 {SHORTS_MIN_CHARS}자 필요). -2.0점 감점"
            )
        })
    elif length < SHORTS_MIN_CHARS:
        status = "slight_shortage"
        penalty = 1.0
        issues.append({
            "type": "warning",
            "component": "shorts_length",
            "message": (
                f"쇼츠 대본 분량이 기준({SHORTS_MIN_CHARS}~{SHORTS_MAX_CHARS}자)보다 다소 부족합니다 "
                f"({length}자 / 권장 {SHORTS_MIN_CHARS}~{SHORTS_MAX_CHARS}자). -1.0점 감점"
            )
        })
    elif length <= SHORTS_MAX_CHARS:
        status = "optimal"
        penalty = 0.0
    elif length <= 550:
        status = "slight_excess"
        penalty = 0.0
        issues.append({
            "type": "warning",
            "component": "shorts_length",
            "message": (
                f"쇼츠 대본 분량이 권장 기준({SHORTS_MIN_CHARS}~{SHORTS_MAX_CHARS}자)을 소폭 초과했습니다 "
                f"({length}자)."
            )
        })
    else:
        status = "excessive"
        penalty = 1.0
        issues.append({
            "type": "warning",
            "component": "shorts_length",
            "message": (
                f"쇼츠 대본 분량이 권장 기준({SHORTS_MIN_CHARS}~{SHORTS_MAX_CHARS}자)을 과도하게 초과했습니다 "
                f"({length}자). -1.0점 감점"
            )
        })

    return {
        "length": length,
        "expected_range": (SHORTS_MIN_CHARS, SHORTS_MAX_CHARS),
        "passed": passed,
        "status": status,
        "penalty": penalty,
        "issues": issues,
    }


def validate_blog_length(blog_article: Optional[str]) -> Dict[str, Any]:
    """
    Validates blog article length against standardized requirement:
    - Target: 2,400 Korean characters ±10% (2,160 ~ 2,640 chars, including spaces).
    - Expected: 2160 <= length <= 2640 chars.
    - If length < 2160: deduct points (-2.0 pts for slight shortage 1800~2159, -4.0 pts for serious shortage <1800).
    - If length > 2640: issue warning (2641~2900) or slight deduction (-1.0 pt for >2900).
    """
    if not blog_article or not blog_article.strip():
        return {
            "length": 0,
            "target": BLOG_TARGET_CHARS,
            "expected_range": (BLOG_MIN_CHARS, BLOG_MAX_CHARS),
            "passed": False,
            "status": "empty",
            "penalty": 4.0,
            "issues": [{
                "type": "warning",
                "component": "blog_length",
                "message": "블로그 원고가 비어 있습니다."
            }]
        }

    length = len(blog_article.strip())
    passed = BLOG_MIN_CHARS <= length <= BLOG_MAX_CHARS
    penalty = 0.0
    issues: List[Dict[str, Any]] = []

    if length < 1800:
        status = "serious_shortage"
        penalty = 4.0
        issues.append({
            "type": "warning",
            "component": "blog_length",
            "message": (
                f"블로그 원고 분량이 기준({BLOG_MIN_CHARS:,}~{BLOG_MAX_CHARS:,}자)보다 심각하게 부족합니다 "
                f"({length:,}자 / 최소 {BLOG_MIN_CHARS:,}자 필요). -4.0점 감점"
            )
        })
    elif length < BLOG_MIN_CHARS:
        status = "slight_shortage"
        penalty = 2.0
        issues.append({
            "type": "warning",
            "component": "blog_length",
            "message": (
                f"블로그 원고 분량이 기준({BLOG_MIN_CHARS:,}~{BLOG_MAX_CHARS:,}자)보다 다소 부족합니다 "
                f"({length:,}자 / 권장 {BLOG_MIN_CHARS:,}~{BLOG_MAX_CHARS:,}자). -2.0점 감점"
            )
        })
    elif length <= BLOG_MAX_CHARS:
        status = "optimal"
        penalty = 0.0
    elif length <= 2900:
        status = "slight_excess"
        penalty = 0.0
        issues.append({
            "type": "warning",
            "component": "blog_length",
            "message": (
                f"블로그 원고 분량이 권장 기준({BLOG_MIN_CHARS:,}~{BLOG_MAX_CHARS:,}자)을 소폭 초과했습니다 "
                f"({length:,}자)."
            )
        })
    else:
        status = "excessive"
        penalty = 1.0
        issues.append({
            "type": "warning",
            "component": "blog_length",
            "message": (
                f"블로그 원고 분량이 권장 기준({BLOG_MIN_CHARS:,}~{BLOG_MAX_CHARS:,}자)을 과도하게 초과했습니다 "
                f"({length:,}자). -1.0점 감점"
            )
        })

    return {
        "length": length,
        "target": BLOG_TARGET_CHARS,
        "expected_range": (BLOG_MIN_CHARS, BLOG_MAX_CHARS),
        "passed": passed,
        "status": status,
        "penalty": penalty,
        "issues": issues,
    }


def _check_blog_consistency(
    article_title: str,
    article_content: str,
    blog_article: Optional[str],
    target_singer: Optional[str]
) -> Tuple[float, List[Dict[str, Any]], bool, Dict[str, Any]]:
    """
    Validates blog article against original article:
    - 4-part structure integrity
    - Core singer representation
    - Absence of severe fake news or wild hallucinated claims
    - Blog length standard: 2,400 chars ±10% (2,160 ~ 2,640 chars)
    Returns: (score, issues, critical_error, details)
    """
    max_pts = 4.0
    score = max_pts
    issues: List[Dict[str, Any]] = []
    critical_error = False

    if not blog_article or not blog_article.strip():
        # Blog article was not provided: full score, evaluated = False
        return max_pts, issues, critical_error, {
            "score": max_pts,
            "max_score": max_pts,
            "evaluated": False,
            "reason": "Blog article not provided"
        }

    article_combined = f"{article_title}\n{article_content}"

    # 1. Singer grounding in blog
    if target_singer:
        valid_names = {target_singer}
        if target_singer in SINGER_ALIASES:
            valid_names.update(SINGER_ALIASES[target_singer])
        if not any(alias in blog_article for alias in valid_names):
            score = max(0.0, score - 1.5)
            issues.append({
                "type": "warning",
                "component": "factual",
                "message": f"블로그 본문에 핵심 가수 '{target_singer}'의 이름이 누락되었습니다."
            })

    # 2. Fake news / severe sensationalism in blog
    blog_critical_terms = []
    for term in CRITICAL_SENSATIONAL_TERMS:
        if term in blog_article and term not in article_combined:
            blog_critical_terms.append(term)
            score = max(0.0, score - 2.0)
            critical_error = True
            issues.append({
                "type": "error",
                "component": "factual",
                "message": f"원문에 없는 치명적 왜곡 표현 '{term}'이(가) 블로그 본문에서 발견되었습니다."
            })

    # 3. 4-part structure check (e.g. [사진 1], [사진 2], [사진 3], [사진 4] or 4 sections)
    photo_tags = re.findall(r"\[사진\s*\d+\]|\[이미지\s*\d+\]|###\s*\d+|【\d+】", blog_article)
    has_structure = len(photo_tags) >= 3 or (len(blog_article) >= 500 and "\n\n" in blog_article)
    if not has_structure:
        score = max(0.0, score - 1.0)
        issues.append({
            "type": "warning",
            "component": "factual",
            "message": "블로그 원고의 4단 구조(도입부, 현장, 반응, 마무리) 구분이 불명확합니다."
        })

    # 4. Standardized Blog Length Check (2,160 ~ 2,640 chars)
    len_res = validate_blog_length(blog_article)
    if len_res["penalty"] > 0:
        score = max(0.0, score - len_res["penalty"])
    issues.extend(len_res["issues"])

    details = {
        "score": round(score, 1),
        "max_score": max_pts,
        "evaluated": True,
        "photo_tags_found": photo_tags,
        "critical_terms": blog_critical_terms,
        "length_validation": len_res,
    }

    return details["score"], issues, critical_error, details


def validate_factual_consistency(
    article_title: str,
    article_content: str,
    shorts_script: str,
    blog_article: Optional[str] = None,
    singer_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    QA-2 Factual & Content Consistency Validator.
    Validates that shorts_script and blog_article are strictly grounded in original news article,
    and adhere to standardized length requirements.

    Point allocation: Maximum 30.0 points.
    - Singer & core subject grounding: 8.0 pts
    - Numbers & statistics fidelity: 10.0 pts
    - Sensationalism / distortion check: 8.0 pts
    - Blog structure, cohesion & length: 4.0 pts
    - Shorts narration length synchronization: (deductions applied if out of range)

    Returns:
    {
        "score": float (0.0 ~ 30.0),
        "max_score": 30.0,
        "passed": bool,
        "critical_error": bool,
        "issues": [{"type": "error"|"warning", "component": "factual", "message": "..."}],
        "details": {
            "singer_grounding": {...},
            "number_fidelity": {...},
            "sensationalism": {...},
            "blog_consistency": {...},
            "shorts_length": {...}
        }
    }
    """
    # 1. Resolve singer
    target_singer = _detect_singer(article_title, article_content, singer_name)

    # 2. Evaluate all sub-checks
    singer_score, singer_issues, singer_crit, singer_details = _check_singer_grounding(
        article_title, article_content, shorts_script, target_singer
    )

    num_score, num_issues, num_crit, num_details = _check_numbers_fidelity(
        article_title, article_content, shorts_script
    )

    sens_score, sens_issues, sens_crit, sens_details = _check_sensationalism_and_distortion(
        article_title, article_content, shorts_script
    )

    blog_score, blog_issues, blog_crit, blog_details = _check_blog_consistency(
        article_title, article_content, blog_article, target_singer
    )

    # 3. Standardized Shorts Narration Length Check (400 ~ 500 chars)
    shorts_len_res = validate_shorts_length(shorts_script)

    # 4. Aggregate totals
    raw_score = singer_score + num_score + sens_score + blog_score - shorts_len_res["penalty"]
    total_score = round(max(0.0, min(30.0, raw_score)), 1)

    all_issues = singer_issues + num_issues + sens_issues + blog_issues + shorts_len_res["issues"]
    has_critical_error = singer_crit or num_crit or sens_crit or blog_crit or (total_score < 15.0)

    # Pass condition: score >= 21.0 (70% of 30) AND no critical error
    passed = (total_score >= 21.0) and (not has_critical_error)

    return {
        "score": total_score,
        "max_score": 30.0,
        "passed": passed,
        "critical_error": has_critical_error,
        "issues": all_issues,
        "details": {
            "target_singer": target_singer,
            "singer_grounding": singer_details,
            "number_fidelity": num_details,
            "sensationalism": sens_details,
            "blog_consistency": blog_details,
            "shorts_length": shorts_len_res,
        }
    }
