"""
engine/media_db.py - Media Library & Cache SQLite Database Layer
================================================================
Accumulative Media Library management for Trot/Celebrity Shorts Automation.
Maintains persistent index of singer photos, stage clips, B-roll footage,
and external API search result caches.

Features:
  - SQLite WAL mode for concurrency and fast transactions
  - SHA-256 file hashing for deduplication
  - Singer auto-registration and alias matching
  - Photo query with smart prioritization (use_count ASC, last_used_at ASC, favorite DESC)
  - Project media usage tracking and penalty against recent reuse
  - API response caching with expiration (TTL)
  - Automatic existing assets scanner & indexer
"""

import os
import glob
import json
import sqlite3
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Union, Any, List, Dict, Tuple, Set
from contextlib import contextmanager

try:
    from PIL import Image
except ImportError:
    Image = None

logger = logging.getLogger("media_db")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Default database location at workspace root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "media_library.db")


@contextmanager
def get_db_connection(db_path: Optional[str] = None):
    """Context manager for SQLite connections with thread safety and WAL mode."""
    target_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    conn = sqlite3.connect(target_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        # Pragmas for reliability & performance
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error on {target_path}: {e}")
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> str:
    """
    Initializes SQLite tables and indexes if they do not already exist.
    Tables:
      - singers
      - media
      - media_tags
      - api_cache
      - project_history
      - project_media
    """
    target_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
    logger.info(f"Initializing Media DB at: {target_path}")

    with get_db_connection(target_path) as conn:
        cur = conn.cursor()

        # 1. singers table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS singers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                aliases TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. media table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                singer_id INTEGER,
                media_type TEXT NOT NULL,          -- 'photo', 'video', 'stage_clip'
                subtype TEXT,                      -- 'singer_photo', 'general_broll', 'stage_clip', 'stock_video'
                file_path TEXT NOT NULL UNIQUE,
                file_hash TEXT NOT NULL,           -- SHA-256 hex string
                dhash TEXT,                        -- 64-bit dHash hex string for photos
                source TEXT,                       -- 'bing', 'naver', 'pexels', 'pixabay', 'local', 'upload'
                source_url TEXT,
                provider_media_id TEXT,
                author TEXT,
                license TEXT,
                tags TEXT,                         -- Comma-separated tags string
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP,
                use_count INTEGER DEFAULT 0,
                favorite INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                FOREIGN KEY(singer_id) REFERENCES singers(id) ON DELETE SET NULL
            );
        """)

        # Migration: Add dhash column if media table already exists without it
        cur.execute("PRAGMA table_info(media);")
        media_columns = [row["name"] for row in cur.fetchall()]
        if "dhash" not in media_columns:
            try:
                cur.execute("ALTER TABLE media ADD COLUMN dhash TEXT;")
                logger.info("Migrated media table: added 'dhash' column.")
            except Exception as e:
                logger.warning(f"Could not add 'dhash' column to media table: {e}")

        # Migration: Add singer_cc_video metadata columns if missing
        cc_cols = {
            "youtube_video_id": "TEXT",
            "youtube_url": "TEXT",
            "channel_name": "TEXT",
            "video_title": "TEXT",
            "original_start": "REAL",
            "original_end": "REAL",
            "clip_duration": "REAL",
            "width": "INTEGER",
            "height": "INTEGER",
            "fps": "REAL",
            "rights_status": "TEXT DEFAULT 'verified'"
        }
        for col_name, col_type in cc_cols.items():
            if col_name not in media_columns:
                try:
                    cur.execute(f"ALTER TABLE media ADD COLUMN {col_name} {col_type};")
                    logger.info(f"Migrated media table: added '{col_name}' column.")
                except Exception as e:
                    logger.warning(f"Could not add '{col_name}' column to media table: {e}")

        # 3. media_tags table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS media_tags (
                media_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (media_id, tag),
                FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
            );
        """)

        # 4. api_cache table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,            -- 'pexels', 'pixabay', etc.
                query TEXT NOT NULL,               -- Normalized search query
                media_type TEXT NOT NULL,          -- 'video', 'photo'
                response_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            );
        """)

        # 5. project_history table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS project_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL UNIQUE,
                singer_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 6. project_media table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS project_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                media_id INTEGER NOT NULL,
                scene_index INTEGER,
                role TEXT,                         -- 'singer_photo', 'broll', 'thumbnail', etc.
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
            );
        """)

        # 7. qa_results table (독립 품질검증 시스템 결과 영구 보관)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS qa_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                singer_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                technical_score REAL DEFAULT 0,
                factual_score REAL DEFAULT 0,
                repetition_score REAL DEFAULT 0,
                content_score REAL DEFAULT 0,
                total_score REAL DEFAULT 0,
                status TEXT NOT NULL,              -- 'PASS', 'WARNING', 'FAIL', 'NOT_RUN'
                critical_error INTEGER DEFAULT 0,  -- 1 if fatal error triggered
                issues_json TEXT,                  -- Detailed issues breakdown
                recommendations_json TEXT,         -- Actionable advice list
                shorts_result_json TEXT,
                blog_result_json TEXT,
                qa_model TEXT DEFAULT 'rule+gemini'
            );
        """)

        # Performance Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_singers_name ON singers(name);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_media_file_hash ON media(file_hash);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_media_dhash ON media(dhash);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_media_singer_id ON media(singer_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_media_type_subtype ON media(media_type, subtype);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_media_active ON media(active);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_media_use_favorite ON media(favorite, use_count, last_used_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_media_tags_tag ON media_tags(tag);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_api_cache_lookup ON api_cache(provider, query, media_type);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_project_media_proj ON project_media(project_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_project_history_proj ON project_history(project_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_results_proj ON qa_results(project_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_results_status ON qa_results(status);")

    logger.info("Media DB tables and indexes successfully verified/created.")
    return target_path


def compute_file_hash(file_path: str) -> str:
    """
    Computes SHA-256 hex digest of a file in 64KB binary chunks.
    Ensures memory efficiency for both small photos and large video clips.
    """
    norm_path = os.path.abspath(os.path.normpath(file_path))
    if not os.path.isfile(norm_path):
        raise FileNotFoundError(f"Cannot compute hash. File not found: {norm_path}")
    
    hasher = hashlib.sha256()
    with open(norm_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def update_media_file_hash(file_path: str, db_path: Optional[str] = None) -> bool:
    """Updates file_hash and dhash in database when a file is edited or cropped."""
    norm_path = os.path.abspath(os.path.normpath(file_path))
    if not os.path.isfile(norm_path):
        return False
    
    new_hash = compute_file_hash(norm_path)
    new_dhash = None
    try:
        new_dhash = compute_dhash(norm_path)
    except Exception:
        pass
        
    target_db = os.path.abspath(db_path or DEFAULT_DB_PATH)
    try:
        with get_db_connection(target_db) as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE media SET file_hash = ?, dhash = ? WHERE file_path = ?",
                (new_hash, new_dhash, norm_path)
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.warning(f"Could not update media file hash for {norm_path}: {e}")
        return False


def compute_dhash(image_path: str) -> str:
    """
    Computes a 64-bit difference hash (dHash) for an image.
    1. Loads image with PIL.
    2. Converts to 'L' (grayscale).
    3. Resizes to (9, 8) using Resampling.LANCZOS.
    4. Compares adjacent horizontal pixels: (row[x] > row[x+1]) to yield 64 bits.
    5. Formats as 16-hex character string.
    """
    norm_path = os.path.abspath(os.path.normpath(image_path))
    if not os.path.isfile(norm_path):
        raise FileNotFoundError(f"Cannot compute dHash. File not found: {norm_path}")

    from PIL import Image
    try:
        resample_filter = Image.Resampling.LANCZOS
    except AttributeError:
        resample_filter = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", 1))

    with Image.open(norm_path) as img:
        gray = img.convert("L").resize((9, 8), resample_filter)
        pixels = list(gray.getdata())  # 72 pixels: 8 rows of 9 pixels

    dhash_int = 0
    for row in range(8):
        row_offset = row * 9
        for col in range(8):
            dhash_int <<= 1
            if pixels[row_offset + col] > pixels[row_offset + col + 1]:
                dhash_int |= 1

    return f"{dhash_int:016x}"


def hamming_distance(hash1: str, hash2: str) -> int:
    """
    Counts differing bits between two 16-hex strings.
    Returns distance (0 to 64).
    """
    if not hash1 or not hash2:
        return 64
    try:
        val1 = int(str(hash1).strip(), 16)
        val2 = int(str(hash2).strip(), 16)
        xor_val = val1 ^ val2
        if hasattr(xor_val, "bit_count"):
            return xor_val.bit_count()
        return bin(xor_val).count("1")
    except (ValueError, TypeError):
        return 64


def find_near_duplicate_photos(
    image_paths: List[str],
    threshold: int = 5,
    db_path: Optional[str] = None
) -> List[Tuple[str, str, int]]:
    """
    Finds pairs of near-duplicate images with Hamming distance <= threshold.
    
    Examines image_paths pairwise and optionally checks against active photos
    stored in the database if db_path is provided.
    
    Returns:
        List of tuples: (image1_path, image2_path, distance)
    """
    if not image_paths:
        return []

    # 1. Resolve dHash for input images
    # Use database cache if db_path is available
    db_cache: Dict[str, str] = {}
    target_db = os.path.abspath(db_path) if db_path else None
    if target_db and os.path.exists(target_db):
        try:
            with get_db_connection(target_db) as conn:
                cur = conn.cursor()
                cur.execute("SELECT file_path, dhash FROM media WHERE dhash IS NOT NULL AND active = 1")
                for r in cur.fetchall():
                    norm_fp = os.path.abspath(os.path.normpath(r["file_path"]))
                    if r["dhash"]:
                        db_cache[norm_fp] = r["dhash"]
        except Exception as e:
            logger.debug(f"Could not load DB dHash cache: {e}")

    valid_hashes: List[Tuple[str, str]] = []
    for path in image_paths:
        norm_p = os.path.abspath(os.path.normpath(path))
        img_hash = db_cache.get(norm_p)
        if not img_hash and os.path.isfile(norm_p):
            try:
                img_hash = compute_dhash(norm_p)
            except Exception as e:
                logger.debug(f"Could not compute dhash for {norm_p}: {e}")
                img_hash = None
        if img_hash:
            valid_hashes.append((norm_p, img_hash))

    near_duplicates: List[Tuple[str, str, int]] = []
    seen_pairs: Set[Tuple[str, str]] = set()

    # 2. Pairwise comparison within image_paths
    for i in range(len(valid_hashes)):
        p1, h1 = valid_hashes[i]
        for j in range(i + 1, len(valid_hashes)):
            p2, h2 = valid_hashes[j]
            pair_key = (min(p1, p2), max(p1, p2))
            if pair_key in seen_pairs:
                continue
            dist = hamming_distance(h1, h2)
            if dist <= threshold:
                seen_pairs.add(pair_key)
                near_duplicates.append((p1, p2, dist))

    # 3. If db_path is provided, also compare input images against other DB photos
    if target_db and os.path.exists(target_db):
        try:
            with get_db_connection(target_db) as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT file_path, dhash
                    FROM media
                    WHERE media_type = 'photo' AND active = 1 AND dhash IS NOT NULL
                """)
                db_rows = cur.fetchall()
                for p1, h1 in valid_hashes:
                    for r in db_rows:
                        db_p = os.path.abspath(os.path.normpath(r["file_path"]))
                        if db_p == p1:
                            continue  # Skip identical path
                        db_h = r["dhash"]
                        if not db_h:
                            continue
                        pair_key = (min(p1, db_p), max(p1, db_p))
                        if pair_key in seen_pairs:
                            continue
                        dist = hamming_distance(h1, db_h)
                        if dist <= threshold:
                            seen_pairs.add(pair_key)
                            near_duplicates.append((p1, db_p, dist))
        except Exception as e:
            logger.debug(f"DB comparison in find_near_duplicate_photos error: {e}")

    return near_duplicates


