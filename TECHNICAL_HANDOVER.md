# 🏆 트롯 쇼츠 & 블로그 자동화 생성 시스템 종합 기술 인수인계 문서 (Technical Specification)

본 문서는 본 프로젝트의 모든 시스템 아키텍처, 핵심 엔진별 내부 로직, 프롬프트 엔지니어링 명세, 데이터베이스 스키마, FFmpeg 렌더링 파이프라인, 그리고 최근 해결된 트러블슈팅 이슈까지 포함하여, **다른 AI 에이전트나 개발자가 즉시 프로젝트를 이어받아 유지보수 및 추가 개발을 진행할 수 있도록 작성된 완전한 인수인계 문서**입니다.

---

## 1. 프로젝트 개요 & 비즈니스 핵심 요구사항

- **목적**: 네이버/언론사의 한국 트로트 스타 관련 최신 보도기사 URL을 입력받아,
  1. **5070 시니어 여성 팬덤**이 열광하는 **60초 고몰입 유튜브 쇼츠(Shorts) 영상(MP4)** 자동 제작
  2. 네이버 트로트 1등 블로그 체류시간 극대화 포맷의 **2,400자 4단 블로그 원고** 자동 생성
- **벤치마크 채널**: 유튜브 채널 `영웅대학`, `서진대학`의 스토리텔링 공식 및 자막/영상 편집 문법
- **핵심 기술 스택**:
  - **언어/런타임**: Python 3.14 (Windows OS 환경)
  - **프론트엔드/UI**: Streamlit (포트 `8501`)
  - **LLM 엔진**: Google Gemini (`gemini-3.6-flash`, `gemini-3.8-flash`, `gemini-3.5-flash`, `gemini-flash-latest`) / OpenAI (`gpt-4o-mini`) / 로컬 내장 템플릿 폴백
  - **음성 합성(TTS)**: Microsoft `Edge-TTS` (`ko-KR-SunHiNeural`, `ko-KR-InJoonNeural`)
  - **영상 처리**: `imageio-ffmpeg` (FFmpeg CLI 기반 복합 필터 그래프), `OpenCV` (Haar Cascade 얼굴 인식 크롭 및 필터), `Pillow`
  - **데이터베이스**: SQLite 3 (`media_library.db`)
  - **외부 B-roll API**: Pexels Video Search API (무료 플랜 200 req/hr)

---

## 2. 전체 디렉토리 구조 & 파일 맵

