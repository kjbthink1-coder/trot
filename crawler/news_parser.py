import os
import re
import shutil
import urllib.request
from urllib.parse import urlparse
import ssl
from bs4 import BeautifulSoup
from crawler.image_enricher import is_valid_photo, fetch_singer_photos, save_curated_photos

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
}

SSL_CTX = ssl._create_unverified_context()

def parse_naver_news(
    url: str,
    output_dir: str = "outputs/crawled",
    project_id: str = None,
    db_path: str = None
) -> dict:
    """
    네이버 뉴스 및 국내 언론사 기사 URL을 받아
    1) 기사 제목
    2) 상단 메뉴/네비게이션이 완전히 제거된 순수 본문 텍스트
    3) 고화질 본문 사진 추출 (아이콘 및 폰트조절 버튼 필터링)
    4) 사진 부족 시 해당 가수 고화질 포토 자동 4장 보충
    을 수행하여 딕셔너리로 반환합니다.
    """
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    # 기존 다운로드 폴더 초기화 (이전 기사의 찌꺼기 방지)
    if os.path.exists(output_dir):
        for f in os.listdir(output_dir):
            try:
                fp = os.path.join(output_dir, f)
                if os.path.isfile(fp):
                    os.remove(fp)
            except Exception:
                pass
    os.makedirs(output_dir, exist_ok=True)

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        raw_bytes = urllib.request.urlopen(req, context=SSL_CTX, timeout=12).read()
    except Exception as e:
        raise ValueError(f"기사 URL 접속 실패: {e}")

    # 한국 언론사 인코딩 자동 감지 (EUC-KR / CP949 / UTF-8 완전 호환)
    html = ""
    # 1. 원시 바이트 내 meta charset 확인
    charset_match = re.search(rb'charset=["\']?([a-zA-Z0-9_-]+)', raw_bytes[:2048], re.I)
    detected_encoding = charset_match.group(1).decode('ascii', errors='ignore').lower() if charset_match else None
    
    candidate_encodings = []
    if detected_encoding:
        candidate_encodings.append(detected_encoding)
    candidate_encodings.extend(['utf-8', 'euc-kr', 'cp949'])

    for enc in candidate_encodings:
        try:
            html = raw_bytes.decode(enc)
            # 한글이 깨짐 없이 디코딩되었는지 검증 (문자열에 유효 한글 유무)
            if re.search(r'[가-힣]', html):
                break
        except Exception:
            continue

    if not html:
        html = raw_bytes.decode('utf-8', errors='replace')

    soup = BeautifulSoup(html, 'html.parser')

    # [중요] 사이트 상단/하단/사이드바 메뉴 완전 분쇄 (GNB, 바로가기, 네비게이션 제거)
    for nav_junk in soup.find_all(['header', 'nav', 'footer', 'aside', 'form']):
        nav_junk.decompose()

    for junk_class in ['gnb', 'menu', 'nav', 'header', 'footer', 'sidebar', 'banner', 'util', 'quick', 'share', 'sns']:
        for tag in soup.find_all(attrs={'class': re.compile(junk_class, re.I)}):
            tag.decompose()
        for tag in soup.find_all(attrs={'id': re.compile(junk_class, re.I)}):
            tag.decompose()

    # 1. 제목 추출
    title = ""
    title_candidates = [
        soup.find('meta', property='og:title'),
        soup.find('h2', id='title_area'),
        soup.find('h3', id='articleTitle'),
        soup.find('h3', class_='tit_view'),
        soup.find('div', class_=re.compile(r'article_tit|view_title|headline|news_title', re.I)),
        soup.find('h1'),
    ]
    for tag in title_candidates:
        if tag:
            if tag.name == 'meta':
                title = tag.get('content', '')
            else:
                title = tag.get_text(strip=True)
            if title and len(title) > 5:
                break
    
    if not title and soup.title:
        title = soup.title.get_text(strip=True)

    # 2. 본문 영역 탐색
    article_content = None
    content_selectors = [
        ('div', {'id': 'CLtag'}),                     # 뉴스엔(newsen) 등
        ('td', {'class': 'article'}),                 # 뉴스엔 및 구형 언론사 테이블
        ('article', {'id': 'dic_area'}),              # 네이버 뉴스
        ('div', {'id': 'articleBodyContents'}),        # 네이버 뉴스 구형
        ('div', {'id': 'newsct_article'}),            # 네이버 모바일
        ('div', {'id': 'articeBody'}),                # 다음/카카오
        ('div', {'class': 'article_view'}),           # 다음 뉴스
        ('div', {'id': 'article-view-content-div'}),  # 주요 일간지
        ('div', {'class': 'article-body'}),           # 일반 언론사
        ('div', {'class': 'view_cont'}),              # 스포츠서울/스포츠조선
        ('div', {'class': 'news_body'}),              # 엑스포츠뉴스
        ('div', {'id': 'news_body_area'}),
        ('div', {'class': 'view_text'}),
        ('div', {'id': 'content'})
    ]

    for tag_name, attrs in content_selectors:
        found = soup.find(tag_name, attrs)
        if found:
            article_content = found
            break

    if not article_content:
        divs = soup.find_all('div')
        best_div = None
        max_p_count = 0
        for d in divs:
            p_count = len(d.find_all('p'))
            if p_count > max_p_count:
                max_p_count = p_count
                best_div = d
        article_content = best_div if max_p_count >= 2 else soup.find('body')

    # 3. 본문 텍스트 정제
    cleaned_lines = []
    if article_content:
        for unwanted in article_content.find_all(['script', 'style', 'iframe', 'button', 'figcaption', 'em']):
            unwanted.decompose()

        for line in article_content.get_text('\n', strip=True).split('\n'):
            line = line.strip()
            if not line or len(line) < 10:
                continue
            if any(junk in line for junk in ['바로가기', '메뉴닫기', '전체서비스', '상단영역', '스타뉴스', '검색버튼', '구독자수', '로그인', '회원가입']):
                continue
            if re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', line):
                continue
            if any(k in line for k in ['무단 전재', '재배포 금지', '저작권자', '기자 =', '기자=', '기자]']):
                continue
            if line.startswith('▶') or line.startswith('※') or line.startswith('ⓒ'):
                continue
            cleaned_lines.append(line)

    clean_content = '\n\n'.join(cleaned_lines)

    # 4. 가수명 감지 (제목 및 본문 전체에서 정밀 매칭)
    detected_singer = "트로트 스타"
    known_singers = [
        "이찬원", "박서진", "임영웅", "김용빈", "박지현", "영탁", 
        "송가인", "양지은", "진해성", "진혜성", "홍지윤", "정동원", 
        "장민호", "손태진", "안성훈", "전유진", "김태연", "김다현", 
        "오유진", "마이진", "강혜연", "은가은", "나상도", "최수호", 
        "진욱", "박성온", "황민호", "황영웅", "신성", "에녹", 
        "민수현", "김희재", "남승민", "홍자", "정미애", "숙행", 
        "김소연", "배아현", "정서주", "미스김", "나훈아", "남진", 
        "장윤정", "주현미"
    ]
    
    # 1순위: 제목에서 탐색
    for singer in known_singers:
        if singer in title:
            detected_singer = singer
            break
            
    # 2순위: 본문 상단(500자)에서 탐색
    if detected_singer == "트로트 스타":
        for singer in known_singers:
            if singer in clean_content[:500]:
                detected_singer = singer
                break

    # 3순위: 본문 전체에서 탐색
    if detected_singer == "트로트 스타":
        for singer in known_singers:
            if singer in clean_content:
                detected_singer = singer
                break

    # 4순위: 동적 패턴 매칭 ('가수 OOO' 또는 'OOO 가수', 'OOO 씨')
    if detected_singer == "트로트 스타":
        m_singer = re.search(r'가수\s+([가-힣]{2,4})', title + " " + clean_content[:300])
        if m_singer:
            detected_singer = m_singer.group(1).strip()
        else:
            m_singer2 = re.search(r'([가-힣]{2,4})\s+가수', title + " " + clean_content[:300])
            if m_singer2:
                detected_singer = m_singer2.group(1).strip()

    # 5. 본문 이미지 추출 (대표 사진 위주로 최대 2장만 안전하게 추출)
    image_urls = []
    og_img = soup.find('meta', property='og:image')
    if og_img and og_img.get('content'):
        image_urls.append(og_img.get('content'))

    if article_content:
        for img in article_content.find_all('img'):
            src = img.get('data-src') or img.get('src')
            if src:
                if not src.startswith('http'):
                    parsed_root = urlparse(url)
                    src = f"{parsed_root.scheme}://{parsed_root.netloc}/{src.lstrip('/')}"
                # 광고, 쇼핑몰, 아이콘 등 엄격 차단
                if not any(x in src.lower() for x in ['icon', 'logo', 'banner', 'button', 'ad.', 'blank', 'emoticon', 'btn_', 'font', 'url', 'zoom', 'shop', 'widget']):
                    image_urls.append(src)

    # 중복 제거
    image_urls = list(dict.fromkeys(image_urls))

    article_photos = []
    idx = 1
    # 기사에서는 진짜 대표 보도사진 최대 2장만 보수적으로 추출
    for img_url in image_urls[:3]:
        try:
            ext = os.path.splitext(urlparse(img_url).path)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png']:
                ext = '.jpg'
            local_filename = os.path.join(output_dir, f"article_{idx}{ext}")
            img_req = urllib.request.Request(img_url, headers=HEADERS)
            data = urllib.request.urlopen(img_req, context=SSL_CTX, timeout=8).read()
            with open(local_filename, 'wb') as f:
                f.write(data)
            
            # 400x300 이상의 진짜 보도사진만 통과
            if is_valid_photo(local_filename, min_w=400, min_h=300):
                article_photos.append(os.path.abspath(local_filename))
                idx += 1
            else:
                if os.path.exists(local_filename):
                    os.remove(local_filename)
        except Exception:
            continue

    # [핵심] 사용자 아이디어 100% 반영:
    # 넉넉하게 30장의 고화질 사진을 수집하여 사용자가 직접 검토/선별/삭제할 수 있도록 지원
    singer_photos = []
    target_search_name = detected_singer if detected_singer != "트로트 스타" else ""
    if not target_search_name:
        # 제목에서 3글자 한국어 인명 패턴 시도
        for s in known_singers:
            if s in title or s in clean_content:
                target_search_name = s
                detected_singer = s
                break

    if target_search_name:
        try:
            singer_photos = fetch_singer_photos(
                target_search_name,
                target_count=30,
                output_dir=output_dir,
                project_id=project_id,
                db_path=db_path
            )
        except Exception as e_fetch:
            print(f"[NewsParser] 가수 사진 수집 예외: {e_fetch}")

    # [스마트 우선순위 적용]
    # 기사 원본 대표 보도사진(1장)은 사실성/시의성을 위해 [사진 1] 최우선 배치
    # 이후 세로형(9:16) 및 얼굴 인식 고화질 사진들이 순서대로 배치됨 (fetch_singer_photos 내부에서 이미 동점대별 난수 셔플 완료)
    valid_images = []
    if article_photos:
        valid_images.append(article_photos[0])
    
    for sp in singer_photos:
        if sp not in valid_images:
            valid_images.append(sp)

    if not valid_images and singer_photos:
        valid_images = singer_photos


    return {
        "url": url,
        "title": title,
        "content": clean_content,
        "images": valid_images,
        "singer": detected_singer
    }
