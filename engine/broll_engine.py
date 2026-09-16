"""
engine/broll_engine.py - B-roll Footage Search, Ingestion & Normalization Engine
==============================================================================
Accumulative B-roll Manager for Trot/Celebrity Shorts Automation.
Implements the strict hierarchical retrieval pipeline:
  1. Local Media DB query (instant, 0 network, offline-first)
  2. Local API Cache check (SQLite api_cache table)
  3. External API search (Pexels / Pixabay portrait video search)
  4. Selective download of exactly ONE required clip
  5. FFmpeg normalization (1080x1920 9:16 portrait, 30fps, muted audio -an)
  6. SQLite DB registration (subtype='general_broll', auto-tagged)
  7. Seamless fallback to existing stock reaction videos on network/API failure
"""

import os
import re
import glob
import time
import json
import shutil
import hashlib
import logging
import urllib.parse
import subprocess
from typing import Optional, List, Dict, Any, Tuple

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Shared requests session configured for environment resilience
http_session = requests.Session()
http_session.verify = False

from engine import media_db

logger = logging.getLogger("broll_engine")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_BROLL_DIR = os.path.join(PROJECT_ROOT, "assets", "general_broll")
DEFAULT_STOCK_DIR = os.path.join(PROJECT_ROOT, "assets", "stock_videos")

# Standard core categories supported by system
SUPPORTED_CATEGORIES = [
    "audience",
    "emotion",
    "hospital",
    "money",
    "smartphone",
    "concert",
    "business"
]

# Query expansion mapping for high quality portrait video search
CATEGORY_QUERY_MAP = {
    "audience": "cheering audience concert crowd fans",
    "emotion": "crying emotional tears touching moment",
    "hospital": "hospital doctor medical healthcare room",
    "money": "counting money cash finance currency",
    "smartphone": "smartphone screen browsing mobile typing",
    "concert": "concert music stage performance spotlight",
    "business": "business meeting discussion handshake office",
}

# Korean keywords to canonical category mapping
KOREAN_CATEGORY_MAP = {
    "관객": "audience",
    "팬": "audience",
    "환호": "audience",
    "응원": "audience",
    "감동": "emotion",
    "눈물": "emotion",
    "슬픔": "emotion",
    "기쁨": "emotion",
    "병원": "hospital",
    "의사": "hospital",
    "치료": "hospital",
    "수술": "hospital",
    "돈": "money",
    "현금": "money",
    "재산": "money",
    "수익": "money",
    "스마트폰": "smartphone",
    "핸드폰": "smartphone",
    "휴대폰": "smartphone",
    "전화": "smartphone",
    "콘서트": "concert",
    "공연": "concert",
    "무대": "concert",
    "노래": "concert",
    "비즈니스": "business",
    "사업": "business",
    "계약": "business",
    "회사": "business",
}

# Rate limit tracking (timestamp of last request per provider)
_LAST_REQUEST_TIME: Dict[str, float] = {
    "pexels": 0.0,
    "pixabay": 0.0,
}
# Minimum interval in seconds between external requests
_MIN_REQUEST_INTERVAL = 1.0


def ensure_broll_directories(base_dir: Optional[str] = None) -> str:
    """
    Ensures assets/general_broll/ and all standard category subdirectories exist.
    """
    target_dir = os.path.abspath(base_dir or DEFAULT_BROLL_DIR)
    os.makedirs(target_dir, exist_ok=True)
    for cat in SUPPORTED_CATEGORIES:
        os.makedirs(os.path.join(target_dir, cat), exist_ok=True)
    return target_dir


def load_env_keys() -> Dict[str, str]:
    """
    Loads API keys from os.environ, falling back to reading .env file at project root.
    """
    keys = {
        "PEXELS_API_KEY": os.getenv("PEXELS_API_KEY", "").strip(),
        "PIXABAY_API_KEY": os.getenv("PIXABAY_API_KEY", "").strip()
    }
    
    env_file = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k in keys and not keys[k]:
                            keys[k] = v
        except Exception as e:
            logger.debug(f"Failed to read .env file: {e}")

    return keys


