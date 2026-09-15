"""
engine/qa/repetition_validator.py - QA-3 Repetition & Freshness Validator
========================================================================
Independent quality assurance validator for media asset freshness and repetition control.
Inspects candidate media, scripts, and hooks against historical projects of the same singer
stored in media_library.db without altering database records.

Validation Aspects (25.0 pts Max):
  1. Photo Duplication (12.0 pts):
     - Calculates SHA-256 / path overlaps against the last 3~5 projects for the singer.
     - 1 duplicate is treated as a standard core news photo exception (0 pt penalty).
     - 20~49% duplicate ratio: -4.0 pts deduction + WARNING.
     - >=50% duplicate ratio: -10.0 pts deduction + WARNING.
  2. B-roll Freshness (7.0 pts):
     - Detects consecutive usage of the exact same clip across recent projects.
     - 3+ consecutive uses: -5.0 pts deduction + WARNING.
     - 2 consecutive uses: -3.0 pts deduction + WARNING.
     - 1 consecutive use (immediate prior): -1.0 pt deduction + WARNING.
  3. Hook Formula Freshness (6.0 pts):
     - Evaluates word-level Jaccard similarity between candidate hook / script opening
       and previous project hooks/titles/openings.
     - > 70% similarity: deduct up to 5.0 pts + WARNING.

If no prior projects exist in the DB for the singer, full 25.0 points are awarded.
"""

import os
import sys
import re
import json
import hashlib
import logging
from typing import Optional, List, Dict, Any, Tuple, Set

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine.media_db import (
    DEFAULT_DB_PATH,
    get_db_connection,
    get_recent_singer_projects,
    compute_file_hash,
    compute_dhash,
    hamming_distance,
    find_near_duplicate_photos,
)

logger = logging.getLogger("qa.repetition_validator")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

MAX_PHOTO_SCORE = 12.0
MAX_BROLL_SCORE = 7.0
MAX_HOOK_SCORE = 6.0
TOTAL_MAX_SCORE = 25.0


def compute_file_hash_safe(file_path: str) -> str:
    """
    Computes SHA-256 hex digest for existing files.
    If the file does not exist on disk (e.g. mock paths in tests),
    derives a deterministic SHA-256 from the normalized file path.
    """
    norm_path = os.path.abspath(os.path.normpath(file_path))
    if os.path.isfile(norm_path):
        try:
            return compute_file_hash(norm_path)
        except Exception as e:
            logger.debug(f"Failed to compute physical file hash for {norm_path}: {e}")
    
    # Deterministic fallback for mock / virtual paths
    return hashlib.sha256(norm_path.lower().encode("utf-8")).hexdigest()


def tokenize_words(text: str) -> List[str]:
    """
    Extracts alphanumeric and Korean word tokens, discarding punctuation.
    """
    if not text:
        return []
    tokens = re.findall(r'[가-힣a-zA-Z0-9]+', text)
    return [t.strip().lower() for t in tokens if t.strip()]


def calculate_jaccard_similarity(text1: str, text2: str) -> float:
    """
    Calculates word-level Jaccard similarity between two texts.
    Returns value in range [0.0, 1.0].
    """
    words1 = set(tokenize_words(text1))
    words2 = set(tokenize_words(text2))
    if not words1 or not words2:
        return 0.0
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    return intersection / union if union > 0 else 0.0


def extract_hook_sentence(current_hook: Optional[str] = None, current_script: Optional[str] = None) -> Optional[str]:
    """
    Extracts the hook sentence either from explicit current_hook or
    the opening sentence/line of current_script.
    """
    if current_hook and current_hook.strip():
        return current_hook.strip()
    if not current_script or not current_script.strip():
        return None
    
    lines = [line.strip() for line in current_script.strip().splitlines() if line.strip()]
    if not lines:
        return None
    first_line = lines[0]
    # Extract first sentence up to period, exclamation, or question mark
    sentences = re.split(r'(?<=[.?!])\s+', first_line)
    return sentences[0].strip() if sentences else first_line


