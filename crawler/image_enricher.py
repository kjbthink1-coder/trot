import os
import re
import urllib.request
from urllib.parse import quote, urlparse
import ssl
from PIL import Image
import io
import random
import logging
from typing import Optional, List, Dict, Any, Union

logger = logging.getLogger("image_enricher")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
}

SSL_CTX = ssl._create_unverified_context()

def is_logo_or_graphic(im: Image.Image) -> bool:
    """
    단색 배경에 텍스트가 박힌 언론사 대표 로고(예: THE FACT 붉은 로고, X 주황 로고 등),
    아이콘, 배너, 그래픽 카드를 정밀하게 검출하여 차단합니다.
    """
    try:
        rgb_im = im.convert("RGB")
        small = rgb_im.resize((100, 100))
        colors = small.getcolors(maxcolors=10000)
        if not colors:
            return False

        total_pixels = 10000
        sorted_colors = sorted(colors, key=lambda x: x[0], reverse=True)
        top1_pct = sorted_colors[0][0] / total_pixels
        top2_pct = (sorted_colors[0][0] + (sorted_colors[1][0] if len(sorted_colors) > 1 else 0)) / total_pixels

        # 주 1~2개 색상의 비율이 70% 이상이면 단색 로고/배너/그래픽 카드로 판정하여 차단
        if top1_pct > 0.60 or top2_pct > 0.72:
            return True

        return False
    except Exception:
        return False


def is_valid_photo(file_path: str, min_w: int = 280, min_h: int = 200) -> bool:
    """작은 아이콘(URL, A 등 버튼) 및 단색 로고를 필터링하고 FFmpeg 호환을 위해 표준 RGB JPEG로 정규화합니다."""
    try:
        with Image.open(file_path) as im:
            w, h = im.size
            if w < min_w or h < min_h:
                return False
            # 정방형에 가까운 초소형 아이콘 필터
            if w <= 64 and h <= 64:
                return False
            if is_logo_or_graphic(im):
                return False
            rgb_im = im.convert("RGB")
        # AVIF, WebP 등을 순수 표준 JPEG로 재저장 (FFmpeg demuxer 오류 방지)
        rgb_im.save(file_path, "JPEG", quality=95)
        return True
    except Exception:
        return False

# 한국 연예인 사진 검색용 최적화 템플릿
SEARCH_TEMPLATES = [
    "가수 {singer}",
    "{singer} 콘서트",
    "{singer} 무대",
    "{singer} 고화질"
]


