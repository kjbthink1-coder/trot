"""
engine/image_enricher.py - Re-export crawler.image_enricher functions for engine module compatibility
"""
from crawler.image_enricher import (
    is_valid_photo,
    fetch_singer_photos,
    save_curated_photos,
    _crawl_external_singer_photos
)

__all__ = [
    "is_valid_photo",
    "fetch_singer_photos",
    "save_curated_photos",
    "_crawl_external_singer_photos"
]
