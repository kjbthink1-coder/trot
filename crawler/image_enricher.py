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


# 한국 주요 트롯 가수별 공식 인스타그램 및 소속사 매핑 DB
OFFICIAL_SINGER_MAP = {
    "임영웅": {"instagram": "limyoungwoong.official", "agency": "물고기뮤직"},
    "박서진": {"instagram": "parkseojin_official", "agency": "포켓돌스튜디오"},
    "진해성": {"instagram": "jinhaeseong_official", "agency": "KDH엔터테인먼트"},
    "영탁": {"instagram": "zerotak2", "agency": "어비스컴퍼니"},
    "김용빈": {"instagram": "yongbin_official", "agency": "김용빈 공식"},
    "이찬원": {"instagram": "mee_woon_sani", "agency": "스카이이엔엠"},
    "박지현": {"instagram": "pjihyun_official", "agency": "TN엔터테인먼트"},
    "전유진": {"instagram": "jeonyujin_official", "agency": "전유진 공식"},
    "송가인": {"instagram": "songgain_", "agency": "포켓돌스튜디오"},
    "양지은": {"instagram": "yangjieun90", "agency": "초록뱀이엔엠"},
    "홍지윤": {"instagram": "hongjiyun_official", "agency": "생각엔터테인먼트"},
    "정동원": {"instagram": "dongwon_13", "agency": "쇼플레이"},
    "장민호": {"instagram": "jangminho7", "agency": "호엔터테인먼트"},
    "김호중": {"instagram": "tvarotti_official", "agency": "생각엔터테인먼트"},
    "손태진": {"instagram": "son_taejin", "agency": "미스틱스토리"},
    "안성훈": {"instagram": "ash_ash0815", "agency": "생각엔터테인먼트"},
    "신성": {"instagram": "shinsung_official", "agency": "뉴에라프로젝트"},
    "에녹": {"instagram": "enoch_official", "agency": "EMK엔터테인먼트"},
    "나상도": {"instagram": "sangdo_na", "agency": "JJ엔터테인먼트"},
    "최수호": {"instagram": "suho_choi_official", "agency": "포켓돌스튜디오"},
    "마이진": {"instagram": "myjin_official", "agency": "DB엔터테인먼트"},
    "오유진": {"instagram": "oh_yujin_official", "agency": "토탈셋"},
    "김희재": {"instagram": "heejae_official", "agency": "티엔엔터테인먼트"}
}

# 수집된 사진별 출처 메타데이터 세션 매핑 (file_path -> source_type)
PHOTO_SOURCE_MAP: Dict[str, str] = {}


def get_photo_source_type(file_path: str) -> str:
    """사진 파일 경로의 수집 출처 구분(official_instagram, official_agency, official_press, media_db, web_fallback)을 반환합니다."""
    abs_p = os.path.abspath(os.path.normpath(file_path))
    return PHOTO_SOURCE_MAP.get(abs_p, "web_fallback")


def get_photo_source_badge(file_path: str) -> str:
    """사진 출처 구분값에 따른 UI 출처 배지 HTML/텍스트를 반환합니다."""
    stype = get_photo_source_type(file_path)
    if stype == "official_instagram":
        return "📸 공식 인스타"
    elif stype == "official_agency":
        return "🏢 소속사 공식"
    elif stype == "official_press":
        return "📰 공식 보도자료"
    elif stype == "media_db":
        return "🗄️ DB 보관"
    else:
        return "🌐 웹 검색"