def _crawl_external_singer_photos(
    singer_name: str,
    target_count: int = 30,
    output_dir: str = "outputs/crawled",
    existing_paths: Optional[set] = None
) -> List[str]:
    """
    국내 포털(다음/카카오) 및 글로벌 검색에서 가수의 고화질 세로형/얼굴인식 사진을 target_count만큼 검색하여 다운로드합니다.
    - 국내 대표 연예 포털(다음 뉴스/포토)을 1순위로 탐색하여 엉뚱한 해외 이미지/동음이의어 원천 차단
    - OpenCV Haar Cascade 얼굴 인식 점수 가산
    - 세로형(aspect-tall) 비율 우선
    - 언론사 로고/쇼핑몰/문서/단어장/만화/광고 엄격 차단
    - 400x350 이상 고화질 선별
    """
    if target_count <= 0:
        return []

    os.makedirs(output_dir, exist_ok=True)
    existing_paths = existing_paths or set()

    # 엉뚱한 언론사 로고(THE FACT, X 등), 쇼핑몰 상품, 영어 단어장, 교재, 만화, 아이콘 도메인 및 키워드 강력 차단
    BLOCKED_KEYWORDS = [
        'icon', 'logo', 'banner', 'thumb', 'shop', 'product', 'item', 'goods', 
        'paint', 'roller', 'kuas', 'supra', 'tokopedia', 'lazada', 'shopee',
        'cartoon', 'anime', 'illustration', 'clipart', 'vector', 'drawing',
        'grammar', 'vocab', 'vocabulary', 'spoke', 'english', 'guide', 'worksheet',
        'diagram', 'chart', 'infographic', 'document', 'pdf', 'slide',
        'thefact', 'tf.co.kr', 'xports', 'xportsnews', 'newsen', 'starnews',
        'mydaily', 'osen', 'dispatch', 'spotv', 'mhn', 'rnx', 'news1', 'newsis',
        'yna.co.kr', 'herald', 'symbol', 'ci_', 'favicon', 'avatar', 'btn_'
    ]

    all_murls = []

    # 1. 국내 대표 포털(다음/카카오 이미지/뉴스) 1순위 전수 탐색 (한국 트로트 가수에 100% 최적화)
    # 다음/카카오 검색은 엉뚱한 해외 쇼핑몰/마라톤/외국 사진 없이 100% 진짜 가수 사진만 보장됨
    daum_urls = []
    try:
        daum_queries = [
            f"가수 {singer_name}",
            f"{singer_name} 콘서트",
            f"{singer_name} 무대",
            f"{singer_name} 화보",
            f"{singer_name} 행사",
            f"{singer_name} 고화질"
        ]
        for dq in daum_queries:
            d_url = f"https://search.daum.net/search?w=img&q={quote(dq)}"
            d_req = urllib.request.Request(d_url, headers=HEADERS)
            d_html = urllib.request.urlopen(d_req, context=SSL_CTX, timeout=7).read().decode('utf-8', errors='ignore')
            # 다음 이미지 결과 추출
            d_matches = re.findall(r'https?://[a-zA-Z0-9_./-]+\.(?:jpg|jpeg|png)', d_html)
            valid_d = [
                m for m in d_matches 
                if any(domain in m for domain in ['daumcdn', 'kakaocdn', 'news', 'photo', 'img', 'media', 'nate.com', 'wikitree'])
                and not any(b in m.lower() for b in ['daum_og', 'favicon', 'icon', 'logo', 'blank', 'avatar'])
            ]
            daum_urls.extend(valid_d)
    except Exception as e:
        logger.debug(f"다음 이미지 검색 예외: {e}")

    daum_unique = list(dict.fromkeys(daum_urls))
    logger.info(f"다음/카카오 국내 포털에서 가수 '{singer_name}' 사진 {len(daum_unique)}장 탐색 완료")

    # 국내 포털에서 30장 이상 확보되었으면 외산 검색(Bing)의 엉뚱한 건조대/마라톤 사진은 절대 섞지 않음!
    if len(daum_unique) >= target_count * 1.5:
        all_murls = daum_unique
    else:
        all_murls.extend(daum_unique)
        # 2. 다음 검색 결과가 극히 부족할 때만 보조 글로벌 검색 (Bing) 활용하되, 엄격한 해외 쇼핑몰/일어/중국어 도메인 차단
        chosen_queries = [f"가수 {singer_name}", f"{singer_name} 콘서트"]
        for query in chosen_queries:
            url_all = f"https://www.bing.com/images/search?q={quote(query)}&setlang=ko-KR&cc=KR"
            try:
                req = urllib.request.Request(url_all, headers=HEADERS)
                html = urllib.request.urlopen(req, context=SSL_CTX, timeout=7).read().decode('utf-8', errors='ignore')
                murls = re.findall(r'murl&quot;:&quot;(http[^&]+)&quot;', html)
                # 엄격한 도메인 필터: .jp, .cn, 해외 쇼핑몰, 일본 야후, 핀터레스트 무작위 등 제외
                clean_bing = []
                for u in murls:
                    u_low = u.lower()
                    if any(bad in u_low for bad in ['.jp', '.cn', 'yimg.jp', 'tokyo', 'rakuten', 'yahoo.co.jp', 'pinterest', 'shopee', 'lazada', 'amazon', 'ebay', 'aliexpress', 'cat', 'shoes', 'rack']):
                        continue
                    clean_bing.append(u)
                all_murls.extend(clean_bing)
            except Exception as e:
                logger.debug(f"Bing 검색 쿼리({url_all}) 오류: {e}")

    # 중복 제거 및 무작위 난수 셔플
    unique_murls = list(dict.fromkeys(all_murls))
    random.shuffle(unique_murls)

    # OpenCV 얼굴 검출기 준비
    face_cascade = None
    try:
        import cv2
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        if os.path.exists(cascade_path):
            face_cascade = cv2.CascadeClassifier(cascade_path)
    except Exception:
        face_cascade = None

    candidates = []
    max_candidates = max(target_count * 2, 6)
    for img_url in unique_murls:
        if len(candidates) >= max_candidates:
            break
        try:
            # URL 키워드 차단
            if any(x in img_url.lower() for x in BLOCKED_KEYWORDS + ['starnews', 'symbol', 'ci_']):
                continue

            img_req = urllib.request.Request(img_url, headers=HEADERS)
            data = urllib.request.urlopen(img_req, context=SSL_CTX, timeout=6).read()

            # 유효성 검사 (최소 480x400 이상의 고화질 실사 사진만)
            im = Image.open(io.BytesIO(data))
            if im.width >= 480 and im.height >= 400:
                if is_logo_or_graphic(im):
                    continue
                is_tall = (im.height >= im.width)
                has_face = False
                face_count = 0
                if face_cascade is not None:
                    try:
                        import numpy as np
                        im_np = np.array(im.convert("RGB"))
                        gray = cv2.cvtColor(im_np, cv2.COLOR_RGB2GRAY)
                        # scaleFactor=1.2, minNeighbors=5로 설정하여 식물/화분/사물 오인식 100% 차단
                        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60))
                        face_count = len(faces)
                        has_face = (face_count > 0)
                    except Exception:
                        has_face = False

                # 가수 사진 우선순위 점수:
                # 1) 사람 얼굴이 확실히 나온 사진만 최우선 (세로형+얼굴: 5점, 가로형+얼굴: 4점)
                # 2) 얼굴이 없는 사진은 현장 무대/행사 사진일 수 있으므로 하위 배치 (세로: 1점, 일반: 0점)
                score = (4 if has_face else 0) + (1 if is_tall else 0)
                candidates.append((score, data))
        except Exception:
            continue

    # 최고 점수 순 정렬하되 점수 그룹 내부에서는 셔플
    score_groups = {}
    for score, data in candidates:
        score_groups.setdefault(score, []).append(data)

    sorted_candidates = []
    for s in sorted(score_groups.keys(), reverse=True):
        group_items = score_groups[s]
        random.shuffle(group_items)
        sorted_candidates.extend(group_items)

    downloaded = []
    idx = 100
    for data in sorted_candidates[:target_count]:
        try:
            while True:
                candidate_path = os.path.abspath(os.path.join(output_dir, f"singer_{idx}.jpg"))
                if not os.path.exists(candidate_path) and candidate_path not in existing_paths:
                    local_path = candidate_path
                    break
                idx += 1

            im = Image.open(io.BytesIO(data))
            im.convert("RGB").save(local_path, "JPEG", quality=95)
            downloaded.append(local_path)
            idx += 1
        except Exception as e:
            logger.debug(f"후보 이미지 저장 실패: {e}")
            continue

    return downloaded