```text
c:\Users\user\Desktop\프로그램\tro\
├── app.py                             # Streamlit 메인 대시보드 UI (탭1: 쇼츠 스튜디오, 탭2: 블로그, 탭3: 무대짤)
├── media_library.db                   # 가수 사진/B-roll/API 캐시/프로젝트 이력/QA 결과 통합 SQLite DB
├── run.bat                            # 1클릭 실행 배치 스크립트 (가상환경 활성화 및 Streamlit 실행)
├── .env                               # GEMINI_API_KEY, PEXELS_API_KEY 등 환경변수
│
├── crawler/                           # [크롤링 & 기사/이미지 수집 계층]
│   ├── __init__.py
│   ├── news_parser.py                 # EUC-KR/CP949/UTF-8 자동감지 뉴스 파서 & 44인 가수 탐지기
│   └── image_enricher.py              # 국내 Daum/Kakao 포털 1순위 고화질 실사 수집 & OpenCV 얼굴인식
│
├── engine/                            # [핵심 엔진 계층]
│   ├── __init__.py
│   ├── ai_generator.py                # Gemini 1-Shot 3중 동시 생성 엔진 (쇼츠대본 + 썸네일5종 + 블로그)
│   ├── media_db.py                    # SQLite 기반 미디어 라이브러리 (해시 중복방지, B-roll 재사용, 쿼리)
│   ├── scene_analyzer.py              # 0ms 키워드 사전 기반 문맥 분석기 (B-roll 카테고리/태그 추천)
│   ├── broll_engine.py                # B-roll 4계층 수집 파이프라인 (로컬DB -> API캐시 -> Pexels API -> 다운로드)
│   ├── tts_engine.py                  # Edge-TTS 음성 합성 및 자막 싱크 계산
│   ├── thumbnail_drawer.py            # 고대비 옐로우/시안 2줄 썸네일 생성기
│   ├── clip_manager.py                # 가수별 4초 무대 짤 보관 및 유튜브 다운로드/슬라이싱
│   ├── video_renderer.py              # 2.8s Ken Burns + 무대짤/B-roll 결합 + ASS 1줄 자막 렌더러
│   └── qa/                            # [독립 품질검증 QA 계층 - 100점 만점 체계]
│       ├── __init__.py
│       ├── technical_validator.py     # QA-1 기술 규격 검증 (20점): 1080x1920, 30fps, 음성/자막 싱크
│       ├── factual_validator.py       # QA-2 사실성 검증 (30점): 기사 본문 vs 대본 숫자/고유명사 대조
│       ├── repetition_validator.py    # QA-3 반복성 검증 (25점): SHA-256 해시 사진/클립 돌려막기 방지
│       ├── frame_extractor.py         # QA-4용 5개 대표 프레임 추출기 (0.5s, 15s, 30s, 45s, 종료1초전)
│       ├── ai_reviewer.py             # QA-4 AI 멀티모달 심층 비평 (25점): Gemini 비전 기반 결함 검수
│       └── qa_aggregator.py           # 4대 검증 종합 채점기 (PASS/WARNING/FAIL 판정 및 DB 저장)
│
├── assets/                            # [정적 및 캐시 미디어 에셋]
│   ├── singers/{가수명}/clips/        # 가수별 4초 무대 짤 MP4
│   ├── general_broll/{category}/      # B-roll 표준 카테고리별 정규화(1080x1920 30fps) 영상
│   └── fonts/                         # 나눔스퀘어라운드 등 고대비 썸네일/자막용 한글 폰트
└── outputs/                           # [최종 산출물]
    ├── crawled/                       # 크롤링된 기사 보도사진 및 고화질 실사 (singer_100.jpg 등)
    ├── thumbnails/                    # 생성된 고대비 썸네일
    ├── audio/                         # TTS 나레이션 음성 파일 (MP3)
    └── videos/                        # 최종 렌더링된 쇼츠 영상 (shorts_final.mp4)
```

---

## 3. 핵심 모듈별 상세 아키텍처 및 내부 로직

### 3.1 크롤러 계층 (`crawler/`)

#### 1) `crawler/news_parser.py`
- **인코딩 자동 감지**: 국내 지방지 및 연예 언론사(newsen.com, jnilbo.com 등)의 `EUC-KR`, `CP949` 한글 깨짐을 원천 방지하기 위해 `charset-normalizer` 및 `chardet` 기반 자동 감지 후 UTF-8로 변환.
- **가수 감지 시스템**:
  - `known_singers` 리스트에 **주요 트로트 스타 44명 전수 등록** (`임영웅`, `박서진`, `김용빈`, `이찬원`, `박지현`, `영탁`, `송가인`, `양지은`, `전유진`, `홍지윤`, `진해성`, `정동원` 등).
  - 1순위: 기사 제목 매칭 ➡️ 2순위: 본문 상단 500자 매칭 ➡️ 3순위: 본문 전체 매칭 ➡️ 4순위: `가수 [이름]` 또는 `[이름] 가수` 정규식 동적 추출.
- **이미지 수집 트리거**: 가수가 정상 판별되면 `image_enricher.fetch_singer_photos(singer_name, target_count=30)`을 호출하여 30장의 후보 사진을 확보.

#### 2) `crawler/image_enricher.py`
- **가수 DB 우선 조회**: `engine.media_db.query_singer_photos(singer_name)`를 1순위로 조회하여 기존에 사용자가 승인한 사진이 있으면 우선 배정 (`DB 재사용`).
- **부족 수량만 외부 수집**:
  - **국내 포털 전수 탐색 (다음/카카오)**: `가수 {singer}`, `{singer} 콘서트`, `{singer} 무대`, `{singer} 화보`, `{singer} 행사`, `{singer} 고화질` 6개 쿼리로 다음 이미지 검색 스크랩.
  - **Bing 스팸 차단**: 다음/카카오에서 30장 이상 확보 시 외산 Bing의 엉뚱한 해외 쇼핑몰/마라톤/외국 사진은 단 1장도 섞이지 않도록 차단.
