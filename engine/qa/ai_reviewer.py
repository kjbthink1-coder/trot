"""
engine/qa/ai_reviewer.py - Multimodal AI Quality Reviewer for Shorts & Blog
==========================================================================
Calls Google Gemini Flash API to perform deep semantic, factual, and visual
cross-checking against the source news article, narration script, and video frames.

Enforces strict negative-only grading (no praises) and returns standardized
QA report JSON with graceful fallback on network or API failures.
"""

import os
import re
import json
import logging
from typing import List, Optional, Dict, Any

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

logger = logging.getLogger("qa.ai_reviewer")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Candidate models ordered by priority
CANDIDATE_GEMINI_MODELS = [
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash"
]

STRICT_SYSTEM_PROMPT_PREFIX = """당신은 엄격한 유튜브 쇼츠 및 블로그 품질 검수관입니다.
칭찬은 절대 금지하며, 사실 왜곡, 대본-화면 부조화, 어색한 문맥, 과도한 반복 표현 등 실제 감점 요인만 찾아내야 합니다.
문제가 없으면 issues에 빈 배열을 넣고 25.0 만점을 부여하세요."""

FALLBACK_RESULT: Dict[str, Any] = {
    "score": None,
    "max_score": 25.0,
    "status": "AI_QA_NOT_RUN",
    "ai_not_run": True,
    "critical_error": False,
    "issues": [
        {
            "issue_type": "ai_qa_not_run",
            "severity": "medium",
            "scene_index": None,
            "start_time": None,
            "end_time": None,
            "evidence": "Gemini API 미연결 또는 응답 실패로 인하여 멀티모달 AI 심층 검수를 수행하지 못했습니다.",
            "repairable": False,
            "repair_action": None,
            "component": "ai_review",
            "type": "warning",
            "message": "AI 심층 리뷰 미실행 (API 확인 필요 - 수동 확인 권장)"
        }
    ],
    "recommendations": [
        "AI 심층 리뷰 미실행 (API 확인 필요 - 수동 확인 권장)"
    ]
}


def get_gemini_api_key(api_key: Optional[str] = None) -> Optional[str]:
    """
    Retrieves the Gemini API key from the function argument, environment variables,
    or by traversing upwards to find a .env file.
    """
    if api_key and api_key.strip():
        return api_key.strip()

    env_val = os.environ.get("GEMINI_API_KEY")
    if env_val and env_val.strip():
        return env_val.strip()

    # Search for .env in current and parent directories
    search_dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        candidate = os.path.join(search_dir, ".env")
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GEMINI_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if key:
                                return key
            except Exception:
                pass
        parent = os.path.dirname(search_dir)
        if parent == search_dir:
            break
        search_dir = parent

    return None


def build_qa_prompt(
    article_title: str,
    article_content: str,
    shorts_script: str,
    blog_article: Optional[str] = None,
    singer_name: Optional[str] = None,
    has_frames: bool = False
) -> str:
    """
    Constructs the rigorous prompt instructing Gemini to inspect for issues only.
    """
    singer_text = f"대상 가수: {singer_name}\n" if singer_name else ""
    blog_section = f"\n[블로그 원고 본문]\n{blog_article[:3000]}\n" if blog_article else "\n[블로그 원고]\n(제공되지 않음 - 검수 생략)\n"

    frame_instructions = (
        "- 첨부된 이미지들은 비디오의 대표 프레임들입니다. 화면 속 인물, 배경, 분위기가 쇼츠 대본 내용과 일치하는지, "
        "어색한 B-roll이나 부조화가 있는지 면밀히 검수하세요.\n"
        if has_frames else
        "- 영상 프레임이 첨부되지 않았으므로 대본과 원문 기사의 정합성 및 문맥 검수에 집중하세요.\n"
    )

    prompt = f"""{STRICT_SYSTEM_PROMPT_PREFIX}

[검수 대상 정보]
{singer_text}기사 제목: {article_title}
기사 본문:
{article_content[:3500]}

[쇼츠 나레이션 대본]
{shorts_script}
{blog_section}
[영상 프레임 검수 지침]
{frame_instructions}
[엄격한 채점 및 감점 기준 (총점 25.0점 만점)]
1. 사실 왜곡 및 기사 대비 왜곡 (최대 10.0점 감점)
   - 원문 기사에 없는 치명적 왜곡, 인물 이름 오기, 날짜/사건 과장이나 허위 날조가 있으면 감점
2. 대본과 화면의 불일치 / 어색한 B-roll (최대 8.0점 감점)
   - 첨부된 영상 프레임의 인물/배경/분위기가 대본 내용과 심각하게 동떨어진 경우 감점
3. 어색한 문맥 및 무의미한 반복 문장 (최대 5.0점 감점)
   - 무의미한 반복 문장, 어색한 호흡, 과도하게 장황한 미사여구 감점
4. 블로그 원고와의 정합성 (최대 2.0점 감점, 블로그 제공 시에만 해당)
   - 블로그 원고 내용이 기사 및 쇼츠 대본과 모순되는 경우 감점

[점수 산출 공식]
- 점수 = 25.0 - (총 감점 점수)
- score 범위: 0.0 ~ 25.0 (소수점 1자리)
- max_score: 25.0
- 문제가 전혀 없으면 score는 25.0 만점이고 issues는 [] 빈 배열이어야 합니다.
- status 판정 기준:
  * PASS: score >= 20.0 이고 error 등급 이슈가 없음
  * WARNING: 15.0 <= score < 20.0 이거나 warning 등급 이슈만 있음
  * FAIL: score < 15.0 이거나 치명적인 오류(error 등급 이슈)가 있음
- critical_error: 원문 날조, 인물 오기 등 영상 폐기 수준의 심각한 오류가 있을 때만 true, 그 외는 false

[반드시 준수할 JSON 출력 규격]
마크다운 서식이나 추가 설명 없이 순수 JSON 객체만 반환하세요:
{{
  "score": 25.0,
  "max_score": 25.0,
  "status": "PASS",
  "critical_error": false,
  "issues": [
    {{
      "issue_type": "scene_mismatch",
      "severity": "medium",
      "scene_index": 1,
      "start_time": 0.0,
      "end_time": 5.0,
      "evidence": "1번 프레임의 인물이 대본에 언급된 가수와 불일치함",
      "repairable": true,
      "repair_action": "replace_photo",
      "component": "ai_review",
      "type": "warning",
      "message": "대본과 프레임 이미지 불일치"
    }}
  ],
  "recommendations": [
    "구체적인 개선 방안"
  ]
}}"""
    return prompt