def fetch_singer_photos(
    singer_name: str,
    target_count: int = 30,
    output_dir: str = "outputs/crawled",
    project_id: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[str]:
    """
    해당 가수의 고화질 보도/콘서트/프로필 사진을 반환합니다.
    
    [핵심 원칙: 가수 DB 우선 -> 부족/다양성 부족 시 외부 수집 -> 선별 후 저장]
    1. Media DB (media_library.db)에서 해당 가수의 기존 유효 사진을 우선 조회합니다.
    2. DB에 유효 사진이 target_count 이상 있으면 즉시 반환 (외부 크롤링 0회로 고속 처리).
    3. DB 사진이 N장 (N < target_count)이면, 부족한 missing_count = target_count - N 만큼만
       외부 Bing 검색을 통해 세로형/얼굴인식 고화질 사진을 수집하여 결합합니다.
    4. DB 조회가 실패하거나 비어있으면 100% 외부 크롤링으로 안전하게 폴백합니다.
    """
    db_photos: List[str] = []

    # 1. 가수 DB 우선 조회
    try:
        from engine.media_db import query_singer_photos
        raw_db_photos = query_singer_photos(
            singer_name=singer_name,
            limit=target_count,
            exclude_recent_project_id=project_id,
            db_path=db_path
        )
        if raw_db_photos:
            for p in raw_db_photos:
                norm_p = os.path.abspath(os.path.normpath(p))
                if os.path.isfile(norm_p):
                    db_photos.append(norm_p)
            logger.info(f"Media DB returned {len(db_photos)} existing photos for singer '{singer_name}'.")
    except Exception as e:
        logger.warning(f"Media DB lookup failed for singer '{singer_name}' ({e}). Seamlessly falling back to external crawl.")
        db_photos = []

    # 2. DB 사진이 충분한 경우 즉시 반환
    if len(db_photos) >= target_count:
        logger.info(f"Media DB fulfilled {len(db_photos[:target_count])}/{target_count} photos for '{singer_name}'.")
        return db_photos[:target_count]

    # 3. 부족 수량(missing_count) 계산
    missing_count = target_count - len(db_photos)
    logger.info(f"DB provided {len(db_photos)}/{target_count} photos for '{singer_name}'. Scraping missing {missing_count} photos from Bing...")

    # 4. 부족한 수량만큼만 외부 고화질 수집
    scraped_photos: List[str] = []
    try:
        scraped_photos = _crawl_external_singer_photos(
            singer_name=singer_name,
            target_count=missing_count,
            output_dir=output_dir,
            existing_paths=set(db_photos)
        )
    except Exception as e:
        logger.error(f"External crawling failed for '{singer_name}': {e}")
        scraped_photos = []

    # 5. DB 사진(우선) + 신규 수집 사진 결합
    combined = list(db_photos)
    for p in scraped_photos:
        if p not in combined:
            combined.append(p)

    return combined


def save_curated_photos(
    singer_name: str,
    approved_photos: List[str],
    project_id: Optional[str] = None,
    source: str = "curated",
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    사용자가 최종 선별(검토/삭제 후 생존)한 사진들만 영구 Media DB에 등록 축적합니다.
    
    Args:
        singer_name: 가수 이름 (예: '임영웅', '박서진')
        approved_photos: 사용자가 삭제하지 않고 최종 선별/승인한 사진 파일 경로 리스트
        project_id: 선택적 프로젝트 고유 ID (전달 시 project_media 기록 및 사용 횟수 갱신)
        source: 미디어 출처 태그 (기본값: 'curated')
        db_path: 데이터베이스 파일 경로 (기본: media_library.db)
        
    Returns:
        List[Dict[str, Any]]: media_db에 등록/갱신된 미디어 레코드 딕셔너리 리스트
    """
    if not approved_photos:
        logger.info(f"No approved photos provided for singer '{singer_name}'.")
        return []

    registered_records = []
    valid_paths = []

    try:
        from engine.media_db import register_media, record_project_usage

        for photo_path in approved_photos:
            if not photo_path:
                continue
            abs_path = os.path.abspath(os.path.normpath(photo_path))
            if not os.path.isfile(abs_path):
                logger.warning(f"Curated photo not found on disk, skipping: {abs_path}")
                continue

            try:
                # SHA-256 해시 중복 검사를 거쳐 영구 등록 (기존 사진이면 duplicate=True로 반환)
                rec = register_media(
                    file_path=abs_path,
                    singer_name=singer_name,
                    media_type="photo",
                    subtype="singer_photo",
                    source=source,
                    tags=[singer_name, "curated", "photo"],
                    db_path=db_path
                )
                registered_records.append(rec)
                valid_paths.append(abs_path)
            except Exception as e:
                logger.error(f"Failed to register curated photo '{abs_path}': {e}")

        # 프로젝트 ID가 지정된 경우 프로젝트 이력 및 사용 횟수 기록
        if project_id and valid_paths:
            try:
                record_project_usage(
                    project_id=project_id,
                    singer_name=singer_name,
                    used_media_paths=valid_paths,
                    db_path=db_path
                )
            except Exception as e:
                logger.warning(f"Failed to record project usage for project '{project_id}': {e}")

        logger.info(f"Successfully registered/updated {len(registered_records)} curated photos for '{singer_name}'.")
    except Exception as e:
        logger.error(f"Error accessing media_db in save_curated_photos: {e}")

    return registered_records