- **OpenCV 얼굴 인식 정밀 필터 (`scaleFactor=1.2`, `minNeighbors=5`)**:
  - 식물/사물 오인식을 차단하고, 진짜 사람 얼굴이 있는 사진에 최고점(세로+얼굴: 5점)을 부여하여 상위 배치.

---

### 3.2 AI 생성 계층 (`engine/ai_generator.py`)

- **1-Shot 통합 생성**: 쇼츠 나레이션 대본 + 5종 썸네일 카피 + 4단 블로그 원고를 단 한 번의 LLM 호출로 생성 (지연시간 최소화 및 문맥 일관성 보장).
- **프롬프트 템플릿**:
```text
당신은 수백만 조회수를 기록하는 유튜브 트로트 전문 채널('영웅대학', '서진대학')의 메인 스토리텔러 작가이자 네이버 1등 트로트 전문 블로그 '트롯매거진'의 수석 에디터입니다.
제공된 트로트 뉴스 기사를 분석하여 5070 시니어 여성 팬덤이 열광하는 (1) 60초 쇼츠 대본, (2) 2줄 썸네일 카피 5종, (3) 2,400자 4단 블로그 원고를 아래 JSON 형식으로 한 번에 생성하세요.

[필수 JSON 규격]
{
  "shorts_script": "50~60초 분량의 나레이션 대본 (한글 공백포함 400~500자). 0~5초 오프닝 3초 후킹(정답을 미리 말하지 않고 결론 은닉형 질문으로 시작) -> 가수의 평소 인품/미담 빌드업 -> 본론 사건과 네티즌들의 감동 댓글/전문가 평가 인용 -> 훈훈한 감동 마무리. 특수기호나 효과음 지문 없이 성우가 바로 읽을 나레이션 본문만 작성할 것.",
  "thumbnails": [
    {"line1": "윗줄 카피 1", "line2": "아랫줄 카피 1!!"}, ...
  ],
  "blog_post": "트롯매거진 공식 4단 블로그 원고 (제목, [사진 1] 반가움 도입부 + 질문1, [사진 2] 현장 디테일 묘사 + 질문2, [사진 3] 팬덤 반응 및 업계 인정 + 질문3, [사진 4] 훈훈한 행보 응원 + 질문4, 하단 📌 더 재밌는 영상 클릭 링크 3개 및 #해시태그 10개 포함, 2,000자 이상)"
}
```

---

### 3.3 스마트 B-roll 파이프라인 (`engine/scene_analyzer.py` & `engine/broll_engine.py`)

1. **Scene Analyzer (`engine/scene_analyzer.py`)**:
   - **0초 지연시간, 0원 비용**: LLM을 다시 부르지 않고 Python Dictionary 기반 키워드/유의어 규칙 매칭으로 0.1ms 내 대본의 감정선 분석.
   - 7대 지원 카테고리: `audience`(환호/팬덤), `emotion`(눈물/감동), `hospital`(치료/건강), `money`(기부/수익/상금), `smartphone`(차트/음원/유튜브/투표), `concert`(무대/공연/열창), `business`(계약/광고/트로피).
2. **B-roll Engine (`engine/broll_engine.py`)**:
   - 4계층 캐스케이드:
     1. 로컬 SQLite DB (`media_library.db`)에서 기보유한 동일 카테고리 영상 확인.
     2. API Cache 테이블 확인.
     3. Pexels API (`orientation=portrait`)에서 최적의 9:16 HD 세로 영상 1건만 다운로드.
     4. FFmpeg 정규화 (`1080x1920`, `30fps`, 무음 `-an`) 후 `assets/general_broll/{category}/`에 영구 보관 및 DB 등록.

---

### 3.4 비디오 렌더링 파이프라인 (`engine/video_renderer.py`)

- **절대 사수 원칙**:
  1. **사진 1장당 2.8초 고정 (Ken Burns 효과)**: 줌인, 줌아웃, 상하 패닝, 좌우 패닝 5종 모션 랜덤 순환.
  2. **OpenCV 스마트 중심 크롭 (`create_face_aware_base_image`)**: 원본이 가로/정방형이어도 가수 얼굴과 상반신을 9:16 화면 정중앙에 완벽 고정.
  3. **가수 무대 짤(4초 MP4) 2개 교차 배치**: 사진 중간(예: 15초 지점, 45초 지점)에 무음 무대 짤 삽입.
  4. **스마트 B-roll 1개 결합**: 대본 중간(30~40초 지점)에 문맥 일치 B-roll 영상 삽입.
  5. **1줄 볼드 자막 (ASS format)**:
     - 2줄 쌓임 없이 화면 하단 1줄만 표시 (`FontSize=16`, `Bold=1`, `Outline=3`).
     - 기본 색상: 5070 시니어 최적화 고대비 옐로우(`#FFF000`).