def get_ffmpeg_exe() -> str:
    """
    Locates FFmpeg executable via imageio_ffmpeg or system PATH.
    """
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    return "ffmpeg"


def get_fallback_stock_video() -> str:
    """
    Returns an existing fallback stock video clip from assets/stock_videos/.
    If none exists, attempts automatic generation via generate_stock_clips.
    """
    os.makedirs(DEFAULT_STOCK_DIR, exist_ok=True)
    default_stock = os.path.join(DEFAULT_STOCK_DIR, "stock_reaction_1.mp4")

    if os.path.isfile(default_stock) and os.path.getsize(default_stock) > 1000:
        return default_stock

    # Check any other MP4 in stock_videos
    for f in glob.glob(os.path.join(DEFAULT_STOCK_DIR, "*.mp4")):
        if os.path.getsize(f) > 1000:
            return os.path.abspath(f)

    # Attempt on-the-fly generation using existing helper
    try:
        from assets.generate_stock_clips import ensure_stock_video
        generated = ensure_stock_video()
        if generated and os.path.isfile(generated):
            return os.path.abspath(generated)
    except Exception as e:
        logger.warning(f"Could not generate stock video on the fly: {e}")

    return default_stock


def normalize_category_name(category: str) -> str:
    """
    Normalizes Korean or English category inputs into standard canonical categories.
    """
    cat_clean = category.strip().lower()
    # Check Korean dictionary
    if cat_clean in KOREAN_CATEGORY_MAP:
        return KOREAN_CATEGORY_MAP[cat_clean]
    
    # Check partial match in Korean dictionary
    for k, v in KOREAN_CATEGORY_MAP.items():
        if k in cat_clean:
            return v

    # Alphanumeric fallback
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", cat_clean)
    return cleaned if cleaned else "audience"


def normalize_video_clip(
    input_path: str,
    output_path: str,
    target_duration: float = 3.5
) -> bool:
    """
    Normalizes a video clip using FFmpeg:
      - 1080x1920 (9:16 vertical shorts format)
      - Exact 30 fps (-r 30)
      - Audio completely muted (-an)
      - Duration limited to target_duration (-t)
      - High compatibility H.264 & YUV420p
    """
    ffmpeg_exe = get_ffmpeg_exe()
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Video filter: Scale to fill 1080x1920 while preserving aspect ratio, then crop center
    # force_original_aspect_ratio=increase ensures no empty black borders
    vf_chain = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "format=yuv420p,setsar=1"
    )

    cmd = [
        ffmpeg_exe, "-y",
        "-ss", "0",
        "-i", os.path.abspath(input_path),
        "-t", str(max(1.0, float(target_duration))),
        "-vf", vf_chain,
        "-r", "30",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-video_track_timescale", "30000",
        "-an",  # Strip audio for zero copyright issues & zero TTS collision
        os.path.abspath(output_path)
    ]

    try:
        res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 1000:
            return True
        logger.error(f"FFmpeg normalization created zero/tiny file: {res.stderr[-300:]}")
        return False
    except Exception as e:
        logger.error(f"FFmpeg normalization failed for {input_path} -> {output_path}: {e}")
        return False


def _enforce_rate_limit(provider: str):
    """Enforces a gentle sleep between API calls to honor rate limits."""
    global _LAST_REQUEST_TIME
    last_time = _LAST_REQUEST_TIME.get(provider, 0.0)
    elapsed = time.time() - last_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _LAST_REQUEST_TIME[provider] = time.time()