def sanitize_review_response(data: Any) -> dict:
    """
    Validates and normalizes the parsed dictionary into the standard QA output schema.
    """
    if not isinstance(data, dict):
        return dict(FALLBACK_RESULT)

    raw_score = data.get("score")
    if raw_score is None:
        return dict(FALLBACK_RESULT)

    try:
        score = float(raw_score)
        score = max(0.0, min(25.0, score))
    except (ValueError, TypeError):
        return dict(FALLBACK_RESULT)

    max_score = 25.0

    raw_status = str(data.get("status", "")).upper()
    if raw_status in ("PASS", "WARNING", "FAIL", "AI_QA_NOT_RUN", "NOT_RUN"):
        status = raw_status
    else:
        status = "PASS" if score >= 20.0 else ("WARNING" if score >= 15.0 else "FAIL")

    critical_error = bool(data.get("critical_error", False))

    raw_issues = data.get("issues", [])
    issues: List[Dict[str, Any]] = []
    if isinstance(raw_issues, list):
        for item in raw_issues:
            if isinstance(item, dict):
                comp = str(item.get("component", "ai_review"))
                itype = str(item.get("type", "warning")).lower()
                if itype not in ("warning", "error", "info"):
                    itype = "warning"
                
                # Structured metadata
                issue_type = str(item.get("issue_type", "scene_mismatch" if "화면" in str(item) else "ai_review_issue"))
                raw_severity = str(item.get("severity", "")).lower()
                if raw_severity in ("high", "medium", "low"):
                    severity = raw_severity
                else:
                    severity = "high" if itype == "error" else ("medium" if itype == "warning" else "low")

                scene_idx = item.get("scene_index")
                if scene_idx is not None:
                    try:
                        scene_idx = int(scene_idx)
                    except (ValueError, TypeError):
                        scene_idx = None

                start_t = item.get("start_time")
                if start_t is not None:
                    try:
                        start_t = float(start_t)
                    except (ValueError, TypeError):
                        start_t = None

                end_t = item.get("end_time")
                if end_t is not None:
                    try:
                        end_t = float(end_t)
                    except (ValueError, TypeError):
                        end_t = None

                msg = str(item.get("message", "")).strip()
                evidence = str(item.get("evidence", msg)).strip()
                if not msg and evidence:
                    msg = evidence
                elif not evidence and msg:
                    evidence = msg

                repairable = bool(item.get("repairable", True))
                repair_action = item.get("repair_action")
                if repair_action is not None:
                    repair_action = str(repair_action).strip()

                if msg:
                    issues.append({
                        "issue_type": issue_type,
                        "severity": severity,
                        "scene_index": scene_idx,
                        "start_time": start_t,
                        "end_time": end_t,
                        "evidence": evidence,
                        "repairable": repairable,
                        "repair_action": repair_action,
                        "component": comp,
                        "type": itype,
                        "message": msg
                    })

    # Adjust status and critical_error if error issues present
    has_error = any(iss["type"] == "error" or iss["severity"] == "high" for iss in issues)
    if has_error or critical_error:
        status = "FAIL"
        if score > 15.0:
            score = 14.5
    elif not issues and score >= 20.0:
        status = "PASS"

    raw_recs = data.get("recommendations", [])
    recommendations: List[str] = []
    if isinstance(raw_recs, list):
        for rec in raw_recs:
            if isinstance(rec, str) and rec.strip():
                recommendations.append(rec.strip())

    return {
        "score": round(score, 1),
        "max_score": max_score,
        "status": status,
        "ai_not_run": False,
        "critical_error": critical_error,
        "issues": issues,
        "recommendations": recommendations
    }