---

### 3.5 품질 검증 QA 시스템 (`engine/qa/` - 100점 만점)

| 공정 | 모듈명 | 배점 | 검증 항목 및 기준 | 감점/탈락 조건 |
| :--- | :--- | :---: | :--- | :--- |
| **QA-1** | `technical_validator.py` | **20점** | MP4 파일 무결성, 1080x1920(9:16), 30fps, 오디오 스트림 유무, 자막-오디오 싱크 오차(<=2.5s), 1줄 자막 규격 | 파일 손상 시 즉시 FAIL (0점), 규격 미달 시 항목별 감점 |
| **QA-2** | `factual_validator.py` | **30점** | 기사 원문 대조: 가수 이름 일치, 수치(만/억/회/위/날짜) 왜곡/환각 여부, 악성 어그로 단어 필터, 쇼츠(400~500자) 및 블로그(2,400자±10%) 분량 엄수 | 날조된 숫자 발생 시 -10점, 가수 불일치 시 -8점, 분량 미달 감점 |
| **QA-3** | `repetition_validator.py` | **25점** | SQLite 기반 최근 5개 프로젝트 대조: SHA-256 + **dHash(Difference Hash, 거리<=5)** 유사 사진 중복도, 동일 B-roll 연속 사용 여부, 첫 문장 유사도 | 사진 50% 이상 중복 시 -10점, 유사 변형 사진 감지 시 감점, B-roll 재탕 시 -5점 |
| **QA-4** | `ai_reviewer.py` | **25점** | **스마트 프레임 추출(전환점/클립경계 8~10장)** 후 Gemini 멀티모달 비전으로 대본-화면 싱크 및 완성도 비평 | 비전 결함(얼굴 잘림, 왜곡) 발생 시 감점, **API 실패 시 점수 퍼주기(22점) 원천 차단 (`AI_QA_NOT_RUN` 상태 및 WARNING 강제)** |

- **종합 판정 기준**:
  - 🟢 **PASS (90점 이상)**: 유튜브 즉시 업로드 강력 추천
  - 🟡 **WARNING (70점 ~ 89점, 또는 AI 미실행 시)**: 업로드 가능하나 세부 리포트 확인 권장
  - 🔴 **FAIL (70점 미만 또는 치명적 오류)**: 재작업/수정 권장

- **구조화된 결함(Issues) 표준 스키마 (향후 Auto-Repair 대비)**:
  모든 검증기 및 AI 리뷰어는 감점 발생 시 다음 8개 메타데이터를 통일하여 반환합니다:
  - `issue_type` (e.g. `caption_overflow`, `number_discrepancy`, `photo_repetition`, `scene_mismatch`)
  - `severity` (`high` | `medium` | `low`)
  - `scene_index` (int or null)
  - `start_time` / `end_time` (float or null)
  - `evidence` (구체적 적발 근거 텍스트)
  - `repairable` (bool - 자동 회귀 수리 가능 여부)
  - `repair_action` (e.g. `caption_resize`, `replace_photo`, `rephrase_script`)

---

## 4. 데이터베이스 스키마 (`media_library.db`)