def search_pexels_videos(query: str, api_key: str, per_page: int = 5) -> Optional[Dict[str, Any]]:
    """
    Searches Pexels Video API for 9:16 portrait videos.
    Adheres strictly to official API schema and rate limits.
    """
    if not api_key:
        return None

    _enforce_rate_limit("pexels")
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&orientation=portrait&per_page={per_page}"
    headers = {
        "Authorization": api_key,
        "User-Agent": "TrotShortsAutomation/1.0"
    }

    try:
        resp = http_session.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 429:
            logger.warning("Pexels rate limit hit (HTTP 429).")
            return None
        else:
            logger.warning(f"Pexels API error {resp.status_code}: {resp.text[:150]}")
            return None
    except Exception as e:
        logger.warning(f"Pexels API request exception: {e}")
        return None


def search_pixabay_videos(query: str, api_key: str, per_page: int = 5) -> Optional[Dict[str, Any]]:
    """
    Searches Pixabay Video API as secondary provider.
    """
    if not api_key:
        return None

    _enforce_rate_limit("pixabay")
    url = f"https://pixabay.com/api/videos/?key={urllib.parse.quote(api_key)}&q={urllib.parse.quote(query)}&per_page={per_page}"

    try:
        resp = http_session.get(url, timeout=12)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 429:
            logger.warning("Pixabay rate limit hit (HTTP 429).")
            return None
        else:
            logger.warning(f"Pixabay API error {resp.status_code}: {resp.text[:150]}")
            return None
    except Exception as e:
        logger.warning(f"Pixabay API request exception: {e}")
        return None