def get_past_hooks_from_db(singer_name: str, limit: int = 5, db_path: Optional[str] = None) -> List[str]:
    """
    Read-only query to media_library.db qa_results table to extract past hooks/scripts.
    Does not modify database.
    """
    target_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
    if not os.path.exists(target_path):
        return []

    past_hooks = []
    try:
        with get_db_connection(target_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT shorts_result_json
                FROM qa_results
                WHERE singer_name = ? COLLATE NOCASE
                ORDER BY created_at DESC LIMIT ?
            """, (singer_name.strip(), limit))
            rows = cur.fetchall()
            for r in rows:
                raw = r["shorts_result_json"]
                if not raw:
                    continue
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(data, dict):
                        for key in ("hook", "first_sentence", "title", "script", "shorts_script"):
                            val = data.get(key)
                            if val and isinstance(val, str) and val.strip():
                                past_hooks.append(val.strip())
                                break
                    elif isinstance(data, str) and data.strip():
                        past_hooks.append(data.strip())
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"Read-only query for past hooks in qa_results: {e}")

    return past_hooks


def check_photo_duplication(
    current_images: List[str],
    recent_projects: List[Dict[str, Any]],
    threshold: int = 5,
    db_path: Optional[str] = None
) -> Tuple[float, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Evaluates photo duplication against previous projects of the same singer.
    Uses SHA-256 for exact match and dHash (difference hash) for near-duplicate match.
    
    Rules:
      - 1 duplicate is treated as normal core news photo exception (0 pt penalty).
      - >= 50% overlap: -10.0 pts deduction + WARNING.
      - 20~49% overlap: -4.0 pts deduction + WARNING.
      - Max score: 12.0 pts.
    """
    if not current_images:
        return MAX_PHOTO_SCORE, [], {
            "current_count": 0,
            "duplicate_count": 0,
            "overlap_percentage": 0.0,
            "duplicate_files": [],
            "near_duplicate_pairs": [],
            "core_exception_applied": False,
            "deduction": 0.0
        }

    # Collect past photo hashes and normalized paths
    past_photo_hashes: Set[str] = set()
    past_photo_paths: Set[str] = set()
    past_photo_basenames: Set[str] = set()

    for proj in recent_projects:
        for media in proj.get("media", []):
            fpath = media.get("file_path", "")
            fhash = media.get("file_hash", "")
            role = str(media.get("role", "")).lower()
            subtype = str(media.get("subtype", "")).lower()
            
            # Treat as photo if tagged as photo/thumbnail or image file extension
            is_photo = (
                "photo" in role or "thumbnail" in role or
                "photo" in subtype or
                any(fpath.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))
            )
            if is_photo:
                if fhash:
                    past_photo_hashes.add(fhash.lower())
                if fpath:
                    past_photo_paths.add(os.path.normcase(os.path.abspath(fpath)))
                    past_photo_basenames.add(os.path.basename(fpath).lower())

    # 1. Exact match check via SHA-256 and path
    duplicate_files: List[str] = []
    seen_current_hashes: Set[str] = set()
    exact_duplicates: Set[str] = set()

    for img in current_images:
        img_norm = os.path.normcase(os.path.abspath(img))
        img_base = os.path.basename(img).lower()
        img_hash = compute_file_hash_safe(img).lower()

        is_dup = (
            img_hash in past_photo_hashes or
            img_norm in past_photo_paths or
            (img_base in past_photo_basenames and img_hash in seen_current_hashes)
        )
        seen_current_hashes.add(img_hash)

        if is_dup:
            duplicate_files.append(img)
            exact_duplicates.add(img_norm)

    # 2. Near-duplicate check with dHash for existing image files
    near_duplicate_pairs: List[Dict[str, Any]] = []
    existing_current = [img for img in current_images if os.path.isfile(img)]
    existing_past = [p for p in past_photo_paths if os.path.isfile(p)]

    if existing_current:
        photos_to_check = list(dict.fromkeys(existing_current + existing_past))
        near_pairs = find_near_duplicate_photos(photos_to_check, threshold=threshold, db_path=db_path)

        current_norm_map = {os.path.normcase(os.path.abspath(img)): img for img in current_images}
        past_norm_set = set(past_photo_paths)

        for p1, p2, dist in near_pairs:
            p1_norm = os.path.normcase(os.path.abspath(p1))
            p2_norm = os.path.normcase(os.path.abspath(p2))

            # Case A: p1 is current image, p2 is past photo
            if p1_norm in current_norm_map and p2_norm in past_norm_set:
                curr_img = current_norm_map[p1_norm]
                if p1_norm not in exact_duplicates and curr_img not in duplicate_files:
                    duplicate_files.append(curr_img)
                near_duplicate_pairs.append({
                    "current_file": curr_img,
                    "matched_file": p2,
                    "distance": dist,
                    "reason": f"이전 프로젝트 사진과 dHash 유사 (해밍거리: {dist} <= {threshold})"
                })
            # Case B: p2 is current image, p1 is past photo
            elif p2_norm in current_norm_map and p1_norm in past_norm_set:
                curr_img = current_norm_map[p2_norm]
                if p2_norm not in exact_duplicates and curr_img not in duplicate_files:
                    duplicate_files.append(curr_img)
                near_duplicate_pairs.append({
                    "current_file": curr_img,
                    "matched_file": p1,
                    "distance": dist,
                    "reason": f"이전 프로젝트 사진과 dHash 유사 (해밍거리: {dist} <= {threshold})"
                })
            # Case C: both are in current_images (internal near-duplicate within current batch)
            elif p1_norm in current_norm_map and p2_norm in current_norm_map:
                curr_img2 = current_norm_map[p2_norm]
                if p2_norm not in exact_duplicates and curr_img2 not in duplicate_files:
                    duplicate_files.append(curr_img2)
                near_duplicate_pairs.append({
                    "current_file": curr_img2,
                    "matched_file": p1,
                    "distance": dist,
                    "reason": f"현재 프로젝트 내 사진 유사 중복 (해밍거리: {dist} <= {threshold})"
                })

    duplicate_count = len(duplicate_files)
    total_current = len(current_images)
    overlap_ratio = duplicate_count / total_current if total_current > 0 else 0.0
    overlap_percentage = round(overlap_ratio * 100.0, 1)

    issues: List[Dict[str, Any]] = []
    deduction = 0.0
    core_exception_applied = False

    # Core article photo exception: 1 overlap is considered normal and not penalized
    if duplicate_count == 1:
        core_exception_applied = True
        deduction = 0.0
        logger.info(f"Core photo exception applied for 1 duplicate: {duplicate_files[0]}")
    elif duplicate_count >= 2:
        if overlap_percentage >= 50.0:
            deduction = 10.0
            issues.append({
                "issue_type": "photo_repetition",
                "severity": "medium",
                "scene_index": None,
                "start_time": None,
                "end_time": None,
                "evidence": f"최근 제작 영상과 사진 {duplicate_count}장 중복 ({overlap_percentage:.1f}%, 중복 파일: {duplicate_files[:3]})",
                "repairable": True,
                "repair_action": "replace_photo",
                "type": "warning",
                "component": "repetition",
                "message": f"최근 제작 영상과 사진 {duplicate_count}장 중복 ({overlap_percentage:.1f}%)"
            })
        elif overlap_percentage >= 20.0:
            deduction = 4.0
            issues.append({
                "issue_type": "photo_repetition",
                "severity": "medium",
                "scene_index": None,
                "start_time": None,
                "end_time": None,
                "evidence": f"최근 제작 영상과 사진 {duplicate_count}장 중복 ({overlap_percentage:.1f}%, 중복 파일: {duplicate_files[:3]})",
                "repairable": True,
                "repair_action": "replace_photo",
                "type": "warning",
                "component": "repetition",
                "message": f"최근 제작 영상과 사진 {duplicate_count}장 중복 ({overlap_percentage:.1f}%)"
            })

    photo_score = max(0.0, round(MAX_PHOTO_SCORE - deduction, 1))

    details = {
        "current_count": total_current,
        "duplicate_count": duplicate_count,
        "overlap_percentage": overlap_percentage,
        "duplicate_files": duplicate_files,
        "near_duplicate_pairs": near_duplicate_pairs,
        "core_exception_applied": core_exception_applied,
        "deduction": deduction
    }
    return photo_score, issues, details


