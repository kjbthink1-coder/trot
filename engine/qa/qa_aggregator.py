"""
engine/qa/qa_aggregator.py - Unified QA Aggregator & Orchestrator
================================================================
Orchestrates the 4-phase Quality Assurance inspection pipeline for YouTube Shorts
and blog content:
  1. QA-1 Technical Validator (Max 20.0 pts)
  2. QA-2 Factual Validator (Max 30.0 pts)
  3. QA-3 Repetition Validator (Max 25.0 pts)
  4. QA-4 AI Reviewer (Max 25.0 pts)

Aggregates total score (0.0 ~ 100.0 pts), determines quality verdict (PASS, WARNING, FAIL, NOT_RUN),
persists results to media_library.db via record_qa_result, and generates actionable recommendations.
"""

import os
import sys
import time
import logging
from typing import List, Optional, Dict, Any

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine.qa.technical_validator import validate_technical_quality
from engine.qa.factual_validator import validate_factual_consistency
from engine.qa.repetition_validator import validate_repetition
from engine.qa.frame_extractor import extract_representative_frames, cleanup_frames
from engine.qa.ai_reviewer import review_with_ai
from engine.media_db import record_qa_result

logger = logging.getLogger("qa.aggregator")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def normalize_issue(iss: Dict[str, Any], default_component: str = "general") -> Dict[str, Any]:
    """
    Normalizes issue dictionary to include all required structured metadata (Item 7):
      - issue_type: str (e.g. 'caption_overflow', 'number_discrepancy', 'photo_repetition', 'scene_mismatch')
      - severity: 'high' | 'medium' | 'low'
      - scene_index: Optional[int]
      - start_time: Optional[float]
      - end_time: Optional[float]
      - evidence: str
      - repairable: bool
      - repair_action: Optional[str]
    Preserves backward compatibility fields (component, type, message).
    """
    comp = str(iss.get("component") or default_component)
    raw_type = str(iss.get("type", "warning")).lower()
    msg = str(iss.get("message", "")).strip()

    raw_sev = str(iss.get("severity", "")).lower()
    if raw_sev in ("high", "medium", "low"):
        severity = raw_sev
    elif raw_type == "error":
        severity = "high"
    elif raw_type == "info":
        severity = "low"
    else:
        severity = "medium"

    issue_type = iss.get("issue_type")
    if not issue_type:
        msg_l = msg.lower()
        if "caption" in msg_l or "자막" in msg:
            issue_type = "caption_overflow"
        elif "숫자" in msg or "number" in msg_l or "통계" in msg:
            issue_type = "number_discrepancy"
        elif "사진" in msg or "photo" in msg_l:
            issue_type = "photo_repetition"
        elif "b-roll" in msg_l or "broll" in msg_l or "짤" in msg:
            issue_type = "broll_repetition"
        elif "hook" in msg_l or "후킹" in msg:
            issue_type = "hook_repetition"
        elif "가수" in msg or "인물" in msg or "singer" in msg_l:
            issue_type = "singer_mismatch"
        elif "화면" in msg or "frame" in msg_l:
            issue_type = "scene_mismatch"
        elif "해상도" in msg or "fps" in msg_l or "비트레이트" in msg:
            issue_type = "video_spec_mismatch"
        elif "싱크" in msg or "audio" in msg_l or "음성" in msg:
            issue_type = "audio_sync"
        elif "ai_qa_not_run" in msg_l or "미실행" in msg:
            issue_type = "ai_qa_not_run"
        else:
            issue_type = f"{comp}_issue"

    evidence = iss.get("evidence")
    if not evidence:
        evidence = msg or f"{comp} issue detected."

    repairable = iss.get("repairable")
    repair_action = iss.get("repair_action")
    if repairable is None:
        if issue_type in ("caption_overflow", "caption_position"):
            repairable = True
            repair_action = repair_action or "caption_resize"
        elif issue_type in ("photo_repetition", "scene_mismatch"):
            repairable = True
            repair_action = repair_action or "replace_photo"
        elif issue_type in ("broll_repetition",):
            repairable = True
            repair_action = repair_action or "replace_broll"
        elif issue_type in ("hook_repetition", "sensationalism", "number_discrepancy"):
            repairable = True
            repair_action = repair_action or "rephrase_script"
        elif issue_type in ("ai_qa_not_run",):
            repairable = False
            repair_action = None
        else:
            repairable = False

    scene_idx = iss.get("scene_index")
    if scene_idx is not None:
        try:
            scene_idx = int(scene_idx)
        except (ValueError, TypeError):
            scene_idx = None

    start_t = iss.get("start_time")
    if start_t is not None:
        try:
            start_t = float(start_t)
        except (ValueError, TypeError):
            start_t = None

    end_t = iss.get("end_time")
    if end_t is not None:
        try:
            end_t = float(end_t)
        except (ValueError, TypeError):
            end_t = None

    return {
        "issue_type": str(issue_type),
        "severity": severity,
        "scene_index": scene_idx,
        "start_time": start_t,
        "end_time": end_t,
        "evidence": str(evidence),
        "repairable": bool(repairable),
        "repair_action": str(repair_action) if repair_action else None,
        "component": comp,
        "type": raw_type,
        "message": msg or str(evidence)
    }