def extract_best_video_candidate(
    provider: str,
    data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Parses API response and selects the single highest quality HD 9:16 video download candidate.
    Returns metadata dict: {download_url, provider, provider_media_id, source_url, author, license}
    """
    if not data:
        return None

    if provider == "pexels":
        videos = data.get("videos", [])
        if not videos:
            return None

        # Choose the best video candidate
        for video in videos:
            v_id = video.get("id")
            source_url = video.get("url", f"https://www.pexels.com/video/{v_id}/")
            author = video.get("user", {}).get("name", "Pexels Creator")
            video_files = video.get("video_files", [])

            # Filter for mp4
            mp4_files = [f for f in video_files if "mp4" in f.get("file_type", "").lower() or ".mp4" in f.get("link", "").lower()]
            if not mp4_files:
                mp4_files = video_files

            # Prioritize portrait 9:16 HD files (height >= width)
            portrait_files = [f for f in mp4_files if f.get("height", 0) >= f.get("width", 0)]
            pool = portrait_files if portrait_files else mp4_files

            if not pool:
                continue

            # Sort by resolution (prefer 1080, then 720)
            def score_file(f):
                h = f.get("height", 0)
                w = f.get("width", 0)
                # Perfect score for ~1080x1920
                if h == 1920 and w == 1080:
                    return 1000
                if h >= 1080:
                    return 500
                if h >= 720:
                    return 300
                return h

            pool.sort(key=score_file, reverse=True)
            chosen = pool[0]
            download_url = chosen.get("link")

            if download_url:
                return {
                    "download_url": download_url,
                    "provider": "pexels",
                    "provider_media_id": str(v_id),
                    "source_url": source_url,
                    "author": author,
                    "license": "Pexels License"
                }

    elif provider == "pixabay":
        hits = data.get("hits", [])
        if not hits:
            return None

        for hit in hits:
            h_id = hit.get("id")
            source_url = hit.get("pageURL", f"https://pixabay.com/videos/id-{h_id}/")
            author = hit.get("user", "Pixabay Creator")
            vids = hit.get("videos", {})

            # Try large, then medium, then small
            for size_key in ("large", "medium", "small"):
                v_obj = vids.get(size_key)
                if v_obj and v_obj.get("url"):
                    return {
                        "download_url": v_obj.get("url"),
                        "provider": "pixabay",
                        "provider_media_id": str(h_id),
                        "source_url": source_url,
                        "author": author,
                        "license": "Pixabay Content License"
                    }

    return None


def download_single_clip(
    download_url: str,
    temp_target_path: str,
    timeout: int = 30
) -> bool:
    """
    Downloads only the specific required video clip using chunked streaming.
    Ensures that temporary un-normalized files do not pollute the asset library.
    """
    os.makedirs(os.path.dirname(os.path.abspath(temp_target_path)), exist_ok=True)
    try:
        with http_session.get(download_url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            with open(temp_target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        return os.path.isfile(temp_target_path) and os.path.getsize(temp_target_path) > 1000
    except Exception as e:
        logger.error(f"Download failed for {download_url}: {e}")
        if os.path.exists(temp_target_path):
            try:
                os.remove(temp_target_path)
            except Exception:
                pass
        return False


def get_or_fetch_broll(
    category: str,
    tag: Optional[str] = None,
    target_duration: float = 3.5,
    db_path: Optional[str] = None,
    allow_stock_fallback: bool = False
) -> Optional[str]:
    """
    Core B-roll retrieval function implementing the strict 6-stage hierarchy:
      Step 1: Check Media DB for existing local B-roll by tags. Return existing clip path!
      Step 2: Check SQLite api_cache for previous query responses.
      Step 3: Query Pexels API (or Pixabay API) if not cached.
      Step 4: Pick the single best HD 9:16 portrait video URL and download ONLY this clip.
      Step 5: Normalize clip using FFmpeg (1080x1920, 30fps, -an muted, target_duration).
      Step 6: Register in media_db (subtype='general_broll') for instant future reuse.
      Fallback: Seamlessly return stock reaction clip if API keys are missing or network fails.
    """
    ensure_broll_directories()
    norm_cat = normalize_category_name(category)
    norm_tag = tag.strip().lower() if tag else None

    # -------------------------------------------------------------
    # Step 1: Check Local DB first (0 network calls, offline-first)
    # -------------------------------------------------------------
    query_tags = [norm_cat]
    if norm_tag:
        query_tags.append(norm_tag)

    local_clips = media_db.query_brolls(tags=query_tags, limit=5, db_path=db_path)
    for row in local_clips:
        fpath = row.get("file_path")
        if fpath and os.path.isfile(fpath):
            logger.info(f"[B-roll Engine] Reusing local clip from DB for '{category}': {fpath}")
            return fpath

    # If tag was specified but yielded no matches, also check category alone
    if norm_tag:
        cat_local_clips = media_db.query_brolls(tags=[norm_cat], limit=5, db_path=db_path)
        for row in cat_local_clips:
            fpath = row.get("file_path")
            if fpath and os.path.isfile(fpath):
                logger.info(f"[B-roll Engine] Reusing local category clip from DB for '{norm_cat}': {fpath}")
                return fpath

    # -------------------------------------------------------------
    # Step 2: Check SQLite API Cache
    # -------------------------------------------------------------
    # Build search query
    base_terms = CATEGORY_QUERY_MAP.get(norm_cat, norm_cat)
    if norm_tag and norm_tag not in base_terms:
        search_query = f"{norm_cat} {norm_tag}"
    else:
        search_query = base_terms

    candidate = None
    cached_data = media_db.get_api_cache("pexels", search_query, media_type="video", db_path=db_path)
    if cached_data:
        logger.info(f"[B-roll Engine] API Cache HIT for Pexels query: '{search_query}'")
        candidate = extract_best_video_candidate("pexels", cached_data)

    if not candidate:
        cached_pixabay = media_db.get_api_cache("pixabay", search_query, media_type="video", db_path=db_path)
        if cached_pixabay:
            logger.info(f"[B-roll Engine] API Cache HIT for Pixabay query: '{search_query}'")
            candidate = extract_best_video_candidate("pixabay", cached_pixabay)

    # -------------------------------------------------------------
    # Step 3: Query Pexels API / Pixabay API if not in cache
    # -------------------------------------------------------------
    keys = load_env_keys()
    pexels_key = keys.get("PEXELS_API_KEY", "")
    pixabay_key = keys.get("PIXABAY_API_KEY", "")

    if not candidate and pexels_key:
        logger.info(f"[B-roll Engine] Querying Pexels API for '{search_query}'...")
        api_res = search_pexels_videos(search_query, pexels_key, per_page=5)
        if api_res and api_res.get("videos"):
            # Store in cache (30-day TTL)
            media_db.set_api_cache("pexels", search_query, api_res, media_type="video", ttl_days=30, db_path=db_path)
            candidate = extract_best_video_candidate("pexels", api_res)

    if not candidate and pixabay_key:
        logger.info(f"[B-roll Engine] Querying Pixabay API for '{search_query}'...")
        api_res = search_pixabay_videos(search_query, pixabay_key, per_page=5)
        if api_res and api_res.get("hits"):
            media_db.set_api_cache("pixabay", search_query, api_res, media_type="video", ttl_days=30, db_path=db_path)
            candidate = extract_best_video_candidate("pixabay", api_res)

    # -------------------------------------------------------------
    # Step 4, 5, 6: Download, Normalize & Register if candidate exists
    # -------------------------------------------------------------
    if candidate and candidate.get("download_url"):
        try:
            download_url = candidate["download_url"]
            provider = candidate["provider"]
            prov_id = candidate["provider_media_id"]

            # Unique deterministic filename based on provider & id
            url_hash = hashlib.sha256(f"{provider}_{prov_id}_{download_url}".encode("utf-8")).hexdigest()
            short_hash = url_hash[:8]

            cat_dir = os.path.join(DEFAULT_BROLL_DIR, norm_cat)
            os.makedirs(cat_dir, exist_ok=True)

            temp_raw_path = os.path.join(cat_dir, f"temp_raw_{short_hash}.mp4")
            final_clip_path = os.path.join(cat_dir, f"broll_{short_hash}.mp4")

            # Check if this exact final normalized file already exists on disk
            if os.path.isfile(final_clip_path) and os.path.getsize(final_clip_path) > 1000:
                logger.info(f"[B-roll Engine] Existing normalized file already exists: {final_clip_path}")
                # Ensure registered in DB
                media_db.register_media(
                    file_path=final_clip_path,
                    media_type="video",
                    subtype="general_broll",
                    source=provider,
                    source_url=candidate.get("source_url"),
                    provider_media_id=prov_id,
                    author=candidate.get("author"),
                    license=candidate.get("license"),
                    tags=[norm_cat] + ([norm_tag] if norm_tag else []),
                    db_path=db_path
                )
                return final_clip_path

            # Step 4: Download ONLY this one clip
            logger.info(f"[B-roll Engine] Downloading single clip ({provider} #{prov_id})...")
            dl_success = download_single_clip(download_url, temp_raw_path)
            if dl_success:
                # Step 5: Normalize clip (1080x1920, 30fps, -an muted)
                logger.info(f"[B-roll Engine] Normalizing clip to 9:16 1080x1920: {final_clip_path}")
                norm_ok = normalize_video_clip(temp_raw_path, final_clip_path, target_duration=target_duration)

                # Clean up temporary raw download file
                if os.path.exists(temp_raw_path):
                    try:
                        os.remove(temp_raw_path)
                    except Exception:
                        pass

                if norm_ok:
                    # Step 6: Register in media_db
                    tags_to_store = [norm_cat]
                    if norm_tag and norm_tag != norm_cat:
                        tags_to_store.append(norm_tag)
                    
                    media_db.register_media(
                        file_path=final_clip_path,
                        media_type="video",
                        subtype="general_broll",
                        source=provider,
                        source_url=candidate.get("source_url"),
                        provider_media_id=prov_id,
                        author=candidate.get("author"),
                        license=candidate.get("license"),
                        tags=tags_to_store,
                        description=f"B-roll footage: {category} ({tag or ''})",
                        db_path=db_path
                    )
                    logger.info(f"[B-roll Engine] Successfully ingested and registered: {final_clip_path}")
                    return final_clip_path

        except Exception as e:
            logger.error(f"[B-roll Engine] Error during clip download/normalization: {e}")

    # -------------------------------------------------------------
    # Fallback handling
    # -------------------------------------------------------------
    if allow_stock_fallback:
        logger.info(f"[B-roll Engine] API/Network unavailable for '{category}'. Falling back to stock reaction clip.")
        fallback_clip = get_fallback_stock_video()
        return fallback_clip if os.path.isfile(fallback_clip) else None
    
    logger.info(f"[B-roll Engine] No B-roll available for '{category}' and stock fallback is disabled. Returning None.")
    return None


def get_or_fetch_broll_multiple(
    category: str,
    tag: Optional[str] = None,
    count: int = 1,
    target_duration: float = 3.5,
    db_path: Optional[str] = None,
    allow_stock_fallback: bool = True
) -> List[str]:
    """
    Retrieves up to `count` non-duplicate B-roll video clip paths for the given category/tag.
    Combines DB queries, API search, and fallback stock clips to return exact requested count.
    """
    if count <= 0:
        return []
    
    ensure_broll_directories()
    norm_cat = normalize_category_name(category)
    norm_tag = tag.strip().lower() if tag else None

    query_tags = [norm_cat]
    if norm_tag:
        query_tags.append(norm_tag)

    results = []
    seen = set()

    # Step 1: Fetch all matching local clips from DB
    local_clips = media_db.query_brolls(tags=query_tags, limit=count * 3, db_path=db_path)
    for row in local_clips:
        fpath = row.get("file_path")
        if fpath and os.path.isfile(fpath) and fpath not in seen:
            results.append(fpath)
            seen.add(fpath)
            if len(results) >= count:
                return results[:count]

    # Check category alone if tag was provided
    if norm_tag and len(results) < count:
        cat_clips = media_db.query_brolls(tags=[norm_cat], limit=count * 3, db_path=db_path)
        for row in cat_clips:
            fpath = row.get("file_path")
            if fpath and os.path.isfile(fpath) and fpath not in seen:
                results.append(fpath)
                seen.add(fpath)
                if len(results) >= count:
                    return results[:count]

    # Step 2: Try fetching via single clip retriever
    if len(results) < count:
        single = get_or_fetch_broll(category=category, tag=tag, target_duration=target_duration, db_path=db_path, allow_stock_fallback=False)
        if single and os.path.isfile(single) and single not in seen:
            results.append(single)
            seen.add(single)

    # Step 3: Fallback stock clip if needed to reach count
    if len(results) < count and allow_stock_fallback:
        stock = get_fallback_stock_video()
        if stock and os.path.isfile(stock) and stock not in seen:
            results.append(stock)
            seen.add(stock)

    return results[:count]


def sync_broll_assets(db_path: Optional[str] = None) -> Dict[str, int]:
    """
    Scans assets/general_broll/ directory and registers all existing MP4 clips
    into media_library.db so any manually added or previously generated clips
    are immediately queryable.
    """
    ensure_broll_directories()
    indexed_count = 0

    for cat_dir_name in os.listdir(DEFAULT_BROLL_DIR):
        cat_path = os.path.join(DEFAULT_BROLL_DIR, cat_dir_name)
        if not os.path.isdir(cat_path):
            continue

        cat_norm = normalize_category_name(cat_dir_name)
        for mp4_file in glob.glob(os.path.join(cat_path, "*.mp4")):
            if os.path.basename(mp4_file).startswith("temp_"):
                continue

            res = media_db.register_media(
                file_path=mp4_file,
                media_type="video",
                subtype="general_broll",
                source="local_broll",
                tags=[cat_norm, cat_dir_name.lower()],
                description=f"Local B-roll for {cat_dir_name}",
                db_path=db_path
            )
            if not res.get("duplicate"):
                indexed_count += 1

    logger.info(f"[B-roll Engine] Synced existing general_broll assets. New: {indexed_count}")
    return {"new_brolls": indexed_count}
