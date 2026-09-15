"""
engine.qa package
=================
Quality assurance modules for automated YouTube Shorts and blog content review.
"""

from engine.qa.technical_validator import (
    validate_technical_quality,
)
from engine.qa.factual_validator import (
    validate_factual_consistency,
    validate_shorts_length,
    validate_blog_length,
    SHORTS_MIN_CHARS,
    SHORTS_MAX_CHARS,
    BLOG_TARGET_CHARS,
    BLOG_MIN_CHARS,
    BLOG_MAX_CHARS,
)
from engine.qa.frame_extractor import (
    extract_representative_frames,
    cleanup_frames,
    get_video_duration,
    get_ffmpeg_exe
)
from engine.qa.ai_reviewer import (
    review_with_ai,
    get_gemini_api_key,
    FALLBACK_RESULT
)
from engine.qa.repetition_validator import (
    validate_repetition,
    calculate_jaccard_similarity,
    extract_hook_sentence,
)
from engine.qa.qa_aggregator import (
    run_full_qa,
)

__all__ = [
    "validate_technical_quality",
    "validate_factual_consistency",
    "validate_shorts_length",
    "validate_blog_length",
    "SHORTS_MIN_CHARS",
    "SHORTS_MAX_CHARS",
    "BLOG_TARGET_CHARS",
    "BLOG_MIN_CHARS",
    "BLOG_MAX_CHARS",
    "extract_representative_frames",
    "cleanup_frames",
    "get_video_duration",
    "get_ffmpeg_exe",
    "review_with_ai",
    "get_gemini_api_key",
    "FALLBACK_RESULT",
    "validate_repetition",
    "calculate_jaccard_similarity",
    "extract_hook_sentence",
    "run_full_qa",
]