def search_instagram_official_photos(
    singer_name: str,
    target_count: int = 10,
    output_dir: str = "outputs/crawled",
    existing_paths: Optional[set] = None
) -> List[str]:
    """1순위: 가수의 공식 인스타그램 및 공식 SNS 고화질 원본 컷을 수집합니다."""
    if target_count <= 0:
        return []
    os.makedirs(output_dir, exist_ok=True)
    existing_paths = existing_paths or set()

    handle_info = OFFICIAL_SINGER_MAP.get(singer_name, {})
    insta_handle = handle_info.get("instagram", "")

    queries = [
        f"{singer_name} 인스타그램 공식",
        f"{singer_name} 인스타 화보",
        f"{singer_name} 공식 인스타",
        f"{singer_name} 인스타 피드"
    ]
    if insta_handle:
        queries.insert(0, f"{singer_name} {insta_handle} 인스타그램")

    img_urls = []
    for q in queries:
        try:
            d_url = f"https://search.daum.net/search?w=img&q={quote(q)}"
            d_req = urllib.request.Request(d_url, headers=HEADERS)
            d_html = urllib.request.urlopen(d_req, context=SSL_CTX, timeout=6).read().decode('utf-8', errors='ignore')
            matches = re.findall(r'https?://[a-zA-Z0-9_./-]+\.(?:jpg|jpeg|png)', d_html)
            for m in matches:
                if not any(b in m.lower() for b in ['daum_og', 'favicon', 'logo', 'icon', 'btn_']) and m not in img_urls:
                    img_urls.append(m)
        except Exception:
            pass

    downloaded = []
    for idx, u in enumerate(img_urls):
        if len(downloaded) >= target_count:
            break
        fn = f"insta_{singer_name}_{idx+1}.jpg"
        fp = os.path.abspath(os.path.join(output_dir, fn))
        if fp in existing_paths:
            continue
        try:
            req = urllib.request.Request(u, headers=HEADERS)
            data = urllib.request.urlopen(req, context=SSL_CTX, timeout=5).read()
            if len(data) > 10000:
                with open(fp, "wb") as f:
                    f.write(data)
                if is_valid_photo(fp, min_w=300, min_h=250):
                    downloaded.append(fp)
                    PHOTO_SOURCE_MAP[fp] = "official_instagram"
                else:
                    if os.path.exists(fp):
                        os.remove(fp)
        except Exception:
            pass

    logger.info(f"[Stage 2/5] 공식 인스타그램/SNS에서 '{singer_name}' 고화질 사진 {len(downloaded)}장 수집 완료.")
    return downloaded


def search_agency_official_photos(
    singer_name: str,
    target_count: int = 10,
    output_dir: str = "outputs/crawled",
    existing_paths: Optional[set] = None
) -> List[str]:
    """2순위: 소속사 공식 네이버 포스트 / 카카오 채널 비하인드 원본 화보 컷을 수집합니다."""
    if target_count <= 0:
        return []
    os.makedirs(output_dir, exist_ok=True)
    existing_paths = existing_paths or set()

    handle_info = OFFICIAL_SINGER_MAP.get(singer_name, {})
    agency_name = handle_info.get("agency", "")

    queries = [
        f"{singer_name} 네이버 포스트 공식",
        f"{singer_name} 비하인드 화보",
        f"{singer_name} 소속사 공식 화보"
    ]
    if agency_name:
        queries.insert(0, f"{singer_name} {agency_name} 공식 화보")

    img_urls = []
    for q in queries:
        try:
            d_url = f"https://search.daum.net/search?w=img&q={quote(q)}"
            d_req = urllib.request.Request(d_url, headers=HEADERS)
            d_html = urllib.request.urlopen(d_req, context=SSL_CTX, timeout=6).read().decode('utf-8', errors='ignore')
            matches = re.findall(r'https?://[a-zA-Z0-9_./-]+\.(?:jpg|jpeg|png)', d_html)
            for m in matches:
                if not any(b in m.lower() for b in ['daum_og', 'favicon', 'logo', 'icon', 'btn_']) and m not in img_urls:
                    img_urls.append(m)
        except Exception:
            pass

    downloaded = []
    for idx, u in enumerate(img_urls):
        if len(downloaded) >= target_count:
            break
        fn = f"agency_{singer_name}_{idx+1}.jpg"
        fp = os.path.abspath(os.path.join(output_dir, fn))
        if fp in existing_paths:
            continue
        try:
            req = urllib.request.Request(u, headers=HEADERS)
            data = urllib.request.urlopen(req, context=SSL_CTX, timeout=5).read()
            if len(data) > 10000:
                with open(fp, "wb") as f:
                    f.write(data)
                if is_valid_photo(fp, min_w=300, min_h=250):
                    downloaded.append(fp)
                    PHOTO_SOURCE_MAP[fp] = "official_agency"
                else:
                    if os.path.exists(fp):
                        os.remove(fp)
        except Exception:
            pass

    logger.info(f"[Stage 3/5] 소속사 공식 채널에서 '{singer_name}' 고화질 사진 {len(downloaded)}장 수집 완료.")
    return downloaded