```sql
-- 1. 등록 가수 정보
CREATE TABLE singers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    aliases TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 미디어 라이브러리 (사진, B-roll, 무대짤)
CREATE TABLE media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    singer_id INTEGER,
    media_type TEXT NOT NULL,         -- 'photo', 'broll', 'stage_clip'
    subtype TEXT,                     -- 'singer_photo', 'general_broll'
    file_path TEXT UNIQUE NOT NULL,
    file_hash TEXT UNIQUE NOT NULL,   -- SHA-256 중복 차단용
    dhash TEXT,                       -- 64비트 Difference Hash (유사 이미지 감지용)
    source TEXT,                      -- 'daum', 'pexels', 'curated'
    source_url TEXT,
    tags TEXT,
    description TEXT,
    favorite INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    FOREIGN KEY(singer_id) REFERENCES singers(id)
);

-- 3. 외부 API 응답 캐시 (Pexels 중복 호출 방지)
CREATE TABLE api_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,           -- 'pexels'
    query TEXT NOT NULL,
    media_type TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

-- 4. 제작 프로젝트 히스토리
CREATE TABLE project_history (
    id TEXT PRIMARY KEY,              -- 'proj_YYYYMMDD_HHMMSS'
    singer_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. 프로젝트별 미디어 매핑 (중복 돌려막기 추적)
CREATE TABLE project_media (
    project_id TEXT,
    media_id INTEGER,
    scene_index INTEGER,
    role TEXT,
    PRIMARY KEY(project_id, media_id),
    FOREIGN KEY(project_id) REFERENCES project_history(id),
    FOREIGN KEY(media_id) REFERENCES media(id)
);

-- 6. 품질검증 QA 결과 저장
CREATE TABLE qa_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    video_path TEXT,
    total_score REAL,
    status TEXT,                      -- 'PASS', 'WARNING', 'FAIL', 'NOT_RUN'
    technical_score REAL,
    factual_score REAL,
    repetition_score REAL,
    ai_review_score REAL,             -- 또는 content_quality_score
    issues_json TEXT,
    recommendations_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. 자주 발생하는 이슈 및 트러블슈팅 가이드

| 증상 | 발생 원인 | 해결책 |
| :--- | :--- | :--- |
| **사진이 1장만 나오고 30장이 안 뜸** | 기사에서 가수명을 감지하지 못해 `트로트 스타`로 폴백된 경우 | `crawler/news_parser.py`의 `known_singers`에 신규 가수 이름을 등록하거나 동적 정규식 패턴을 점검합니다. |
| **송가인 기사에서 빨래건조대 등 엉뚱한 사진 노출** | 외산 Bing 이미지 검색이 한국어 동음이의어를 해외 상품으로 오인식 | `crawler/image_enricher.py`에서 다음/카카오 포털 이미지를 1순위로 채우고, 30장 확보 시 Bing 검색을 섞지 않도록 설정되어 있는지 확인합니다. |
| **코드 수정 후 브라우저에 즉시 반영이 안 됨** | 백그라운드에 구형 Streamlit / Python 프로세스가 계속 살아있는 경우 | 터미널에서 `powershell -Command "Stop-Process -Name python -Force"`를 실행한 후 `run.bat` 또는 `streamlit run app.py`로 재시작합니다. |
| **B-roll이 삽입되지 않고 무대짤만 나옴** | UI에서 `스마트 B-roll 삽입` 모드가 '사용 안 함'으로 선택되었거나 Pexels API 키가 만료된 경우 | 사이드바에 Pexels API 키를 입력하거나, 라디오 버튼에서 `💡 추천 B-roll 1개 자동 결합`을 선택합니다. |
| **뉴스 사이트 인코딩 깨짐 (뷱? 꿱?)** | 특정 언론사가 EUC-KR / CP949를 사용함 | `crawler/news_parser.py` 상단의 자동 인코딩 판별 디코딩 로직을 통과하도록 보장합니다. |

---

## 6. 다음 에이전트를 위한 개발 로드맵 (Next Steps)

1. **QA 자동 회귀(Auto-Correction) 루프 추가**:
   - 현재 QA 시스템은 점수 및 문제점 '진단 리포트'만 제공하고 있음.
   - 향후 `status == 'FAIL'`인 경우, 자막 싱크 재조정, 중복 사진 자동 교체, 또는 LLM 환각 문장 자동 재수정을 거쳐 **자동 재렌더링하는 자체 회귀 파이프라인**을 연동할 수 있습니다.
2. **가수별 유튜브 짤 자동 수집기 확장**:
   - `engine/clip_manager.py`에 YouTube Data API v3를 연동하여 가수의 최근 무대 영상을 자동으로 1~2개 긁어와 4초 짤로 자동 슬라이싱해두는 크론잡(Cron) 구축 권장.
3. **Pexels 외 Pixabay/Coverr 등 보조 B-roll Provider 추가**:
   - `engine/broll_engine.py`에 Pixabay 비디오 API 폴백을 추가하여 Pexels Rate Limit 발생 시 대비.