def check_broll_reuse(
    current_brolls: Optional[List[str]],
    recent_projects: List[Dict[str, Any]]
) -> Tuple[float, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Evaluates B-roll reuse across recent projects.
    Checks consecutive usage of the exact same clip.
    
    Rules:
      - 3+ consecutive uses in recent projects: -5.0 pts deduction + WARNING.
      - 2 consecutive uses: -3.0 pts deduction + WARNING.
      - 1 consecutive use (immediate prior project): -1.0 pt deduction + WARNING.
      - Maximum deduction capped at 5.0 pts.
      - Max score: 7.0 pts.
    """
    if not current_brolls:
        return MAX_BROLL_SCORE, [], {
            "current_count": 0,
            "consecutive_reuses": [],
            "max_consecutive": 0,
            "deduction": 0.0
        }

    # Pre-parse recent projects' B-rolls in chronological order (newest first)
    project_brolls: List[List[Dict[str, str]]] = []
    for proj in recent_projects:
        clips = []
        for media in proj.get("media", []):
            fpath = media.get("file_path", "")
            fhash = media.get("file_hash", "")
            role = str(media.get("role", "")).lower()
            subtype = str(media.get("subtype", "")).lower()
            
            # Treat as B-roll if role/subtype contains broll or stock, or video not stage clip
            is_broll = (
                "broll" in role or "stock" in role or
                "broll" in subtype or "stock" in subtype or
                (media.get("file_path", "").lower().endswith((".mp4", ".mov", ".webm")) and "clip" not in subtype)
            )
            if is_broll or any(fpath.lower().endswith(ext) for ext in (".mp4", ".mov", ".webm")):
                clips.append({
                    "path": os.path.normcase(os.path.abspath(fpath)),
                    "basename": os.path.basename(fpath).lower(),
                    "hash": fhash.lower() if fhash else ""
                })
        project_brolls.append(clips)

    issues: List[Dict[str, Any]] = []
    consecutive_reuses: List[Dict[str, Any]] = []
    max_consecutive_all = 0
    total_deduction = 0.0

    for broll_path in current_brolls:
        b_norm = os.path.normcase(os.path.abspath(broll_path))
        b_base = os.path.basename(broll_path).lower()
        b_hash = compute_file_hash_safe(broll_path).lower()

        # Check consecutive presence starting from project 0 (immediately previous project)
        consecutive_count = 0
        for proj_clips in project_brolls:
            matched = any(
                (b_hash and c["hash"] == b_hash) or
                c["path"] == b_norm or
                c["basename"] == b_base
                for c in proj_clips
            )
            if matched:
                consecutive_count += 1
            else:
                break  # Chain breaks

        if consecutive_count > 0:
            consecutive_reuses.append({
                "clip": os.path.basename(broll_path),
                "consecutive_count": consecutive_count
            })
            if consecutive_count > max_consecutive_all:
                max_consecutive_all = consecutive_count

            clip_name = os.path.basename(broll_path)
            if consecutive_count >= 3:
                clip_deduction = 5.0
                issues.append({
                    "issue_type": "broll_repetition",
                    "severity": "medium",
                    "scene_index": None,
                    "start_time": None,
                    "end_time": None,
                    "evidence": f"B-roll 클립 '{clip_name}'이(가) 최근 {consecutive_count}회 연속 재사용됨",
                    "repairable": True,
                    "repair_action": "replace_broll",
                    "type": "warning",
                    "component": "repetition",
                    "message": f"B-roll 클립 '{clip_name}'이(가) 최근 {consecutive_count}회 연속 재사용됨 (다양성 확보 필요)"
                })
            elif consecutive_count == 2:
                clip_deduction = 3.0
                issues.append({
                    "issue_type": "broll_repetition",
                    "severity": "medium",
                    "scene_index": None,
                    "start_time": None,
                    "end_time": None,
                    "evidence": f"B-roll 클립 '{clip_name}'이(가) 최근 2회 연속 재사용됨",
                    "repairable": True,
                    "repair_action": "replace_broll",
                    "type": "warning",
                    "component": "repetition",
                    "message": f"B-roll 클립 '{clip_name}'이(가) 최근 2회 연속 재사용됨"
                })
            else:
                clip_deduction = 1.0
                issues.append({
                    "issue_type": "broll_repetition",
                    "severity": "low",
                    "scene_index": None,
                    "start_time": None,
                    "end_time": None,
                    "evidence": f"B-roll 클립 '{clip_name}'이(가) 직전 영상에서 재사용됨",
                    "repairable": True,
                    "repair_action": "replace_broll",
                    "type": "warning",
                    "component": "repetition",
                    "message": f"B-roll 클립 '{clip_name}'이(가) 직전 영상에서 재사용됨"
                })

            total_deduction = max(total_deduction, clip_deduction)

    # Cap deduction at 5.0 pts max
    final_deduction = min(5.0, total_deduction)
    broll_score = max(0.0, round(MAX_BROLL_SCORE - final_deduction, 1))

    details = {
        "current_count": len(current_brolls),
        "consecutive_reuses": consecutive_reuses,
        "max_consecutive": max_consecutive_all,
        "deduction": final_deduction
    }
    return broll_score, issues, details


def check_hook_similarity(
    target_hook: Optional[str],
    past_hooks: List[str]
) -> Tuple[float, List[Dict[str, Any]], Dict[str, Any]]:
    """
    Evaluates word-level Jaccard similarity between target hook and past hooks/scripts.
    
    Rules:
      - Similarity > 0.70: deduct up to 5.0 pts + WARNING.
      - Max score: 6.0 pts.
    """
    if not target_hook or not past_hooks:
        return MAX_HOOK_SCORE, [], {
            "target_hook": target_hook,
            "max_similarity": 0.0,
            "most_similar_past_hook": None,
            "deduction": 0.0
        }

    max_sim = 0.0
    most_similar_hook = None

    for past in past_hooks:
        sim = calculate_jaccard_similarity(target_hook, past)
        if sim > max_sim:
            max_sim = sim
            most_similar_hook = past

    max_sim = round(max_sim, 3)
    issues: List[Dict[str, Any]] = []
    deduction = 0.0

    if max_sim >= 0.85:
        deduction = 5.0
        issues.append({
            "issue_type": "hook_repetition",
            "severity": "medium",
            "scene_index": 0,
            "start_time": 0.0,
            "end_time": 5.0,
            "evidence": f"Hook 문장 유사도 {max_sim * 100:.1f}% (과거 훅: '{most_similar_hook}')",
            "repairable": True,
            "repair_action": "rephrase_script",
            "type": "warning",
            "component": "repetition",
            "message": f"Hook 문장이 이전 콘텐츠와 매우 유사 (유사도 {max_sim * 100:.1f}%, 기준: 70% 초과)"
        })
    elif max_sim > 0.70:
        deduction = 4.0
        issues.append({
            "issue_type": "hook_repetition",
            "severity": "medium",
            "scene_index": 0,
            "start_time": 0.0,
            "end_time": 5.0,
            "evidence": f"Hook 문장 유사도 {max_sim * 100:.1f}% (과거 훅: '{most_similar_hook}')",
            "repairable": True,
            "repair_action": "rephrase_script",
            "type": "warning",
            "component": "repetition",
            "message": f"Hook 문장이 최근 제작 영상과 유사 (유사도 {max_sim * 100:.1f}%, 기준: 70% 초과)"
        })
    elif max_sim >= 0.50:
        deduction = 1.5
        issues.append({
            "issue_type": "hook_repetition",
            "severity": "low",
            "scene_index": 0,
            "start_time": 0.0,
            "end_time": 5.0,
            "evidence": f"Hook 문장 어휘 일부 중복 (유사도 {max_sim * 100:.1f}%)",
            "repairable": True,
            "repair_action": "rephrase_script",
            "type": "warning",
            "component": "repetition",
            "message": f"Hook 문장 어휘 일부 중복 (유사도 {max_sim * 100:.1f}%)"
        })

    hook_score = max(0.0, round(MAX_HOOK_SCORE - deduction, 1))

    details = {
        "target_hook": target_hook,
        "max_similarity": max_sim,
        "most_similar_past_hook": most_similar_hook,
        "deduction": deduction
    }
    return hook_score, issues, details


def validate_repetition(
    singer_name: str,
    current_images: List[str],
    current_brolls: Optional[List[str]] = None,
    current_script: Optional[str] = None,
    current_hook: Optional[str] = None,
    db_path: Optional[str] = None,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Main validator entrypoint for QA-3 Repetition and Freshness control.
    Performs strictly read-only inspection against media_library.db without modifying records.

    Parameters:
      singer_name: Target singer's name (e.g. '임영웅', '송가인')
      current_images: List of image file paths planned for the current project
      current_brolls: Optional list of B-roll file paths
      current_script: Optional text of the candidate script
      current_hook: Optional hook sentence
      db_path: Optional custom SQLite database path
      **kwargs:
        - past_hooks: Optional explicit list of past hook texts
        - past_scripts: Optional explicit list of past script texts
        - recent_projects: Optional pre-loaded list of recent projects (for testing)

    Returns structured dict:
      {
          "score": float,            # 0.0 ~ 25.0
          "max_score": 25.0,
          "passed": bool,
          "critical_error": bool,
          "issues": [
              {"type": "error" | "warning", "component": "repetition", "message": str}
          ],
          "details": {
              "photo_diversity_score": float,
              "broll_freshness_score": float,
              "hook_freshness_score": float,
              "total_recent_projects_checked": int,
              "photo_stats": dict,
              "broll_stats": dict,
              "hook_stats": dict,
              "message": str
          }
      }
    """
    clean_singer = (singer_name or "").strip()
    if not clean_singer:
        return {
            "score": TOTAL_MAX_SCORE,
            "max_score": TOTAL_MAX_SCORE,
            "passed": True,
            "critical_error": False,
            "issues": [],
            "details": {
                "photo_diversity_score": MAX_PHOTO_SCORE,
                "broll_freshness_score": MAX_BROLL_SCORE,
                "hook_freshness_score": MAX_HOOK_SCORE,
                "total_recent_projects_checked": 0,
                "message": "가수명이 지정되지 않아 반복성 검사 통과 (기본 점수 부여)"
            }
        }

    # 1. Fetch recent projects from DB (or kwargs for unit testing)
    recent_projects = kwargs.get("recent_projects")
    if recent_projects is None:
        recent_projects = get_recent_singer_projects(clean_singer, limit=5, db_path=db_path)

    # 2. Rule: If no prior projects exist in DB for this singer, grant full 25.0 points!
    if not recent_projects:
        logger.info(f"No prior projects found for singer '{clean_singer}'. Granting full 25.0 pts (100% fresh).")
        return {
            "score": TOTAL_MAX_SCORE,
            "max_score": TOTAL_MAX_SCORE,
            "passed": True,
            "critical_error": False,
            "issues": [],
            "details": {
                "photo_diversity_score": MAX_PHOTO_SCORE,
                "broll_freshness_score": MAX_BROLL_SCORE,
                "hook_freshness_score": MAX_HOOK_SCORE,
                "total_recent_projects_checked": 0,
                "photo_stats": {
                    "current_count": len(current_images or []),
                    "duplicate_count": 0,
                    "overlap_percentage": 0.0,
                    "duplicate_files": [],
                    "core_exception_applied": False,
                    "deduction": 0.0
                },
                "broll_stats": {
                    "current_count": len(current_brolls or []),
                    "consecutive_reuses": [],
                    "max_consecutive": 0,
                    "deduction": 0.0
                },
                "hook_stats": {
                    "current_hook": extract_hook_sentence(current_hook, current_script),
                    "max_similarity": 0.0,
                    "most_similar_past_hook": None,
                    "deduction": 0.0
                },
                "message": f"가수 '{clean_singer}'의 이전 제작 프로젝트 이력이 없어 100% 신규 제작으로 판정 (만점 부여)"
            }
        }

    # 3. Check Photo Duplication (12.0 pts max)
    photo_score, photo_issues, photo_details = check_photo_duplication(
        current_images=current_images or [],
        recent_projects=recent_projects,
        threshold=kwargs.get("photo_threshold", 5),
        db_path=db_path
    )

    # 4. Check B-roll Reuse (7.0 pts max)
    broll_score, broll_issues, broll_details = check_broll_reuse(
        current_brolls=current_brolls or [],
        recent_projects=recent_projects
    )

    # 5. Check Hook / Script Freshness (6.0 pts max)
    target_hook = extract_hook_sentence(current_hook, current_script)
    past_hooks: List[str] = list(kwargs.get("past_hooks") or [])
    if not past_hooks:
        past_hooks = get_past_hooks_from_db(clean_singer, limit=5, db_path=db_path)
    
    # Also check past scripts passed in kwargs
    if kwargs.get("past_scripts"):
        for ps in kwargs["past_scripts"]:
            hook_cand = extract_hook_sentence(None, ps)
            if hook_cand:
                past_hooks.append(hook_cand)

    hook_score, hook_issues, hook_details = check_hook_similarity(
        target_hook=target_hook,
        past_hooks=past_hooks
    )

    # 6. Aggregate Total Score & Status
    total_score = round(photo_score + broll_score + hook_score, 1)
    all_issues = photo_issues + broll_issues + hook_issues

    # Passing threshold: 70% of 25.0 (17.5 pts)
    passed = total_score >= 17.5
    # Critical error flag: triggered if score is severely low (< 10.0 pts)
    critical_error = total_score < 10.0

    return {
        "score": total_score,
        "max_score": TOTAL_MAX_SCORE,
        "passed": passed,
        "critical_error": critical_error,
        "issues": all_issues,
        "details": {
            "photo_diversity_score": photo_score,
            "photo_max_score": MAX_PHOTO_SCORE,
            "broll_freshness_score": broll_score,
            "broll_max_score": MAX_BROLL_SCORE,
            "hook_freshness_score": hook_score,
            "hook_max_score": MAX_HOOK_SCORE,
            "total_recent_projects_checked": len(recent_projects),
            "photo_stats": photo_details,
            "broll_stats": broll_details,
            "hook_stats": hook_details,
            "message": f"최근 {len(recent_projects)}개 프로젝트 대비 신선도 검사 완료"
        }
    }


if __name__ == "__main__":
    print("=== QA-3 Repetition Validator Self Test ===")
    sample_res = validate_repetition(
        singer_name="신규가수_테스트",
        current_images=["/dummy/photo1.jpg", "/dummy/photo2.jpg"]
    )
    print(json.dumps(sample_res, ensure_ascii=False, indent=2))