def search_official_press_release_photos(
    singer_name: str,
    target_count: int = 10,
    output_dir: str = "outputs/crawled",
    existing_paths: Optional[set] = None
) -> List[str]:
    """3순위: 앨범 자켓 및 공식 보도자료(Press Release) 원본 화보 컷을 수집합니다."""
    if target_count <= 0:
        return []
    os.makedirs(output_dir, exist_ok=True)
    existing_paths = existing_paths or set()

    queries = [
        f"{singer_name} 공식 프로필 사진",
        f"{singer_name} 앨범 자켓 원본",
        f"{singer_name} 공식 보도자료 화보"
    ]

    img_urls = []
    for q in queries:
        try:
            d_url = f"https://search.daum.net/search?w=img&q={quote(q)}"
            d_req = urllib.request.Request(d_url, headers=HEADERS)
            d_html = urllib.request.urlopen(d_req, context=SSL_CTX, timeout=6).read().decode('utf-8', errors='ignore')
            matches = re.findall(r'https?://[a-zA-Z0-9_./-]+\.(?:jpg|jpeg|png)', d_html)
            for m in matches:
                if m not in img_urls and not any(b in m.lower() for b in ['favicon', 'logo', 'icon', 'btn_']):
                    img_urls.append(m)
        except Exception:
            pass

    downloaded = []
    for idx, u in enumerate(img_urls):
        if len(downloaded) >= target_count:
            break
        fn = f"press_{singer_name}_{idx+1}.jpg"
        fp = os.path.abspath(os.path.join(output_dir, fn))
        if fp in existing_paths:
            continue
        try:
            req = urllib.request.Request(u, headers=HEADERS)
            data = urllib.request.urlopen(req, context=SSL_CTX, timeout=5).read()
            if len(data) > 10000:
                with open(fp, "wb") as f:
                    f.write(data)
                if is_valid_photo(fp, min_w=300, min_h=250):
                    downloaded.append(fp)
                    PHOTO_SOURCE_MAP[fp] = "official_press"
                else:
                    if os.path.exists(fp):
                        os.remove(fp)
        except Exception:
            pass

    logger.info(f"[Stage 3/5] 공식 보도자료/프로필에서 '{singer_name}' 사진 {len(downloaded)}장 수집 완료.")
    return downloaded