def parse_json_from_response(raw_text: str) -> Optional[dict]:
    """
    Safely parses JSON from Gemini's response text, handling code blocks and trailing noise.
    """
    if not raw_text or not raw_text.strip():
        return None

    cleaned = raw_text.strip()
    # Strip markdown code fencing if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except Exception:
        # Attempt regex extraction of the first JSON object
        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
    return None


def review_with_ai(
    article_title: str,
    article_content: str,
    shorts_script: str,
    blog_article: Optional[str] = None,
    frame_paths: Optional[List[str]] = None,
    singer_name: Optional[str] = None,
    api_key: Optional[str] = None
) -> dict:
    """
    Performs multimodal AI quality inspection using Google Gemini Flash models.

    Args:
        article_title: Source news article headline.
        article_content: Full news article body text.
        shorts_script: Generated 50-60s shorts narration script.
        blog_article: Optional blog draft content.
        frame_paths: Optional list of representative frame image paths.
        singer_name: Optional target artist/singer name.
        api_key: Optional Gemini API key (defaults to GEMINI_API_KEY from .env / environ).

    Returns:
        Structured dictionary adhering to QA-4 schema:
        {
            "score": float (0.0 ~ 25.0),
            "max_score": 25.0,
            "status": "PASS" | "WARNING" | "FAIL" | "NOT_RUN",
            "critical_error": bool,
            "issues": [...],
            "recommendations": [...]
        }
    """
    resolved_key = get_gemini_api_key(api_key)
    if not resolved_key:
        logger.warning("Gemini API key not found; returning neutral safe fallback.")
        return dict(FALLBACK_RESULT)

    # Load valid representative frame images if available
    loaded_images = []
    if frame_paths:
        for fp in frame_paths:
            if fp and os.path.isfile(fp) and os.path.getsize(fp) > 0:
                try:
                    from PIL import Image
                    img = Image.open(fp)
                    loaded_images.append(img)
                except Exception as ie:
                    logger.debug(f"Could not load image {fp} for AI review: {ie}")

    has_frames = len(loaded_images) > 0
    prompt_text = build_qa_prompt(
        article_title=article_title,
        article_content=article_content,
        shorts_script=shorts_script,
        blog_article=blog_article,
        singer_name=singer_name,
        has_frames=has_frames
    )

    # Prepare multimodal contents list (images first, then prompt text)
    contents_multimodal: List[Any] = list(loaded_images) + [prompt_text]
    contents_text_only: List[Any] = [prompt_text]

    # Attempt Google GenAI SDK (google.genai)
    try:
        from google import genai
        client = genai.Client(api_key=resolved_key)

        for model_name in CANDIDATE_GEMINI_MODELS:
            # 1. Try with multimodal images + prompt
            for contents_to_try in ([contents_multimodal] if has_frames else []) + [contents_text_only]:
                try:
                    logger.info(f"Calling Gemini ({model_name}) with {len(contents_to_try)} parts...")
                    res = client.models.generate_content(
                        model=model_name,
                        contents=contents_to_try,
                        config={"response_mime_type": "application/json"}
                    )
                    if res and res.text:
                        parsed = parse_json_from_response(res.text)
                        if parsed:
                            sanitized = sanitize_review_response(parsed)
                            logger.info(
                                f"Gemini review succeeded with {model_name}: "
                                f"score={sanitized['score']}, status={sanitized['status']}, issues={len(sanitized['issues'])}"
                            )
                            return sanitized
                except Exception as model_err:
                    logger.debug(f"Model {model_name} attempt failed with error: {model_err}")
                    continue

    except ImportError:
        logger.debug("google.genai SDK not available; attempting google.generativeai fallback.")
    except Exception as e:
        logger.warning(f"Unexpected error during google.genai review: {e}")

    # Fallback to legacy google.generativeai if available
    try:
        import google.generativeai as legacy_genai
        legacy_genai.configure(api_key=resolved_key)

        for model_name in ["gemini-1.5-flash", "gemini-pro"]:
            try:
                gen_model = legacy_genai.GenerativeModel(model_name)
                res = gen_model.generate_content(contents_multimodal if has_frames else contents_text_only)
                if res and res.text:
                    parsed = parse_json_from_response(res.text)
                    if parsed:
                        sanitized = sanitize_review_response(parsed)
                        logger.info(f"Legacy Gemini review succeeded with {model_name}")
                        return sanitized
            except Exception as leg_err:
                logger.debug(f"Legacy model {model_name} failed: {leg_err}")
                continue
    except Exception:
        pass

    # Fail-safe: Under any network, quota, or parsing fault, never crash
    logger.warning("AI review could not complete across all candidate models; using fail-safe neutral response.")
    return dict(FALLBACK_RESULT)