def run_full_qa(
    video_path: str,
    article_title: str,
    article_content: str,
    shorts_script: str,
    blog_article: Optional[str] = None,
    singer_name: Optional[str] = None,
    tts_audio_path: Optional[str] = None,
    srt_path: Optional[str] = None,
    images: Optional[List[str]] = None,
    broll_path: Optional[str] = None,
    singer_clips: Optional[List[str]] = None,
    timeline_segments: Optional[List[Dict[str, Any]]] = None,
    api_key: Optional[str] = None,
    project_id: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes the comprehensive QA verification pipeline across all 4 validators.

    Args:
        video_path: Path to the generated 1080x1920 MP4 video.
        article_title: Source news article title.
        article_content: Source news article body text.
        shorts_script: Narration script used in the video.
        blog_article: Optional blog post draft.
        singer_name: Optional singer/artist name.
        tts_audio_path: Optional synthesized TTS audio file.
        srt_path: Optional SRT subtitle file.
        images: Optional list of image paths used.
        broll_path: Optional B-roll video clip path.
        api_key: Optional Gemini API key.
        project_id: Optional project identifier.
        db_path: Optional SQLite media database path.

    Returns:
        Standardized dict containing:
        - status: 'PASS' | 'WARNING' | 'FAIL' | 'NOT_RUN'
        - total_score: float (0.0 ~ 100.0)
        - max_score: 100.0
        - passed: bool
        - critical_error: bool
        - category_scores: dict
        - issues: list
        - recommendations: list
        - details: dict
        - db_record: dict or None
    """
    try:
        logger.info(f"Starting Full QA verification for video: {video_path}")

        # -------------------------------------------------------------
        # 1. QA-1 Technical Validator (Max 20.0 pts)
        # -------------------------------------------------------------
        try:
            tech_res = validate_technical_quality(
                video_path=video_path,
                tts_audio_path=tts_audio_path,
                srt_path=srt_path,
                images=images,
                broll_path=broll_path
            )
        except Exception as e_tech:
            logger.error(f"QA-1 Technical Validator crashed: {e_tech}")
            tech_res = {
                "score": 0.0,
                "max_score": 20.0,
                "passed": False,
                "critical_error": True,
                "issues": [{"type": "error", "component": "technical", "message": f"기술 검증 실패: {e_tech}"}],
                "details": {}
            }

        # -------------------------------------------------------------
        # 2. QA-2 Factual Validator (Max 30.0 pts)
        # -------------------------------------------------------------
        try:
            fact_res = validate_factual_consistency(
                article_title=article_title,
                article_content=article_content,
                shorts_script=shorts_script,
                blog_article=blog_article,
                singer_name=singer_name
            )
        except Exception as e_fact:
            logger.error(f"QA-2 Factual Validator crashed: {e_fact}")
            fact_res = {
                "score": 0.0,
                "max_score": 30.0,
                "passed": False,
                "critical_error": True,
                "issues": [{"type": "error", "component": "factual", "message": f"사실 검증 실패: {e_fact}"}],
                "details": {}
            }

        # -------------------------------------------------------------
        # 3. QA-3 Repetition Validator (Max 25.0 pts)
        # -------------------------------------------------------------
        try:
            brolls = ([broll_path] if broll_path else []) + (singer_clips or [])
            rep_res = validate_repetition(
                singer_name=singer_name or "",
                current_images=images or [],
                current_brolls=brolls,
                current_script=shorts_script,
                db_path=db_path
            )
        except Exception as e_rep:
            logger.error(f"QA-3 Repetition Validator crashed: {e_rep}")
            rep_res = {
                "score": 0.0,
                "max_score": 25.0,
                "passed": False,
                "critical_error": False,
                "issues": [{"type": "warning", "component": "repetition", "message": f"반복성 검증 실패: {e_rep}"}],
                "details": {}
            }

        # -------------------------------------------------------------
        # 4. QA-4 AI Reviewer (Max 25.0 pts)
        # -------------------------------------------------------------
        extracted_frames: List[str] = []
        try:
            if video_path and os.path.exists(video_path):
                extracted_frames = extract_representative_frames(video_path, count=5, timeline_segments=timeline_segments)
            
            ai_res = review_with_ai(
                article_title=article_title,
                article_content=article_content,
                shorts_script=shorts_script,
                blog_article=blog_article,
                frame_paths=extracted_frames,
                singer_name=singer_name,
                api_key=api_key
            )
        except Exception as e_ai:
            logger.error(f"QA-4 AI Reviewer crashed: {e_ai}")
            ai_res = {
                "score": None,
                "max_score": 25.0,
                "status": "AI_QA_NOT_RUN",
                "ai_not_run": True,
                "critical_error": False,
                "issues": [{
                    "issue_type": "ai_qa_not_run",
                    "severity": "medium",
                    "scene_index": None,
                    "start_time": None,
                    "end_time": None,
                    "evidence": f"AI 심층 리뷰 미실행 ({e_ai})",
                    "repairable": True,
                    "repair_action": "rerun_ai_qa",
                    "component": "ai_review",
                    "type": "warning",
                    "message": "AI 심층 리뷰 미실행 (API 확인 필요 - 수동 확인 권장)"
                }],
                "recommendations": ["AI 심층 리뷰 미실행 (API 확인 필요 - 아래 원클릭 수정 버튼으로 즉시 실행)"]
            }
        finally:
            if extracted_frames:
                cleanup_frames(extracted_frames)

        # -------------------------------------------------------------
        # 5. Score Aggregation (Item 1 & Item 2)
        # -------------------------------------------------------------
        ai_not_run = bool(
            ai_res.get("ai_not_run", False)
            or ai_res.get("status") in ("AI_QA_NOT_RUN", "NOT_RUN")
            or ai_res.get("score") is None
        )

        tech_score = float(tech_res.get("score", 0.0))
        fact_score = float(fact_res.get("score", 0.0))
        rep_score = float(rep_res.get("score", 0.0))

        if ai_not_run:
            content_quality_score = None
            raw_total = tech_score + fact_score + rep_score
        else:
            content_quality_score = float(ai_res.get("score", 0.0))
            raw_total = tech_score + fact_score + rep_score + content_quality_score

        total_score = round(max(0.0, min(100.0, raw_total)), 1)

        # Critical error check across all validators
        critical_error = bool(
            tech_res.get("critical_error", False)
            or fact_res.get("critical_error", False)
            or rep_res.get("critical_error", False)
            or ai_res.get("critical_error", False)
        )

        # Status determination:
        # FAIL: critical error is True or total_score < 70.0 (or either validator failed)
        # WARNING: if AI review did not run, or 70.0 <= total_score < 90.0
        # PASS: total_score >= 90.0, AI review succeeded, and no critical error
        if critical_error or total_score < 70.0 or tech_res.get("status") == "FAIL" or fact_res.get("status") == "FAIL":
            status = "FAIL"
        elif ai_not_run:
            status = "WARNING"  # Force WARNING when AI review was not run!
        elif total_score < 90.0:
            status = "WARNING"
        else:
            status = "PASS"

        # Combine and normalize all detected issues (Item 7)
        all_issues: List[Dict[str, Any]] = []
        for src, comp_name in [
            (tech_res, "technical"),
            (fact_res, "factual"),
            (rep_res, "repetition"),
            (ai_res, "ai_review")
        ]:
            for iss in src.get("issues", []):
                all_issues.append(normalize_issue(iss, default_component=comp_name))

        # -------------------------------------------------------------
        # 6. Recommendation Synthesis
        # -------------------------------------------------------------
        recommendations: List[str] = []

        if ai_not_run:
            recommendations.append("⚠️ AI 심층 리뷰 미실행 (API 확인 필요 - 수동 확인 권장)")

        if status == "PASS":
            recommendations.append("✅ 유튜브 쇼츠 및 블로그 업로드 강력 추천 (모든 알고리즘 안전 기준 충족)")
        elif status == "WARNING":
            recommendations.append("⚠️ 유튜브 업로드 전 주의 항목 검토 권장 (아래 세부 리포트 확인)")
        else:
            recommendations.append("❌ 치명적 결함 또는 낮은 품질 점수 발견 - 수정 후 재렌더링 권장")

        # Specific actionable recommendations based on issues
        if tech_score < 15.0:
            recommendations.append("🔧 기술 점검: 해상도(1080x1920 세로형) 또는 음성 싱크를 재확인하세요.")
        if fact_score < 22.0:
            recommendations.append("📰 사실 점검: 대본 속 가수명, 숫자(조회수/순위), 자극적 어휘를 원문 기사와 대조하세요.")
        if rep_score < 18.0:
            recommendations.append("🔄 신선도 점검: 이전 영상에서 사용된 사진 또는 짤이 다수 중복되었습니다. 새로운 사진을 선별하세요.")

        # Include AI Review recommendations
        for ai_rec in ai_res.get("recommendations", []):
            if isinstance(ai_rec, str) and ai_rec.strip() and ai_rec.strip() not in recommendations:
                recommendations.append(ai_rec.strip())

        # Deduplicate recommendations preserving order
        deduped_recs: List[str] = []
        for rec in recommendations:
            if rec not in deduped_recs:
                deduped_recs.append(rec)

        # -------------------------------------------------------------
        # 7. Persist to SQLite (media_db.record_qa_result)
        # -------------------------------------------------------------
        resolved_proj_id = project_id or f"qa_{int(time.time())}"
        resolved_singer = singer_name or "미지정"
        db_record = None
        try:
            db_record = record_qa_result(
                project_id=resolved_proj_id,
                singer_name=resolved_singer,
                technical_score=tech_score,
                factual_score=fact_score,
                repetition_score=rep_score,
                content_score=content_quality_score,
                total_score=total_score,
                status=status,
                issues=all_issues,
                recommendations=deduped_recs,
                critical_error=critical_error,
                shorts_result={
                    "technical": tech_res,
                    "factual": fact_res,
                    "repetition": rep_res,
                    "content_quality": ai_res,
                    "ai_review": ai_res
                },
                blog_result=fact_res.get("details", {}).get("blog_consistency", {}),
                qa_model="rule+gemini",
                db_path=db_path
            )
            logger.info(f"Persisted QA result to DB. ID: {db_record.get('id')}, Status: {status}, Score: {total_score}")
        except Exception as e_db:
            logger.warning(f"Could not persist QA result to media_db: {e_db}")

        category_scores = {
            "technical": {
                "score": tech_score,
                "max_score": 20.0,
                "passed": tech_res.get("passed", False),
                "name": "기술 규격 (20점)"
            },
            "technical_specs": {
                "score": tech_score,
                "max_score": 20.0,
                "passed": tech_res.get("passed", False),
                "name": "기술 규격 (20점)"
            },
            "factual": {
                "score": fact_score,
                "max_score": 30.0,
                "passed": fact_res.get("passed", False),
                "name": "사실성/일치도 (30점)"
            },
            "fact_accuracy": {
                "score": fact_score,
                "max_score": 30.0,
                "passed": fact_res.get("passed", False),
                "name": "사실성/일치도 (30점)"
            },
            "repetition": {
                "score": rep_score,
                "max_score": 25.0,
                "passed": rep_res.get("passed", False),
                "name": "반복/다양성 (25점)"
            },
            "repeat_prevention": {
                "score": rep_score,
                "max_score": 25.0,
                "passed": rep_res.get("passed", False),
                "name": "반복/다양성 (25점)"
            },
            "content_quality": {
                "score": content_quality_score,
                "max_score": 25.0,
                "passed": (content_quality_score is not None and content_quality_score >= 20.0),
                "ai_not_run": ai_not_run,
                "name": "콘텐츠 완성도 (25점)"
            },
            "ai_review": {
                "score": content_quality_score,
                "max_score": 25.0,
                "passed": (content_quality_score is not None and content_quality_score >= 20.0),
                "ai_not_run": ai_not_run,
                "name": "콘텐츠 완성도 (25점)"
            }
        }

        return {
            "status": status,
            "total_score": total_score,
            "max_score": 100.0,
            "passed": (status == "PASS"),
            "critical_error": critical_error,
            "ai_not_run": ai_not_run,
            "technical_score": tech_score,
            "factual_score": fact_score,
            "repetition_score": rep_score,
            "content_quality_score": content_quality_score,
            "ai_score": content_quality_score,
            "category_scores": category_scores,
            "issues": all_issues,
            "recommendations": deduped_recs,
            "details": {
                "technical": tech_res,
                "factual": fact_res,
                "repetition": rep_res,
                "content_quality": ai_res,
                "ai_review": ai_res
            },
            "db_record": db_record
        }

    except Exception as exc:
        logger.critical(f"Unexpected crash in run_full_qa aggregator: {exc}", exc_info=True)
        # Fail-safe: Return safe NOT_RUN dict without throwing error or damaging video
        return {
            "status": "NOT_RUN",
            "total_score": 0.0,
            "max_score": 100.0,
            "passed": False,
            "critical_error": False,
            "ai_not_run": True,
            "technical_score": 0.0,
            "factual_score": 0.0,
            "repetition_score": 0.0,
            "content_quality_score": None,
            "ai_score": None,
            "category_scores": {
                "technical": {"score": 0.0, "max_score": 20.0, "passed": False, "name": "기술 규격 (20점)"},
                "factual": {"score": 0.0, "max_score": 30.0, "passed": False, "name": "사실성/일치도 (30점)"},
                "repetition": {"score": 0.0, "max_score": 25.0, "passed": False, "name": "반복/다양성 (25점)"},
                "content_quality": {"score": None, "max_score": 25.0, "passed": False, "ai_not_run": True, "name": "콘텐츠 완성도 (25점)"},
                "ai_review": {"score": None, "max_score": 25.0, "passed": False, "ai_not_run": True, "name": "콘텐츠 완성도 (25점)"}
            },
            "issues": [normalize_issue({
                "issue_type": "qa_pipeline_crash",
                "severity": "high",
                "component": "qa_aggregator",
                "type": "error",
                "message": f"QA 종합 검수 파이프라인 오류: {str(exc)}"
            })],
            "recommendations": ["QA 파이프라인 비정상 종료. 시스템 로그를 확인하세요."],
            "details": {},
            "db_record": None
        }