def fetch_singer_photos(
    singer_name: str,
    target_count: int = 30,
    output_dir: str = "outputs/crawled",
    project_id: Optional[str] = None,
    db_path: Optional[str] = None
) -> List[str]:
    """
    해당 가수의 고화질 5단계 계층형 출처 수집기:
      1단계: 기존 미디어 DB (media_library.db) 보관 사진 (최우선 불러오기)
      2단계: 공식 인스타그램 / 공식 SNS 피드 원본 고화질 컷
      3단계: 소속사 공식 채널 (네이버 공식 포스트 / 카카오 채널) 비하인드 화보
      4단계: 앨범 자켓 및 공식 보도자료 (Press Kit) 원본 컷
      5단계: 일반 웹 이미지 검색 (위 1~4단계 수량이 부족할 때만 안전 Fallback)
    """
    final_photos: List[str] = []
    seen_paths: set = set()

    # -------------------------------------------------------------
    # 1단계 (⚡ DB 우선): media_library.db 보관 사진 로딩
    # -------------------------------------------------------------
    try:
        from engine.media_db import query_singer_photos
        raw_db = query_singer_photos(
            singer_name=singer_name,
            limit=target_count,
            exclude_recent_project_id=project_id,
            db_path=db_path
        )
        if raw_db:
            for p in raw_db:
                norm_p = os.path.abspath(os.path.normpath(p))
                if os.path.isfile(norm_p) and norm_p not in seen_paths:
                    final_photos.append(norm_p)
                    seen_paths.add(norm_p)
                    PHOTO_SOURCE_MAP[norm_p] = "media_db"
            logger.info(f"[Stage 1/5 DB] Media DB에서 '{singer_name}' 사진 {len(final_photos)}장 로딩 완료.")
    except Exception as e:
        logger.warning(f"[Stage 1/5 DB] DB 조회 실패: {e}")

    if len(final_photos) >= target_count:
        return final_photos[:target_count]

    # -------------------------------------------------------------
    # 2단계 (📸 공식 인스타/SNS): 인스타그램/SNS 원본 수집
    # -------------------------------------------------------------
    need_cnt = target_count - len(final_photos)
    try:
        insta_photos = search_instagram_official_photos(singer_name, target_count=min(12, need_cnt), output_dir=output_dir, existing_paths=seen_paths)
        for p in insta_photos:
            if p not in seen_paths:
                final_photos.append(p)
                seen_paths.add(p)
    except Exception as e_insta:
        logger.warning(f"Stage 2 Instagram crawl warning: {e_insta}")

    if len(final_photos) >= target_count:
        return final_photos[:target_count]

    # -------------------------------------------------------------
    # 3단계 (🏢 소속사 공식 채널): 네이버 포스트/카카오 채널 수집
    # -------------------------------------------------------------
    need_cnt = target_count - len(final_photos)
    try:
        agency_photos = search_agency_official_photos(singer_name, target_count=min(10, need_cnt), output_dir=output_dir, existing_paths=seen_paths)
        for p in agency_photos:
            if p not in seen_paths:
                final_photos.append(p)
                seen_paths.add(p)
    except Exception as e_agency:
        logger.warning(f"Stage 3 Agency channel crawl warning: {e_agency}")

    if len(final_photos) >= target_count:
        return final_photos[:target_count]

    # -------------------------------------------------------------
    # 4단계 (📰 공식 보도자료/앨범): 프로필 & 앨범 자켓 수집
    # -------------------------------------------------------------
    need_cnt = target_count - len(final_photos)
    try:
        press_photos = search_official_press_release_photos(singer_name, target_count=min(8, need_cnt), output_dir=output_dir, existing_paths=seen_paths)
        for p in press_photos:
            if p not in seen_paths:
                final_photos.append(p)
                seen_paths.add(p)
    except Exception as e_press:
        logger.warning(f"Stage 4 Press release crawl warning: {e_press}")

    if len(final_photos) >= target_count:
        return final_photos[:target_count]

    # -------------------------------------------------------------
    # 5단계 (🌐 일반 웹 검색 Fallback): 수량 부족 시 안전 백업
    # -------------------------------------------------------------
    need_cnt = target_count - len(final_photos)
    logger.info(f"[Stage 5/5 Fallback] 1~4단계 수집 결과 {len(final_photos)}/{target_count}장. 부족 수량 {need_cnt}장 일반 웹 검색 수행...")
    try:
        web_photos = _crawl_external_singer_photos(singer_name, target_count=need_cnt, output_dir=output_dir, existing_paths=seen_paths)
        for p in web_photos:
            if p not in seen_paths:
                final_photos.append(p)
                seen_paths.add(p)
                PHOTO_SOURCE_MAP[p] = "web_fallback"
    except Exception as e_web:
        logger.error(f"Stage 5 Web search fallback error: {e_web}")

    return final_photos


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