def get_or_create_singer(
    name: str,
    aliases: str = "",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Looks up a singer by name or aliases. If not found, registers a new singer.
    Returns a dict representation of the singer row.
    """
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Singer name cannot be empty.")
    
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        
        # 1. Exact name match (case-insensitive)
        cur.execute("SELECT * FROM singers WHERE name = ? COLLATE NOCASE", (clean_name,))
        row = cur.fetchone()
        if row:
            singer_dict = dict(row)
            # Update aliases if new aliases provided and existing was empty
            if aliases and not singer_dict.get("aliases"):
                cur.execute("UPDATE singers SET aliases = ? WHERE id = ?", (aliases.strip(), singer_dict["id"]))
                singer_dict["aliases"] = aliases.strip()
            return singer_dict
        
        # 2. Check if clean_name is an existing alias
        cur.execute("SELECT * FROM singers WHERE aliases LIKE ? COLLATE NOCASE", (f"%{clean_name}%",))
        alias_row = cur.fetchone()
        if alias_row:
            return dict(alias_row)
        
        # 3. Create new singer record
        clean_aliases = aliases.strip() if aliases else None
        cur.execute("INSERT INTO singers (name, aliases) VALUES (?, ?)", (clean_name, clean_aliases))
        new_id = cur.lastrowid
        
        cur.execute("SELECT * FROM singers WHERE id = ?", (new_id,))
        return dict(cur.fetchone())


def register_media(
    file_path: str,
    singer_name: Optional[str] = None,
    media_type: str = "photo",
    subtype: str = "singer_photo",
    source: str = "bing",
    source_url: Optional[str] = None,
    tags: Optional[Union[List[str], set, str]] = None,
    description: Optional[str] = None,
    provider_media_id: Optional[str] = None,
    author: Optional[str] = None,
    license: Optional[str] = None,
    favorite: int = 0,
    active: int = 1,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Registers a media file into the media library with robust SHA-256 deduplication.
    
    If the file hash already exists in the database:
      - Marks 'is_duplicate': True, 'duplicate': True
      - Updates file_path if original file was moved or path changed
      - Associates singer_id or tags if missing
      - Returns existing record without creating duplicate entries
    
    If new:
      - Inserts new row into 'media'
      - Inserts individual tags into 'media_tags'
      - Returns new record with 'is_duplicate': False
    """
    norm_path = os.path.abspath(os.path.normpath(file_path))
    if not os.path.isfile(norm_path):
        raise FileNotFoundError(f"Media file not found on disk: {norm_path}")
    
    file_hash = compute_file_hash(norm_path)
    
    # Compute dHash for photos
    dhash = None
    ext = os.path.splitext(norm_path)[1].lower()
    if media_type == "photo" or ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
        try:
            dhash = compute_dhash(norm_path)
        except Exception as e:
            logger.debug(f"Could not compute dhash for {norm_path}: {e}")
    
    # Normalize tags
    tag_list = []
    if tags:
        if isinstance(tags, (list, set, tuple)):
            tag_list = [str(t).strip().lower() for t in tags if str(t).strip()]
        elif isinstance(tags, str):
            tag_list = [t.strip().lower() for t in tags.replace(";", ",").split(",") if t.strip()]
    tag_list = list(dict.fromkeys(tag_list))  # Deduplicate tags preserving order
    tags_str = ",".join(tag_list) if tag_list else None

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        
        singer_id = None
        if singer_name:
            singer = get_or_create_singer(singer_name, db_path=db_path)
            singer_id = singer["id"]

        # 1. Check duplicate via file_hash
        cur.execute("SELECT * FROM media WHERE file_hash = ?", (file_hash,))
        dup_row = cur.fetchone()
        if dup_row:
            existing = dict(dup_row)
            updates = []
            params = []
            
            # If stored path doesn't exist on disk, update to current path
            if existing["file_path"] != norm_path and not os.path.exists(existing["file_path"]):
                updates.append("file_path = ?")
                params.append(norm_path)
                existing["file_path"] = norm_path
            
            # Activate if currently inactive
            if existing["active"] == 0 and active == 1:
                updates.append("active = 1")
                existing["active"] = 1
            
            # Associate singer if previously unassigned
            if singer_id and not existing.get("singer_id"):
                updates.append("singer_id = ?")
                params.append(singer_id)
                existing["singer_id"] = singer_id
            
            # Update dhash if missing in existing record
            if dhash and not existing.get("dhash"):
                updates.append("dhash = ?")
                params.append(dhash)
                existing["dhash"] = dhash
            
            if updates:
                params.append(existing["id"])
                cur.execute(f"UPDATE media SET {', '.join(updates)} WHERE id = ?", tuple(params))
            
            # Insert any missing tags
            for t in tag_list:
                cur.execute("INSERT OR IGNORE INTO media_tags (media_id, tag) VALUES (?, ?)", (existing["id"], t))
            
            existing["is_duplicate"] = True
            existing["duplicate"] = True
            return existing

        # 2. Check if identical file_path is already registered with an older hash
        cur.execute("SELECT * FROM media WHERE file_path = ?", (norm_path,))
        path_row = cur.fetchone()
        if path_row:
            existing = dict(path_row)
            cur.execute("UPDATE media SET file_hash = ?, dhash = ?, active = 1 WHERE id = ?", (file_hash, dhash, existing["id"]))
            existing["file_hash"] = file_hash
            existing["dhash"] = dhash
            existing["is_duplicate"] = True
            existing["duplicate"] = True
            return existing

        # 3. Insert new media record
        cur.execute("""
            INSERT INTO media (
                singer_id, media_type, subtype, file_path, file_hash, dhash,
                source, source_url, provider_media_id, author, license,
                tags, description, favorite, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            singer_id, media_type, subtype, norm_path, file_hash, dhash,
            source, source_url, provider_media_id, author, license,
            tags_str, description, favorite, active
        ))
        media_id = cur.lastrowid

        # 4. Insert normalized tags into media_tags table
        for t in tag_list:
            cur.execute("INSERT OR IGNORE INTO media_tags (media_id, tag) VALUES (?, ?)", (media_id, t))

        cur.execute("SELECT * FROM media WHERE id = ?", (media_id,))
        result = dict(cur.fetchone())
        result["is_duplicate"] = False
        result["duplicate"] = False
        return result


def query_singer_photos(
    singer_name: str,
    limit: int = 30,
    exclude_recent_project_id: Optional[str] = None,
    exclude_recent_project: Optional[str] = None,
    order_by: str = "use_count ASC, last_used_at ASC, favorite DESC",
    db_path: Optional[str] = None
) -> List[str]:
    """
    Queries valid existing photo file paths for a specific singer.
    
    Prioritization criteria (smart sorting):
      - Low use count first (use_count ASC)
      - Not used recently (last_used_at ASC; NULLs appear first)
      - User favorites prioritized (favorite DESC)
      - Excludes photos used in 'exclude_recent_project'
      - Automatically detects deleted files on disk and flags them inactive (active=0)
    
    Returns:
      List[str]: List of existing absolute file paths (up to 'limit')
    """
    proj_id = exclude_recent_project or exclude_recent_project_id

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()

        # Find singer record
        cur.execute("SELECT id FROM singers WHERE name = ? COLLATE NOCASE", (singer_name.strip(),))
        s_row = cur.fetchone()
        if not s_row:
            cur.execute("SELECT id FROM singers WHERE aliases LIKE ? COLLATE NOCASE", (f"%{singer_name.strip()}%",))
            s_row = cur.fetchone()
        
        if not s_row:
            return []

        singer_id = s_row["id"]

        # Build query
        query_sql = """
            SELECT m.id, m.file_path, m.use_count, m.last_used_at, m.favorite
            FROM media m
            WHERE m.singer_id = ?
              AND m.media_type = 'photo'
              AND m.active = 1
        """
        params: List[Any] = [singer_id]

        if proj_id:
            query_sql += """
                AND m.id NOT IN (
                    SELECT media_id FROM project_media WHERE project_id = ?
                )
            """
            params.append(proj_id)

        # Apply ordering
        query_sql += f" ORDER BY {order_by}"

        cur.execute(query_sql, tuple(params))
        rows = cur.fetchall()

        valid_paths: List[str] = []
        inactive_ids: List[int] = []

        for r in rows:
            fpath = r["file_path"]
            if os.path.isfile(fpath):
                valid_paths.append(fpath)
                if len(valid_paths) >= limit:
                    break
            else:
                inactive_ids.append(r["id"])

        # Auto-deactivate missing files
        if inactive_ids:
            cur.executemany("UPDATE media SET active = 0 WHERE id = ?", [(i,) for i in inactive_ids])

        return valid_paths


def record_media_usage(
    media_id: int,
    project_id: Optional[str] = None,
    scene_index: Optional[int] = None,
    role: str = "singer_photo",
    db_path: Optional[str] = None
) -> bool:
    """
    Increments use_count and updates last_used_at for a media item.
    Optionally records the project scene role in project_media.
    """
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE media
            SET use_count = use_count + 1,
                last_used_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (media_id,))
        
        if project_id:
            cur.execute("""
                INSERT INTO project_media (project_id, media_id, scene_index, role)
                VALUES (?, ?, ?, ?)
            """, (project_id, media_id, scene_index, role))
        
        return cur.rowcount > 0


def record_project_usage(
    project_id: str,
    singer_name: str,
    used_media_paths: List[str],
    scene_roles: Optional[List[str]] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Records a completed project run and updates all used media items.
    
    1. Records project in project_history
    2. Matches each media path against the media database (auto-registers if not yet tracked)
    3. Increments use_count and updates last_used_at
    4. Logs scene indices and roles into project_media
    """
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()

        # 1. Project history entry
        cur.execute("""
            INSERT OR REPLACE INTO project_history (project_id, singer_name, created_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (project_id, singer_name))

        recorded_count = 0
        media_ids: List[int] = []

        for i, raw_path in enumerate(used_media_paths):
            norm_p = os.path.abspath(os.path.normpath(raw_path))
            role = scene_roles[i] if (scene_roles and i < len(scene_roles) and scene_roles[i]) else "singer_photo"

            # Check existing media
            cur.execute("SELECT id FROM media WHERE file_path = ?", (norm_p,))
            m_row = cur.fetchone()
            if not m_row and os.path.isfile(norm_p):
                f_hash = compute_file_hash(norm_p)
                cur.execute("SELECT id FROM media WHERE file_hash = ?", (f_hash,))
                m_row = cur.fetchone()

            if m_row:
                m_id = m_row["id"]
            else:
                # Auto register if physical file exists
                if os.path.isfile(norm_p):
                    ext = os.path.splitext(norm_p)[1].lower()
                    m_type = "video" if ext in (".mp4", ".avi", ".mov", ".mkv", ".webm") else "photo"
                    subtype = "stage_clip" if "clips" in norm_p.lower() else ("general_broll" if "stock" in norm_p.lower() else "singer_photo")
                    reg = register_media(
                        file_path=norm_p,
                        singer_name=singer_name,
                        media_type=m_type,
                        subtype=subtype,
                        source="project_auto",
                        db_path=db_path
                    )
                    m_id = reg["id"]
                else:
                    continue

            # Update usage
            cur.execute("""
                UPDATE media
                SET use_count = use_count + 1,
                    last_used_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (m_id,))

            cur.execute("""
                INSERT INTO project_media (project_id, media_id, scene_index, role)
                VALUES (?, ?, ?, ?)
            """, (project_id, m_id, i, role))

            media_ids.append(m_id)
            recorded_count += 1

        return {
            "project_id": project_id,
            "singer_name": singer_name,
            "recorded_count": recorded_count,
            "media_ids": media_ids
        }


def get_api_cache(
    provider: str,
    query: str,
    media_type: str = "video",
    db_path: Optional[str] = None
) -> Optional[Any]:
    """
    Retrieves cached external API response (Pexels, Pixabay, Bing, etc.)
    Returns parsed JSON data (dict or list) if unexpired, or None if miss/expired.
    """
    norm_provider = provider.strip().lower()
    norm_query = query.strip().lower()
    norm_type = media_type.strip().lower()

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT response_json, expires_at
            FROM api_cache
            WHERE provider = ? AND query = ? AND media_type = ?
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            ORDER BY created_at DESC
            LIMIT 1
        """, (norm_provider, norm_query, norm_type))
        row = cur.fetchone()
        if not row:
            return None

        raw_json = row["response_json"]
        try:
            return json.loads(raw_json)
        except Exception:
            return raw_json


def set_api_cache(
    provider: str,
    query: str,
    arg3: Any,
    arg4: Optional[Any] = None,
    media_type: str = "video",
    ttl_days: int = 30,
    db_path: Optional[str] = None
) -> bool:
    """
    Stores external API response in SQLite cache with a TTL (default 30 days).
    
    Supports flexible signatures:
      set_api_cache(provider, query, response_json, media_type='video', ttl_days=30)
      set_api_cache(provider, query, media_type, response_json, ttl_days=30)
    """
    if arg4 is not None:
        actual_media_type = str(arg3).strip().lower()
        actual_response = arg4
    else:
        if isinstance(arg3, (dict, list)):
            actual_response = arg3
            actual_media_type = media_type.strip().lower()
        elif isinstance(arg3, str) and (arg3.strip().startswith("{") or arg3.strip().startswith("[")):
            actual_response = arg3
            actual_media_type = media_type.strip().lower()
        elif arg3 in ("video", "photo", "stage_clip", "music"):
            actual_media_type = str(arg3).strip().lower()
            actual_response = ""
        else:
            actual_response = arg3
            actual_media_type = media_type.strip().lower()

    if isinstance(actual_response, (dict, list)):
        payload_str = json.dumps(actual_response, ensure_ascii=False)
    else:
        payload_str = str(actual_response)

    norm_provider = provider.strip().lower()
    norm_query = query.strip().lower()

    expires_dt = datetime.utcnow() + timedelta(days=ttl_days)
    expires_at_str = expires_dt.strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM api_cache
            WHERE provider = ? AND query = ? AND media_type = ?
        """, (norm_provider, norm_query, actual_media_type))
        existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE api_cache
                SET response_json = ?, created_at = CURRENT_TIMESTAMP, expires_at = ?
                WHERE id = ?
            """, (payload_str, expires_at_str, existing["id"]))
        else:
            cur.execute("""
                INSERT INTO api_cache (provider, query, media_type, response_json, expires_at)
                VALUES (?, ?, ?, ?, ?)
            """, (norm_provider, norm_query, actual_media_type, payload_str, expires_at_str))
        return True


def get_media_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns summary counts of registered media, singers, cache, and DB size.
    """
    target_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
    if not os.path.exists(target_path):
        init_db(target_path)

    with get_db_connection(target_path) as conn:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) as cnt FROM singers")
        total_singers = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM media WHERE active = 1")
        total_media = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM media WHERE media_type = 'photo' AND active = 1")
        total_photos = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM media WHERE (subtype = 'general_broll' OR media_type = 'video') AND active = 1")
        total_brolls = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM media WHERE subtype = 'stage_clip' AND active = 1")
        total_stage_clips = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM api_cache WHERE expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP")
        total_cache_entries = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) as cnt FROM project_history")
        total_projects = cur.fetchone()["cnt"]

        db_size_bytes = os.path.getsize(target_path) if os.path.exists(target_path) else 0

        return {
            "total_singers": total_singers,
            "total_media": total_media,
            "total_photos": total_photos,
            "total_brolls": total_brolls,
            "total_stage_clips": total_stage_clips,
            "total_cache_entries": total_cache_entries,
            "total_projects": total_projects,
            "db_size_bytes": db_size_bytes,
            "db_path": target_path
        }


# Function alias
get_db_stats = get_media_stats


def query_brolls(
    tags: Optional[List[str]] = None,
    limit: int = 10,
    order_by: str = "use_count ASC, last_used_at ASC, favorite DESC",
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Queries B-roll media items optionally filtered by tags.
    """
    with get_db_connection(db_path) as conn:
        cur = conn.cursor()

        if tags:
            tag_placeholders = ",".join("?" for _ in tags)
            sql = f"""
                SELECT DISTINCT m.*
                FROM media m
                JOIN media_tags mt ON m.id = mt.media_id
                WHERE (m.subtype = 'general_broll' OR m.media_type = 'video')
                  AND m.active = 1
                  AND mt.tag IN ({tag_placeholders})
                ORDER BY m.{order_by}
                LIMIT ?
            """
            cur.execute(sql, (*[t.strip().lower() for t in tags], limit))
        else:
            sql = f"""
                SELECT *
                FROM media
                WHERE (subtype = 'general_broll' OR media_type = 'video')
                  AND active = 1
                ORDER BY {order_by}
                LIMIT ?
            """
            cur.execute(sql, (limit,))

        rows = cur.fetchall()
        return [dict(r) for r in rows if os.path.isfile(r["file_path"])]


def sync_existing_assets(db_path: Optional[str] = None) -> Dict[str, int]:
    """
    Scans existing assets directories (assets/singers, assets/stock_videos)
    and registers all found media into media_library.db.
    """
    init_db(db_path)
    indexed_clips = 0
    indexed_photos = 0
    indexed_stocks = 0

    # 1. Singer stage clips & photos in assets/singers
    singers_root = os.path.join(PROJECT_ROOT, "assets", "singers")
    if os.path.isdir(singers_root):
        for singer_dir in os.listdir(singers_root):
            singer_path = os.path.join(singers_root, singer_dir)
            if not os.path.isdir(singer_path):
                continue
            
            singer_name = singer_dir.replace("_", " ")

            # Check clips
            clips_dir = os.path.join(singer_path, "clips")
            if os.path.isdir(clips_dir):
                for clip_file in glob.glob(os.path.join(clips_dir, "*.mp4")):
                    res = register_media(
                        file_path=clip_file,
                        singer_name=singer_name,
                        media_type="video",
                        subtype="stage_clip",
                        source="local_asset",
                        tags=["stage", "performance", singer_name],
                        db_path=db_path
                    )
                    if not res.get("duplicate"):
                        indexed_clips += 1

            # Check photos if any
            photos_dir = os.path.join(singer_path, "photos")
            if os.path.isdir(photos_dir):
                for p_ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
                    for photo_file in glob.glob(os.path.join(photos_dir, p_ext)):
                        res = register_media(
                            file_path=photo_file,
                            singer_name=singer_name,
                            media_type="photo",
                            subtype="singer_photo",
                            source="local_asset",
                            tags=["singer", singer_name],
                            db_path=db_path
                        )
                        if not res.get("duplicate"):
                            indexed_photos += 1

    # 2. General stock videos in assets/stock_videos
    stock_root = os.path.join(PROJECT_ROOT, "assets", "stock_videos")
    if os.path.isdir(stock_root):
        for stock_file in glob.glob(os.path.join(stock_root, "*.mp4")):
            base_name = os.path.splitext(os.path.basename(stock_file))[0]
            tags = [t for t in base_name.replace("-", "_").split("_") if t]
            res = register_media(
                file_path=stock_file,
                singer_name=None,
                media_type="video",
                subtype="general_broll",
                source="stock_asset",
                tags=tags,
                db_path=db_path
            )
            if not res.get("duplicate"):
                indexed_stocks += 1

    # 3. Categorized B-rolls in assets/general_broll
    indexed_brolls = 0
    broll_root = os.path.join(PROJECT_ROOT, "assets", "general_broll")
    if os.path.isdir(broll_root):
        for cat_dir in os.listdir(broll_root):
            cat_path = os.path.join(broll_root, cat_dir)
            if not os.path.isdir(cat_path):
                continue
            for broll_file in glob.glob(os.path.join(cat_path, "*.mp4")):
                if os.path.basename(broll_file).startswith("temp_"):
                    continue
                res = register_media(
                    file_path=broll_file,
                    singer_name=None,
                    media_type="video",
                    subtype="general_broll",
                    source="local_broll",
                    tags=[cat_dir.lower(), "broll"],
                    description=f"Local B-roll for {cat_dir}",
                    db_path=db_path
                )
                if not res.get("duplicate"):
                    indexed_brolls += 1

    logger.info(f"Sync complete. New clips: {indexed_clips}, photos: {indexed_photos}, stocks: {indexed_stocks}, brolls: {indexed_brolls}")
    return {
        "new_clips": indexed_clips,
        "new_photos": indexed_photos,
        "new_stocks": indexed_stocks,
        "new_brolls": indexed_brolls
    }


def record_qa_result(
    project_id: str,
    singer_name: str,
    technical_score: float,
    factual_score: float,
    repetition_score: float,
    content_score: float,
    total_score: float,
    status: str,
    issues: Optional[List[Dict[str, Any]]] = None,
    recommendations: Optional[List[str]] = None,
    critical_error: bool = False,
    shorts_result: Optional[Dict[str, Any]] = None,
    blog_result: Optional[Dict[str, Any]] = None,
    qa_model: str = "rule+gemini",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Stores an immutable record of a QA verification run into qa_results table.
    """
    target_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
    init_db(target_path)

    with get_db_connection(target_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO qa_results (
                project_id, singer_name, technical_score, factual_score,
                repetition_score, content_score, total_score, status,
                critical_error, issues_json, recommendations_json,
                shorts_result_json, blog_result_json, qa_model
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            singer_name,
            round(float(technical_score), 2),
            round(float(factual_score), 2),
            round(float(repetition_score), 2),
            round(float(content_score), 2) if content_score is not None else None,
            round(float(total_score), 2),
            status,
            1 if critical_error else 0,
            json.dumps(issues or [], ensure_ascii=False),
            json.dumps(recommendations or [], ensure_ascii=False),
            json.dumps(shorts_result or {}, ensure_ascii=False),
            json.dumps(blog_result or {}, ensure_ascii=False),
            qa_model
        ))
        row_id = cur.lastrowid
        return {
            "id": row_id,
            "project_id": project_id,
            "status": status,
            "total_score": total_score
        }


def get_recent_qa_results(
    limit: int = 10,
    singer_name: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Returns the most recent QA verification records.
    """
    target_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
    if not os.path.exists(target_path):
        return []

    with get_db_connection(target_path) as conn:
        cur = conn.cursor()
        if singer_name:
            cur.execute("""
                SELECT * FROM qa_results
                WHERE singer_name = ? COLLATE NOCASE
                ORDER BY created_at DESC LIMIT ?
            """, (singer_name.strip(), limit))
        else:
            cur.execute("""
                SELECT * FROM qa_results
                ORDER BY created_at DESC LIMIT ?
            """, (limit,))
        
        rows = cur.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            for k in ("issues_json", "recommendations_json", "shorts_result_json", "blog_result_json"):
                if d.get(k):
                    try:
                        d[k.replace("_json", "")] = json.loads(d[k])
                    except Exception:
                        pass
            results.append(d)
        return results


def get_recent_singer_projects(
    singer_name: str,
    limit: int = 5,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieves recent projects and used media for the specified singer to enable repetition checking.
    """
    target_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
    if not os.path.exists(target_path):
        return []

    with get_db_connection(target_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, project_id, singer_name, created_at
            FROM project_history
            WHERE singer_name = ? COLLATE NOCASE
            ORDER BY created_at DESC LIMIT ?
        """, (singer_name.strip(), limit))
        p_rows = cur.fetchall()
        
        projects = []
        for p in p_rows:
            pid = p["project_id"]
            cur.execute("""
                SELECT pm.scene_index, pm.role, m.file_path, m.file_hash, m.dhash, m.subtype, m.tags
                FROM project_media pm
                JOIN media m ON pm.media_id = m.id
                WHERE pm.project_id = ?
                ORDER BY pm.scene_index ASC
            """, (pid,))
            media_list = [dict(mr) for mr in cur.fetchall()]
            projects.append({
                "project_id": pid,
                "singer_name": p["singer_name"],
                "created_at": p["created_at"],
                "media": media_list
            })
        return projects


def delete_media_record(
    target: Union[int, str],
    db_path: Optional[str] = None
) -> bool:
    """
    Deletes a media item from media_library.db and removes the underlying file from disk.
    target can be media_id (int) or file_path (str).
    """
    target_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
    if not os.path.exists(target_path):
        return False

    with get_db_connection(target_path) as conn:
        cur = conn.cursor()
        if isinstance(target, int) or (isinstance(target, str) and target.isdigit()):
            mid = int(target)
            cur.execute("SELECT id, file_path FROM media WHERE id = ?", (mid,))
        else:
            fpath = os.path.abspath(os.path.normpath(str(target)))
            cur.execute("SELECT id, file_path FROM media WHERE file_path = ?", (fpath,))
        
        row = cur.fetchone()
        if not row:
            return False
        
        m_id = row["id"]
        m_path = row["file_path"]

        cur.execute("DELETE FROM media_tags WHERE media_id = ?", (m_id,))
        cur.execute("DELETE FROM project_media WHERE media_id = ?", (m_id,))
        cur.execute("DELETE FROM media WHERE id = ?", (m_id,))

        if m_path and os.path.isfile(m_path):
            try:
                os.remove(m_path)
            except Exception as e:
                logger.warning(f"Could not remove file {m_path} from disk: {e}")
        return True


if __name__ == "__main__":
    print("=== Media DB Standalone Verification ===")
    test_db = os.path.join(PROJECT_ROOT, "test_media_library.db")
    if os.path.exists(test_db):
        os.remove(test_db)
    
    init_db(test_db)
    stats = get_media_stats(test_db)
    print(f"Initialized test DB: {stats}")
