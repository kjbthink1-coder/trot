import streamlit as st
import os
import sys
import tempfile
import time

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crawler.news_parser import parse_naver_news
from crawler.image_enricher import fetch_singer_photos, get_photo_source_badge
from engine.ai_generator import generate_contents
from engine.tts_engine import synthesize_speech, DEFAULT_VOICE, MALE_VOICE
from engine.thumbnail_drawer import create_high_contrast_thumbnail
from engine.video_renderer import render_shorts_video
from assets.generate_stock_clips import ensure_stock_video
import random
from engine.clip_manager import (
    get_all_singers,
    get_singer_clips,
    get_singer_clip_count,
    get_random_singer_clips,
    slice_video_into_clips,
    download_youtube_and_slice,
    delete_clip
)
from engine.media_db import get_media_stats, get_db_connection, compute_file_hash, update_media_file_hash, delete_media_record
from engine.scene_analyzer import analyze_script_scenes
from engine.broll_engine import get_or_fetch_broll
from engine.qa import run_full_qa
from engine.cc_video_engine import (
    get_db_singer_cc_clips,
    search_youtube_cc_videos,
    download_raw_cc_video,
    trim_and_normalize_cc_clip,
    detect_video_face_center_percent,
    get_cc_crop_preview_frame
)
import streamlit_cropper as sc
from PIL import Image

st.set_page_config(
    page_title="AI 트로트 쇼츠 & 블로그 스튜디오",
    page_icon="🎙️",
    layout="wide"
)

# .env 파일에서 저장된 API 키 불러오기 함수
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
def load_env_key(key_name: str) -> str:
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(f"{key_name}="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get(key_name, "")

def save_env_key(key_name: str, value: str):
    existing = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    existing[k] = v
    existing[key_name] = value.strip()
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")

# ----------------- ⚙️ API 및 환경 설정 팝업 모달 -----------------
@st.dialog("⚙️ API 및 환경 설정")
def open_setting_dialog():
    st.subheader("🤖 AI LLM 엔진 설정")
    provider = st.selectbox("AI 엔진 선택", ["gemini", "openai", "내장 템플릿 (API 키 없이 즉시 생성)"])
    
    if provider == "gemini":
        saved_gemini = load_env_key("GEMINI_API_KEY")
        api_key_input = st.text_input("Gemini API Key", type="password", value=saved_gemini, help="Google AI Studio에서 발급받은 키를 입력하세요")
        
        if st.button("💾 Gemini 키 영구 저장", key="btn_save_gemini_modal"):
            if api_key_input.strip():
                save_env_key("GEMINI_API_KEY", api_key_input)
                st.success("Gemini API 키가 저장되었습니다!")
            else:
                st.warning("키를 입력해 주세요.")
        if api_key_input.strip() or saved_gemini:
            st.caption("🟢 API 키가 설정되어 있습니다.")
        else:
            st.caption("🟡 키가 없으면 내장 템플릿으로 자동 생성됩니다.")

    elif provider == "openai":
        saved_openai = load_env_key("OPENAI_API_KEY")
        api_key_input = st.text_input("OpenAI API Key", type="password", value=saved_openai)
        if st.button("💾 OpenAI 키 영구 저장", key="btn_save_openai_modal"):
            save_env_key("OPENAI_API_KEY", api_key_input)
            st.success("OpenAI API 키 저장 완료!")

    st.divider()
    st.subheader("🎬 무료 B-roll 스톡 영상 API 설정")
    saved_pexels = load_env_key("PEXELS_API_KEY")
    pexels_input = st.text_input("Pexels API Key", type="password", value=saved_pexels, help="https://www.pexels.com/api/ 에서 발급받은 무료 키")
    if st.button("💾 Pexels 키 저장", key="btn_save_pexels_modal"):
        if pexels_input.strip():
            save_env_key("PEXELS_API_KEY", pexels_input)
            st.success("Pexels API 키가 저장되었습니다!")
        else:
            st.warning("키를 입력해 주세요.")
    if pexels_input.strip() or saved_pexels:
        st.caption("🟢 고화질 9:16 B-roll 자동 다운로드 활성화됨")
    else:
        st.caption("⚪ 키 미입력 시 기저장된 로컬 DB B-roll 우선 재사용")


# ----------------- ✂️ 이미지 크롭/자르기 팝업 모달 -----------------
@st.dialog("✂️ 이미지 영역 자르기 (글씨/로고 제거)")
def open_crop_dialog(img_path: str, img_idx: int):
    st.write("마우스로 **파란색 점선 박스**를 드래그하여 불필요한 언론사 로고나 하단 글씨를 제외하고 범위를 맞추세요.")
    try:
        raw_img = Image.open(img_path)
        # st_cropper: 점선 박스 드래그 자르기 컴포넌트
        cropped_img = sc.st_cropper(
            raw_img,
            realtime_update=True,
            box_color="#00D2FF",
            aspect_ratio=None,
            key=f"cropper_widget_{img_idx}"
        )
        
        st.divider()
        col_preview, col_action = st.columns([1, 1])
        with col_preview:
            st.write("✂️ **자르기 결과 미리보기:**")
            st.image(cropped_img, use_container_width=True)
            
        with col_action:
            st.write("")
            st.write("")
            if st.button("💾 크롭 완료 및 DB 저장", type="primary", use_container_width=True, key=f"btn_save_crop_{img_idx}"):
                # 크롭된 이미지 덮어쓰기 저장
                cropped_img.save(img_path, quality=95)
                # DB 해시 갱신
                update_media_file_hash(img_path)
                st.success("이미지가 자르기 후 DB 및 파일로 저장되었습니다!")
                time.sleep(0.5)
                st.rerun()
            if st.button("❌ 닫기 / 취소", type="secondary", use_container_width=True, key=f"btn_close_crop_{img_idx}"):
                st.rerun()
    except Exception as e:
        st.error(f"이미지 로딩 중 오류 발생: {e}")

# 커스텀 CSS (상용 SaaS Slate & Indigo 디자인 시스템)
st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    * { font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif; }
    
    .main-title { font-size: 2.0rem; font-weight: 800; color: #0F172A; letter-spacing: -0.5px; margin-bottom: 0.3rem; }
    .sub-title { font-size: 1.05rem; color: #64748B; font-weight: 500; margin-bottom: 1.5rem; }
    
    /* SaaS 대시보드 카드 */
    .saas-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 1.2rem;
        box-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.04);
        margin-bottom: 1.2rem;
    }
    
    /* 대본 에디터 가독성 패치 */
    .stTextArea textarea {
        line-height: 1.68 !important;
        font-size: 0.95rem !important;
        color: #0F172A !important;
        border-radius: 10px !important;
        border: 1.5px solid #CBD5E1 !important;
        padding: 0.85rem !important;
        background-color: #F8FAFC !important;
    }
    .stTextArea textarea:focus {
        border-color: #6366F1 !important;
        box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15) !important;
    }
    
    /* 수집 이미지 바둑판 카드 정렬 */
    .gallery-box [data-testid="stImage"] img {
        height: 180px !important;
        object-fit: cover !important;
        border-radius: 10px !important;
        border: 1px solid #E2E8F0;
    }
    
    /* 버튼 인체공학적 높이 및 터치 타겟 패치 */
    .stButton>button {
        font-weight: 600 !important;
        border-radius: 8px !important;
        height: 2.45rem !important;
        font-size: 0.85rem !important;
        padding: 0 0.4rem !important;
    }
    
    /* 썸네일 미리보기 커버 (컴팩트 330px 높이 제한으로 좌우 세로 길이 밸런스 맞춤) */
    .thumb-preview-box [data-testid="stImage"] img {
        height: auto !important;
        max-height: 330px !important;
        object-fit: contain !important;
        border-radius: 12px !important;
        border: 1px solid #E2E8F0 !important;
        box-shadow: 0 6px 16px -4px rgba(15, 23, 42, 0.1) !important;
        margin: 0 auto !important;
        display: block !important;
    }

    /* 🎬 컴팩트 쇼츠 비디오 플레이어 (9:16 세로 영상 화면 거대화 방지) */
    .compact-video-box,
    div[data-testid="stVideo"] {
        max-width: 250px !important;
        max-height: 440px !important;
        margin: 0 auto !important;
    }

    .compact-video-box video,
    .compact-video-box iframe,
    div[data-testid="stVideo"] video,
    div[data-testid="stVideo"] iframe {
        max-width: 250px !important;
        max-height: 440px !important;
        width: 100% !important;
        height: auto !important;
        margin: 0 auto !important;
        display: block !important;
        border-radius: 12px !important;
        box-shadow: 0 6px 20px rgba(15, 23, 42, 0.15) !important;
    }

    .engine-badge {
        display: inline-block;
        padding: 0.4rem 0.9rem;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.88rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🎙️ AI 트로트 쇼츠 & 블로그 자동 생성 스튜디오</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">네이버 기사 링크 하나로 5070 시니어 최적화 쇼츠 영상(MP4)과 네이버 블로그 원고를 1분 만에 완성합니다.</div>', unsafe_allow_html=True)

# 🗄️ 미디어 DB 보관함 실시간 통계 배지
try:
    db_stats = get_media_stats()
    n_photos = db_stats.get("total_photos", 0)
    n_brolls = db_stats.get("total_brolls", 0)
    n_clips = db_stats.get("total_stage_clips", 0)
    n_singers = db_stats.get("total_singers", 0)
    st.markdown(
        f'<div style="display: flex; align-items: center; justify-content: space-between; background: #E8F5E9; border: 1.5px solid #81C784; border-radius: 8px; padding: 0.6rem 1.2rem; margin-bottom: 1.2rem; font-size: 0.95rem; color: #1B5E20; font-weight: 600;">'
        f'<span>🗄️ <b>미디어 보관함:</b> 가수 사진 <b>{n_photos}</b>장 &nbsp;|&nbsp; B-roll <b>{n_brolls}</b>개 &nbsp;|&nbsp; 무대 짤 <b>{n_clips}</b>개 &nbsp;|&nbsp; 등록 가수 <b>{n_singers}</b>명</span>'
        f'<span style="font-size: 0.85rem; color: #2E7D32; font-weight: normal;">⚡ 작업할수록 자동 축적되어 제작 속도가 빨라집니다</span>'
        f'</div>',
        unsafe_allow_html=True
    )
except Exception:
    pass

# ----------------- 사이드바 설정 -----------------
with st.sidebar:
    st.title("🎙️ 트롯 스튜디오")
    if st.button("⚙️ API 및 환경 설정", use_container_width=True, type="primary"):
        open_setting_dialog()
        
    provider = "gemini"
    current_key = load_env_key("GEMINI_API_KEY")
    if current_key:
        st.caption("🟢 API 키 활성화됨")
    else:
        st.caption("🟡 ⚙️ 설정에서 API 키를 저장하세요")

    st.divider()
    voice_choice = st.radio("AI 성우 목소리 선택", ["여성 성우 (선희 - 따뜻한 감동)", "남성 성우 (인준 - 묵직한 신뢰)"])
    selected_voice = DEFAULT_VOICE if "여성" in voice_choice else MALE_VOICE

    st.divider()
    st.subheader("💡 2단계 B안 빠른 링크")
    st.caption("가수별 최신 네이버 뉴스 바로가기")
    singers_quick = ["임영웅", "박서진", "김용빈", "이찬원", "박지현", "영탁", "송가인", "양지은", "전유진", "홍지윤"]
    for s in singers_quick:
        st.markdown(f"- [{s} 최신 뉴스 검색](https://search.naver.com/search.naver?where=news&query={s}&sort=1)", unsafe_allow_html=True)

    st.divider()
    st.subheader("🗄️ 미디어 DB 보관함")
    try:
        s_stats = get_media_stats()
        sb1, sb2 = st.columns(2)
        sb1.metric("가수 사진", f"{s_stats.get('total_photos', 0)}장")
        sb2.metric("B-roll 영상", f"{s_stats.get('total_brolls', 0)}개")
        sb3, sb4 = st.columns(2)
        sb3.metric("무대 짤", f"{s_stats.get('total_stage_clips', 0)}개")
        sb4.metric("등록 가수", f"{s_stats.get('total_singers', 0)}명")
    except Exception:
        st.caption("DB 통계 로딩 중...")

# 세션 상태 초기화
if "parsed_data" not in st.session_state:
    st.session_state.parsed_data = None
if "ai_result" not in st.session_state:
    st.session_state.ai_result = None
if "selected_thumb_idx" not in st.session_state:
    st.session_state.selected_thumb_idx = 0
if "selected_thumb_img_idx" not in st.session_state:
    st.session_state.selected_thumb_img_idx = 0
if "rendered_video" not in st.session_state:
    st.session_state.rendered_video = None
if "qa_result" not in st.session_state:
    st.session_state.qa_result = None

# 최상위 탭 구성: [제작 스튜디오] vs [가수 무대 짤 보관함]
main_tab_produce, main_tab_library = st.tabs(["🚀 원클릭 쇼츠 & 블로그 제작", "🎬 가수별 무대 짤(클립) 보관함"])

# =========================================================================
# TAB 1: 원클릭 쇼츠 & 블로그 제작
# =========================================================================
with main_tab_produce:
    # ----------------- 1단계: URL 입력 -----------------
    st.subheader("1️⃣ 뉴스 기사 URL 입력 (A안)")
    col_input, col_btn = st.columns([4, 1])

    with col_input:
        news_url = st.text_input("분석할 네이버/언론사 기사 링크를 붙여넣으세요", placeholder="https://n.news.naver.com/article/...")

    with col_btn:
        st.write("")
        analyze_btn = st.button("🚀 기사 분석 & AI 생성", type="primary", use_container_width=True)

    if analyze_btn:
        if not news_url.strip():
            st.error("기사 URL을 입력해 주세요!")
        else:
            # 이전 생성 결과 세션 완벽 초기화
            st.session_state.parsed_data = None
            st.session_state.ai_result = None
            st.session_state.rendered_video = None
            st.session_state.qa_result = None

            with st.spinner("기사 본문과 사진을 추출하고 AI 후킹 대본 및 블로그를 생성 중입니다..."):
                try:
                    # 1. 크롤링
                    parsed = parse_naver_news(news_url.strip())
                    parsed["images_original"] = list(parsed["images"])
                    st.session_state.parsed_data = parsed
                    
                    # 2. AI 생성
                    ai_prov = "fallback" if "내장" in provider else provider
                    ai_res = generate_contents(
                        article_title=parsed["title"],
                        article_content=parsed["content"],
                        singer_name=parsed["singer"],
                        api_key=current_key if current_key else None,
                        provider=ai_prov
                    )
                    
                    # 3. AI 문맥 분석으로 확정된 진짜 주인공 가수 교정 & 사진 재수집
                    ai_detected_singer = ai_res.get("target_singer")
                    if ai_detected_singer and ai_detected_singer != "트로트 스타" and ai_detected_singer != parsed["singer"]:
                        print(f"[SingerCorrection] 파서 감지({parsed['singer']}) -> AI 확정({ai_detected_singer}) 주인공 교정!")
                        parsed["singer"] = ai_detected_singer
                        try:
                            fresh_photos = fetch_singer_photos(ai_detected_singer, target_count=30, output_dir="outputs/crawled")
                            if fresh_photos:
                                parsed["images"] = fresh_photos
                                parsed["images_original"] = list(fresh_photos)
                        except Exception as e_refetch:
                            print(f"[PhotoReFetch] {e_refetch}")

                    st.session_state.parsed_data = parsed
                    st.session_state.ai_result = ai_res
                    st.session_state.selected_thumb_img_idx = 0
                    st.session_state.rendered_video = None
                    st.session_state.qa_result = None
                    st.success(f"[{parsed['singer']}] 기사 분석 및 고유 대본/블로그 생성 완료!")
                except Exception as e:
                    st.error(f"처리 중 오류가 발생했습니다: {e}")

    # ----------------- 2단계: 결과 확인 및 선택 -----------------
    if st.session_state.parsed_data and st.session_state.ai_result:
        parsed = st.session_state.parsed_data
        ai_res = st.session_state.ai_result
        
        st.divider()
        
        # 사용된 AI 엔진 표시
        engine_used = ai_res.get("engine_used", "AI 엔진")
        badge_color = "#E8F5E9" if "Gemini" in engine_used or "OpenAI" in engine_used else "#FFF3E0"
        text_color = "#2E7D32" if "Gemini" in engine_used or "OpenAI" in engine_used else "#E65100"
        st.markdown(
            f'<div class="engine-badge" style="background-color: {badge_color}; color: {text_color};">'
            f'🤖 실행 엔진: {engine_used} | 대상 가수: {parsed["singer"]}</div>',
            unsafe_allow_html=True
        )
        
        # 탭 구성: [쇼츠 영상 스튜디오] / [네이버 블로그 원고]
        tab_shorts, tab_blog = st.tabs(["🎬 쇼츠(Shorts) 제작 스튜디오", "📝 트롯매거진 4단 블로그 원고"])
        
        # === TAB 1: 쇼츠 제작 ===
        with tab_shorts:
            # 💳 [카드 1] 🎯 썸네일 카피 선택 & 🎨 실시간 디자인 스튜디오
            st.markdown('<div class="saas-card">', unsafe_allow_html=True)
            col_c1_left, col_c1_right = st.columns([1, 1.05])
            
            with col_c1_left:
                st.markdown("#### 🎯 썸네일 카피 선택")
                cur_thumb_idx = st.session_state.get("selected_thumb_idx", 0)
                if cur_thumb_idx >= len(ai_res["thumbnails"]):
                    cur_thumb_idx = 0
                    st.session_state.selected_thumb_idx = 0

                for idx, item in enumerate(ai_res["thumbnails"]):
                    is_card_sel = (idx == cur_thumb_idx)
                    card_border = "#6366F1" if is_card_sel else "#E2E8F0"
                    card_bg = "#EEF2FF" if is_card_sel else "#FFFFFF"
                    badge_txt = "✔ 선택됨" if is_card_sel else f"후킹 썸네일 #{idx+1}"
                    badge_bg = "#4F46E5" if is_card_sel else "#94A3B8"
                    
                    col_copy_txt, col_copy_btn = st.columns([4.2, 1])
                    with col_copy_txt:
                        st.markdown(
                            f'<div style="background: {card_bg}; border: 1.5px solid {card_border}; border-radius: 10px; padding: 0.6rem 0.85rem; margin-bottom: 0.35rem;">'
                            f'<span style="font-size: 0.72rem; font-weight: 700; color: #FFFFFF; background: {badge_bg}; padding: 0.15rem 0.45rem; border-radius: 4px;">{badge_txt}</span><br>'
                            f'<span style="font-size: 0.88rem; font-weight: 700; color: #0F172A;">윗줄:</span> <span style="font-size: 0.88rem; color: #0284C7; font-weight: 700;">{item["line1"]}</span> &nbsp;|&nbsp; '
                            f'<span style="font-size: 0.88rem; font-weight: 700; color: #0F172A;">아랫줄:</span> <span style="font-size: 0.88rem; color: #D97706; font-weight: 700;">{item["line2"]}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                    with col_copy_btn:
                        btn_type = "primary" if is_card_sel else "secondary"
                        if st.button("선택", key=f"btn_pick_copy_{idx}", type=btn_type, use_container_width=True):
                            st.session_state.selected_thumb_idx = idx
                            st.rerun()

                chosen_thumb = ai_res["thumbnails"][cur_thumb_idx]

            with col_c1_right:
                col_t_img, col_t_ctrl = st.columns([1, 1.1])
                
                with col_t_ctrl:
                    st.markdown('<div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:10px; padding:0.65rem 0.8rem; margin-bottom:0.4rem;">', unsafe_allow_html=True)
                    st.markdown("##### 🎨 폰트 스타일 & 색상 조절")
                    st.caption("조절 즉시 왼쪽 커버에 실시간 반영됩니다.")
                    
                    st.markdown("🔹 **윗줄 텍스트 설정**")
                    cs1, cc1 = st.columns([2.5, 1.2])
                    with cs1:
                        line1_size = st.slider("윗줄 크기", min_value=40, max_value=120, value=76, step=2, key="slider_line1")
                    with cc1:
                        line1_color = st.color_picker("윗줄 색상", value="#00D2FF", key="picker_line1")
                        
                    st.markdown("🔸 **아랫줄 텍스트 설정**")
                    cs2, cc2 = st.columns([2.5, 1.2])
                    with cs2:
                        line2_size = st.slider("아랫줄 크기", min_value=40, max_value=120, value=76, step=2, key="slider_line2")
                    with cc2:
                        line2_color = st.color_picker("아랫줄 색상", value="#FFF200", key="picker_line2")

                    st.markdown("🟡 **쇼츠 1줄 자막 설정**")
                    cs3, cc3 = st.columns([2.5, 1.2])
                    with cs3:
                        sub_size = st.slider("자막 크기", min_value=12, max_value=24, value=16, step=1, key="slider_sub")
                    with cc3:
                        sub_color = st.color_picker("자막 색상", value="#FFF000", key="picker_sub")
                    
                    sub_margin_v = st.slider(
                        "↕️ 자막 세로 위치 (왼쪽: 아래로 ⬇️ / 오른쪽: 위로 ⬆️)",
                        min_value=10, max_value=200, value=45, step=5,
                        key="slider_sub_pos",
                        help="왼쪽으로 올수록 자막이 아래로 내려가고, 오른쪽으로 밀수록 위로 올라갑니다."
                    )
                    st.markdown('</div>', unsafe_allow_html=True)

                if parsed["images"]:
                    selected_bg = parsed["images"][st.session_state.get("selected_thumb_img_idx", 0)] if st.session_state.get("selected_thumb_img_idx", 0) < len(parsed["images"]) else parsed["images"][0]
                else:
                    selected_bg = None

                thumb_path = create_high_contrast_thumbnail(
                    bg_image_path=selected_bg,
                    line1=chosen_thumb["line1"],
                    line2=chosen_thumb["line2"],
                    font_size_1=line1_size,
                    font_size_2=line2_size,
                    color_1=line1_color,
                    color_2=line2_color
                )

                with col_t_img:
                    st.markdown('<div class="thumb-preview-box">', unsafe_allow_html=True)
                    st.image(thumb_path, caption="유튜브 쇼츠 첫 프레임 & 썸네일 커버", use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True) # End Card 1

            # 💳 [카드 2] 📸 수집 사진 선별 & 썸네일 지정 (전체 화면 너비 카드)
            st.markdown('<div class="saas-card">', unsafe_allow_html=True)
            st.markdown("#### 📸 수집 사진 선별 & 썸네일 커버 지정 (전체 갤러리)")
            if parsed["images"]:
                cur_count = len(parsed["images"])
                db_reused = 0
                try:
                    with get_db_connection() as conn:
                        cur_db = conn.cursor()
                        for p in parsed["images"]:
                            if os.path.exists(p):
                                h = compute_file_hash(p)
                                cur_db.execute("SELECT id FROM media WHERE file_hash = ? LIMIT 1", (h,))
                                if cur_db.fetchone():
                                    db_reused += 1
                except Exception:
                    db_reused = 0
                external_collected = max(0, cur_count - db_reused)
                
                bar_col1, bar_col2 = st.columns([4, 1])
                with bar_col1:
                    st.caption(f"💡 현재 **{cur_count}장** 사용 중 (🗄️ DB 재사용 **{db_reused}장** / 🌐 외부 수집 **{external_collected}장**) — 원치 않는 사진은 **'🗑️'** 버튼으로 제외하세요")
                with bar_col2:
                    if st.button("🔄 원본 전체 복원", help="삭제했던 사진들을 포함해 처음 수집된 사진 전체를 다시 복원합니다.", use_container_width=True):
                        if "images_original" in parsed:
                            parsed["images"] = list(parsed["images_original"])
                            st.session_state.selected_thumb_img_idx = 0
                            st.rerun()

                total_imgs = len(parsed["images"])
                cur_img_idx = st.session_state.get("selected_thumb_img_idx", 0)
                if cur_img_idx >= total_imgs:
                    cur_img_idx = 0
                    st.session_state.selected_thumb_img_idx = 0

                st.markdown('<div class="gallery-box">', unsafe_allow_html=True)
                cols_per_row = 6  # 전체 폭 활용 6열 배치
                for r_idx in range(0, total_imgs, cols_per_row):
                    row_slice = parsed["images"][r_idx:r_idx + cols_per_row]
                    cols = st.columns(cols_per_row)
                    for c_idx, img_p in enumerate(row_slice):
                        global_idx = r_idx + c_idx
                        is_sel = (global_idx == cur_img_idx)
                        with cols[c_idx]:
                            st.image(img_p, use_container_width=True)
                            st.caption(get_photo_source_badge(img_p))
                            b_c1, b_c2, b_c3 = st.columns([1.25, 1.0, 0.75])
                            with b_c1:
                                btn_txt = "⭐ 커버" if is_sel else "⭐ 선택"
                                btn_t = "primary" if is_sel else "secondary"
                                if st.button(btn_txt, key=f"thumb_pick_{global_idx}", type=btn_t, use_container_width=True):
                                    st.session_state.selected_thumb_img_idx = global_idx
                                    st.rerun()
                            with b_c2:
                                if st.button("✂️ 자르기", key=f"img_crop_{global_idx}", help="불필요한 글씨/로고 자르기 (점선 크롭)", use_container_width=True):
                                    open_crop_dialog(img_p, global_idx)
                            with b_c3:
                                if st.button("🗑️", key=f"img_del_{global_idx}", help="이 사진을 영상 및 블로그에서 제외", use_container_width=True):
                                    parsed["images"].pop(global_idx)
                                    if st.session_state.selected_thumb_img_idx >= len(parsed["images"]):
                                        st.session_state.selected_thumb_img_idx = max(0, len(parsed["images"]) - 1)
                                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("선택된 사진이 없습니다. '🔄 원본 전체 복원'을 누르세요.")

            # 🎬 [신규 기능] 해당 가수 YouTube Creative Commons(CC) 영상 수집 & 3~4초 컷편집 패널
            st.divider()
            st.markdown(f"##### 🎬 [{parsed['singer']}] YouTube Creative Commons(CC) 영상 수집 및 3~4초 컷편집 스튜디오")
            st.caption("가수의 실제 영상 컷(3~4초)을 직접 미리보고 자른 후 가수 미디어 라이브러리에 저장·재사용합니다 (일반 B-roll과 엄격히 분리).")

            # 1. DB FIRST: 가수의 기존 축적된 singer_cc_video DB 목록 표시 및 사용자 직접 선택
            if "selected_cc_clips" not in st.session_state:
                st.session_state.selected_cc_clips = {}

            singer_cc_db_clips = get_db_singer_cc_clips(parsed['singer'], limit=10)
            if singer_cc_db_clips:
                st.markdown(f"🗄️ **가수 라이브러리 DB 보유 클립 ({len(singer_cc_db_clips)}개)** — *원치 않는 영상은 '🗑️ DB 삭제'를 누르고, 사용할 영상만 체크하세요!*")
                cols_cc_db = st.columns(4)
                for c_idx, c_info in enumerate(singer_cc_db_clips):
                    fpath = c_info['file_path']
                    cid = c_info.get('id', c_idx)
                    if os.path.exists(fpath):
                        with cols_cc_db[c_idx % 4]:
                            st.caption(f"📹 {c_info.get('video_title', 'CC Clip')[:18]}... ({c_info.get('clip_duration', 3.5):.1f}초)")
                            st.markdown('<div class="compact-video-box">', unsafe_allow_html=True)
                            st.video(fpath)
                            st.markdown('</div>', unsafe_allow_html=True)
                            
                            c_c1, c_c2 = st.columns([1.6, 1])
                            with c_c1:
                                chk_key = f"chk_cc_{cid}"
                                is_checked = st.checkbox("✅ 쇼츠에 사용", value=True, key=chk_key)
                                cur_singer_sel = st.session_state.selected_cc_clips.get(parsed['singer'], [])
                                if is_checked:
                                    if fpath not in cur_singer_sel:
                                        cur_singer_sel.append(fpath)
                                else:
                                    if fpath in cur_singer_sel:
                                        cur_singer_sel.remove(fpath)
                                st.session_state.selected_cc_clips[parsed['singer']] = cur_singer_sel
                            with c_c2:
                                if st.button("🗑️ 삭제", key=f"btn_del_db_cc_{cid}", help="이 클립을 DB 및 디스크에서 완전 삭제합니다."):
                                    delete_media_record(cid)
                                    time.sleep(0.3)
                                    st.rerun()

            col_cc_btn1, col_cc_btn2, col_cc_info = st.columns([1.5, 1.8, 2.5])
            with col_cc_btn1:
                if st.button(f"🔍 [{parsed['singer']}] CC 영상 5개 탐색", key="btn_fetch_youtube_cc"):
                    with st.spinner(f"YouTube에서 [{parsed['singer']}] Creative Commons 영상 탐색 중..."):
                        cc_results = search_youtube_cc_videos(parsed['singer'], max_results=5)
                        st.session_state.youtube_cc_candidates = cc_results
                        st.rerun()

            cc_candidates = st.session_state.get("youtube_cc_candidates", [])
            with col_cc_btn2:
                if cc_candidates:
                    if st.button(f"⚡ 5개 후보 모두 컷편집 & DB 저장", key="btn_trim_all_cc", type="primary"):
                        with st.spinner(f"5개 CC 후보 영상을 설정한 구간/구도로 일괄 컷편집 & DB 저장 중..."):
                            saved_cnt = 0
                            for c_i, c_item in enumerate(cc_candidates):
                                t_s = st.session_state.get(f"cc_start_{c_i}", 10.0)
                                t_e = st.session_state.get(f"cc_end_{c_i}", min(c_item['original_duration'], t_s + 3.8))
                                c_x = float(st.session_state.get(f"cc_crop_x_{c_i}", 50))
                                try:
                                    r_p = download_raw_cc_video(c_item["youtube_url"])
                                    trim_and_normalize_cc_clip(
                                        raw_video_path=r_p,
                                        start_time=t_s,
                                        end_time=t_e,
                                        singer_name=parsed['singer'],
                                        metadata=c_item,
                                        crop_x_percent=c_x
                                    )
                                    saved_cnt += 1
                                except Exception as e_batch:
                                    print(f"Batch trim error candidate {c_i}: {e_batch}")
                            st.success(f"🎉 총 {saved_cnt}개 CC 클립이 DB 보관함에 저장되었습니다!")
                            time.sleep(0.5)
                            st.rerun()

            cc_candidates = st.session_state.get("youtube_cc_candidates", [])
            if cc_candidates:
                st.markdown("##### 📹 수집된 CC 영상 후보 목록 (구간 자르기 & DB 저장)")
                for idx, item in enumerate(cc_candidates):
                    with st.expander(f"🎬 후보 #{idx+1}: {item['video_title']} ({item['channel_name']})", expanded=(idx==0)):
                        c_v1, c_v2 = st.columns([1, 1.2])
                        with c_v1:
                            st.caption(f"🔗 [YouTube 원본 링크]({item['youtube_url']}) | 원본 길이: {item['original_duration']}초")
                            st.markdown(f"**라이선스**: `{item['license']}`")
                            
                            t_start = st.number_input(f"시작 시간(초)", min_value=0.0, max_value=float(max(1, item['original_duration']-1)), value=10.0, step=1.0, key=f"cc_start_{idx}")
                            t_end = st.number_input(f"종료 시간(초)", min_value=float(t_start+1.0), max_value=float(item['original_duration']), value=float(min(item['original_duration'], t_start+3.8)), step=0.5, key=f"cc_end_{idx}")
                            clip_len = round(t_end - t_start, 1)
                            st.info(f"✂️ 자르기 구간: `{t_start:.1f}s ~ {t_end:.1f}s` (클립 길이: {clip_len}초)")

                            crop_x_val = st.slider(
                                "↔️ 세로 크롭 좌우 위치 조절 (0%: 왼쪽 ~ 50%: 중앙 ~ 100%: 오른쪽)",
                                min_value=0, max_value=100, value=50, step=5,
                                key=f"cc_crop_x_{idx}",
                                help="가수 얼굴이 왼쪽에 쏠려있으면 30% 이하로, 우측에 쏠려있으면 70% 이상으로 설정하세요."
                            )

                        with c_v2:
                            st.markdown("##### 📸 9:16 세로 구도 실시간 미리보기")
                            # 1초 실시간 크롭 미리보기 프레임 추출
                            preview_img_path = None
                            try:
                                raw_p_tmp = download_raw_cc_video(item["youtube_url"])
                                preview_img_path = get_cc_crop_preview_frame(
                                    raw_video_path=raw_p_tmp,
                                    sample_time=float(t_start),
                                    crop_x_percent=float(crop_x_val)
                                )
                            except Exception as e_pv:
                                preview_img_path = None

                            if preview_img_path and os.path.exists(preview_img_path):
                                st.image(
                                    preview_img_path,
                                    caption=f"📸 시작시간 {t_start:.1f}s 프레임 (좌우 {crop_x_val}%)",
                                    width=240
                                )
                            else:
                                st.info("💡 1초 원본 영상 다운로드 중... 잠시 후 미리보기가 생성됩니다.")

                            col_act1, col_act2 = st.columns([1, 1])
                            with col_act1:
                                if st.button(f"🤖 가수 얼굴 자동 탐지", key=f"btn_autoface_{idx}"):
                                    with st.spinner("가수 얼굴 위치 탐지 중..."):
                                        try:
                                            raw_tmp = download_raw_cc_video(item["youtube_url"])
                                            detected_x = detect_video_face_center_percent(raw_tmp, sample_time=t_start)
                                            st.success(f"🎯 얼굴 위치: `{detected_x:.1f}%` (슬라이더를 {int(detected_x)}%로 조절)")
                                        except Exception as e_fd:
                                            st.warning(f"탐지 참고: {e_fd}")

                            with col_act2:
                                if st.button(f"💾 3~4초 클립 컷 & DB 저장", key=f"btn_trim_cc_{idx}", type="primary"):
                                    with st.spinner(f"1080x1920 3~4초 클립 컷편집 중 (구도 {crop_x_val}%)..."):
                                        try:
                                            raw_p = download_raw_cc_video(item["youtube_url"])
                                            trimmed_info = trim_and_normalize_cc_clip(
                                                raw_video_path=raw_p,
                                                start_time=t_start,
                                                end_time=t_end,
                                                singer_name=parsed['singer'],
                                                metadata=item,
                                                crop_x_percent=float(crop_x_val)
                                            )
                                            st.success(f"🎉 3~4초 CC 클립(구도 {crop_x_val}%)이 DB에 저장되었습니다!")
                                            time.sleep(0.5)
                                            st.rerun()
                                        except Exception as e_trim:
                                            st.error(f"클립 컷편집 중 오류: {e_trim}")

            st.markdown('</div>', unsafe_allow_html=True) # End Card 2

            # 💳 [카드 3] 📜 60초 쇼츠 나레이션 대본 (전체 화면 너비 카드)
            st.markdown('<div class="saas-card">', unsafe_allow_html=True)
            st.markdown("#### 📜 60초 쇼츠 나레이션 대본")
            edited_script = st.text_area("대본 수정 (필요 시 자유롭게 수정 가능)", value=ai_res["shorts_script"], height=160)
            st.markdown('</div>', unsafe_allow_html=True) # End Card 3

            # 💳 [카드 4] 🎬 영상 연출 옵션 & 🚀 렌더링 / 결과 플레이어 Card
            st.markdown('<div class="saas-card">', unsafe_allow_html=True)
            col_opt, col_render = st.columns([1.1, 1.2])

            with col_opt:
                st.markdown("#### 🎥 영상 연출 & B-roll 옵션 설정")
                singer_name = parsed["singer"]
                stored_clip_count = get_singer_clip_count(singer_name)
                
                if stored_clip_count > 0:
                    use_stage_clips = st.checkbox(
                        f"✅ [{singer_name}] 보관함 무작위 무대 짤 2개 교차 합성 (현재 {stored_clip_count}개 보유 중)",
                        value=True,
                        help="가수 보관함의 짤들을 무작위 추출하여 사진 사이사이에 교차 배치합니다."
                    )
                else:
                    st.info(f"💡 [{singer_name}] 보관함에 등록된 무대 짤이 없습니다. 상단 '🎬 무대 짤 보관함' 탭에서 생성 가능합니다.")
                    use_stage_clips = False

                use_reaction_card = st.checkbox(
                    "💬 [네티즌 실시간 반응] 연출 카드 삽입 (선택 사항)",
                    value=False,
                    help="영상 중간에 3초간 네티즌 응원 반응 카드를 삽입합니다."
                )

                st.divider()
                broll_mode = st.radio(
                    "🎬 스마트 B-roll 삽입",
                    [
                        "사용 안 함 (가수 무대 짤만 사용 - 기본)",
                        "💡 추천 B-roll 1개 자동 결합",
                        "🎨 B-roll 카테고리 직접 선택"
                    ],
                    index=0,
                    horizontal=True,
                    help="대본 문맥에 어울리는 HD 세로형 B-roll 영상을 스마트하게 결합합니다."
                )

                selected_broll_cat = None
                selected_broll_tag = None

                if broll_mode == "💡 추천 B-roll 1개 자동 결합":
                    try:
                        analysis = analyze_script_scenes(edited_script, singer_name=singer_name)
                        rec = analysis.get("primary_broll", {})
                        selected_broll_cat = rec.get("category", "audience")
                        selected_broll_tag = rec.get("tag", selected_broll_cat)
                        rec_sent = rec.get("sentence", "")
                        rec_reason = rec.get("reason", "")
                        st.info(f"🎯 **대본 분석 추천:** [{selected_broll_cat}] '{selected_broll_tag}' (문맥: \"{rec_sent[:35]}...\")")
                    except Exception as e_sc:
                        selected_broll_cat = "audience"
                        selected_broll_tag = "audience"

                elif broll_mode == "🎨 B-roll 카테고리 직접 선택":
                    cat_map = {
                        "audience (팬/관객/환호/박수)": ("audience", "cheering audience concert crowd fans"),
                        "emotion (눈물/감동/환희/뭉클)": ("emotion", "crying emotional tears touching moment"),
                        "hospital (병원/건강/치료/쾌유)": ("hospital", "hospital doctor medical healthcare room"),
                        "money (기부/수익/상금/매출)": ("money", "counting money cash finance currency"),
                        "smartphone (음원차트/유튜브/SNS)": ("smartphone", "smartphone screen browsing mobile typing"),
                        "concert (콘서트/무대/공연/열창)": ("concert", "concert music stage performance spotlight"),
                        "business (광고/전속계약/시상식)": ("business", "business meeting discussion handshake office")
                    }
                    sel_cat_key = st.selectbox("B-roll 카테고리 선택", list(cat_map.keys()))
                    selected_broll_cat, selected_broll_tag = cat_map[sel_cat_key]

                st.divider()
                st.markdown("##### 🎞️ 쇼츠 미디어 수량 & 구성 제어 (Custom Clip Mix)")
                
                preset_choice = st.radio(
                    "조합 프리셋 선택",
                    [
                        "⚡ 추천 멀티 믹스 (CC 1개 + B-roll 1개)",
                        "📷 사진 중심 쇼츠 (CC 0개 + B-roll 0개)",
                        "🎬 가수 CC 무대 강조 (CC 2개 + B-roll 0개)",
                        "🎨 화려한 B-roll 믹스 (CC 1개 + B-roll 2개)",
                        "⚙️ 커스텀 수량 직접 지정"
                    ],
                    index=0,
                    help="쇼츠 영상에 넣을 가수 CC 영상, 일반 B-roll, 무대 짤의 수량을 설정합니다."
                )

                if "📷 사진 중심" in preset_choice:
                    init_cc, init_broll, init_stage = 0, 0, 0
                elif "🎬 가수 CC 무대" in preset_choice:
                    init_cc, init_broll, init_stage = 2, 0, 0
                elif "🎨 화려한 B-roll" in preset_choice:
                    init_cc, init_broll, init_stage = 1, 2, 0
                elif "⚙️ 커스텀" in preset_choice:
                    init_cc, init_broll, init_stage = 1, 1, 1 if stored_clip_count > 0 else 0
                else: # ⚡ 추천 멀티 믹스
                    init_cc, init_broll, init_stage = 1, 1, 1 if stored_clip_count > 0 else 0

                c_cc, c_br, c_st = st.columns(3)
                with c_cc:
                    num_cc_count = st.number_input("🎬 가수 CC 영상", min_value=0, max_value=3, value=init_cc, step=1)
                with c_br:
                    num_broll_count = st.number_input("📽️ 일반 B-roll", min_value=0, max_value=3, value=init_broll, step=1)
                with c_st:
                    num_stage_count = st.number_input("🎤 보관함 무대짤", min_value=0, max_value=min(3, max(0, stored_clip_count)), value=min(init_stage, max(0, stored_clip_count)), step=1)

                st.markdown(
                    f"""
                    <div style="background-color: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 8px; padding: 10px 14px; margin-top: 10px; font-size: 0.88rem; color: #166534; font-weight: 500;">
                        📊 <b>타임라인 구성 예상:</b> CC 영상 {num_cc_count}개 + B-roll {num_broll_count}개 + 무대 짤 {num_stage_count}개<br>
                        💡 <i>나머지 남은 재생시간은 수집된 기사 사진들로 대본 길이에 맞춰 자동 켄 번즈 교차 배치됩니다.</i>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with col_render:
                st.markdown("#### 🚀 원클릭 쇼츠 영상 렌더링")
                st.caption("Edge-TTS 음성 + 음성 싱크 자막 합성 + 커스텀 미디어 믹스 + 켄 번즈 무빙 + 고대비 썸네일 (1080x1920 MP4)")
                
                render_btn = st.button("🎬 쇼츠 영상(MP4) 즉시 렌더링", type="primary", use_container_width=True)
                
                if render_btn:
                    with st.spinner("Edge-TTS 음성 합성 및 가수 CC 영상/사진 믹스 렌더링 중... (약 15~25초 소요)"):
                        try:
                            audio_path, srt_path = synthesize_speech(edited_script, voice=selected_voice)
                            stock_clip = ensure_stock_video() if use_reaction_card else None
                            stage_clips = get_random_singer_clips(singer_name, count=num_stage_count) if (num_stage_count > 0 and stored_clip_count > 0) else []
                            
                            all_imgs = parsed["images"]
                            if selected_bg and selected_bg in all_imgs:
                                video_imgs = [selected_bg] + [p for p in all_imgs if p != selected_bg]
                            else:
                                video_imgs = all_imgs

                            # CC 영상 클립 탐색 (사용자 체크박스 직접 선택 클립 1순위 -> DB 순서 순)
                            cc_file_paths = []
                            if num_cc_count > 0:
                                user_chosen = st.session_state.get("selected_cc_clips", {}).get(singer_name, [])
                                user_chosen_valid = [p for p in user_chosen if os.path.exists(p)]
                                if user_chosen_valid:
                                    cc_file_paths = user_chosen_valid[:num_cc_count]
                                else:
                                    db_cc = get_db_singer_cc_clips(singer_name, limit=num_cc_count * 2)
                                    cc_file_paths = [c["file_path"] for c in db_cc if os.path.exists(c.get("file_path", ""))][:num_cc_count]

                            proj_id = f"shorts_{singer_name}_{int(time.time())}"
                            try:
                                save_curated_photos(singer_name=singer_name, approved_photos=video_imgs, project_id=proj_id)
                            except Exception as e_db:
                                print(f"[MediaDB] 선별 사진 저장 알림: {e_db}")

                            # B-roll 영상 탐색 및 획득 (요청 수량만큼 추출)
                            broll_clips_list = []
                            if num_broll_count > 0 and selected_broll_cat:
                                try:
                                    broll_clips_list = get_or_fetch_broll_multiple(category=selected_broll_cat, tag=selected_broll_tag, count=num_broll_count, target_duration=3.5)
                                except Exception as e_br:
                                    print(f"[B-roll Engine] B-roll 추출 알림: {e_br}")
                                    broll_clips_list = []

                            video_path = render_shorts_video(
                                audio_path=audio_path,
                                thumbnail_path=thumb_path,
                                image_paths=video_imgs,
                                stock_video_path=stock_clip,
                                singer_clips=stage_clips,
                                singer_cc_clips=cc_file_paths,
                                broll_video_paths=broll_clips_list,
                                srt_path=srt_path,
                                sub_font_size=sub_size,
                                sub_color=sub_color,
                                sub_margin_v=sub_margin_v
                            )
                            st.session_state.rendered_video = video_path
                            st.success("쇼츠 영상 렌더링 성공! 영상 플레이어가 아래에 바로 준비되었습니다.")

                            with st.spinner("🔍 쇼츠 품질 검증(QA) 진행 중..."):
                                try:
                                    qa_res = run_full_qa(
                                        video_path=video_path,
                                        article_title=parsed.get("title", ""),
                                        article_content=parsed.get("content", ""),
                                        shorts_script=edited_script,
                                        blog_article=ai_res.get("blog_post", ""),
                                        singer_name=singer_name,
                                        tts_audio_path=audio_path,
                                        srt_path=srt_path,
                                        api_key=current_key if current_key else None
                                    )
                                    st.session_state.qa_result = qa_res
                                except Exception as e_qa:
                                    print(f"[QA] 검증 에러: {e_qa}")
                        except Exception as e_ren:
                            st.error(f"렌더링 실패: {e_ren}")

                # 🎬 렌더링된 쇼츠 영상 플레이어 및 QA 리포트 표시 (우측 자리에 바로 등장!)
                if st.session_state.rendered_video and os.path.exists(st.session_state.rendered_video):
                    st.divider()
                    st.markdown("##### 🎬 최종 렌더링 완료 영상 (1080x1920 MP4)")
                    
                    st.markdown('<div class="compact-video-box">', unsafe_allow_html=True)
                    st.video(st.session_state.rendered_video)
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                    with open(st.session_state.rendered_video, "rb") as vf:
                        st.download_button(
                            "📥 최종 쇼츠 MP4 다운로드",
                            data=vf,
                            file_name=f"shorts_{parsed.get('singer', 'trot')}.mp4",
                            mime="video/mp4",
                            use_container_width=True
                        )

                # 🔍 시니어 친화적 직관적 품질검증(QA) 스코어 카드
                if st.session_state.get("qa_result"):
                    qa_data = st.session_state.qa_result
                    status = qa_data.get("status", "NOT_RUN")
                    score = qa_data.get("total_score", 0.0)

                    if status == "PASS":
                        st.markdown(f"#### ✅ 품질 검증 합격 (총점: {score:.1f} / 100점)")
                    elif status == "WARNING":
                        st.markdown(f"#### ⚠️ 품질 검증 주의 (총점: {score:.1f} / 100점)")
                    else:
                        st.markdown(f"#### ❌ 품질 검증 미달 (총점: {score:.1f} / 100점)")

                    cat_scores = qa_data.get("category_scores", {})
                    c_tech = cat_scores.get("technical") or cat_scores.get("technical_specs") or {"score": 0.0, "max_score": 20.0}
                    c_fact = cat_scores.get("factual") or cat_scores.get("fact_accuracy") or {"score": 0.0, "max_score": 30.0}
                    c_rep = cat_scores.get("repetition") or cat_scores.get("repeat_prevention") or {"score": 0.0, "max_score": 25.0}
                    c_content = cat_scores.get("content_quality") or cat_scores.get("ai_review") or {"score": None, "max_score": 25.0}

                    ai_not_run = bool(
                        qa_data.get("ai_not_run", False)
                        or c_content.get("ai_not_run", False)
                        or c_content.get("score") is None
                    )

                    if ai_not_run:
                        st.markdown(
                            """
                            <div style="background-color: #FFF3E0; border-left: 5px solid #FF9800; border-radius: 8px; padding: 10px 16px; margin-bottom: 14px; font-weight: 600; color: #E65100;">
                                ⚠️ AI 심층 리뷰 미실행 (확인 권장 - Gemini API 연결 상태를 점검하세요)
                            </div>
                            """,
                            unsafe_allow_html=True
                        )

                    st.markdown("##### 📊 4대 핵심 품질 검증 점수")
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("🔧 기술 규격", f"{c_tech['score']} / 20점", delta="합격" if c_tech['score'] >= 14 else "미흡")
                    col2.metric("📰 사실성/일치도", f"{c_fact['score']} / 30점", delta="합격" if c_fact['score'] >= 21 else "미흡")
                    col3.metric("🔄 반복/다양성", f"{c_rep['score']} / 25점", delta="합격" if c_rep['score'] >= 18 else "중복주의")
                    if ai_not_run:
                        col4.metric("🤖 콘텐츠 완성도", "미실행", delta="확인 권장", delta_color="off")
                    else:
                        score_val = c_content.get("score", 0.0)
                        col4.metric("🤖 콘텐츠 완성도", f"{score_val} / 25점", delta="우수" if score_val >= 20 else "보통")

                    st.write("")
                    st.caption(f"🔧 기술 규격 (1080x1920 세로 해상도, 음성 싱크, 자막 규격): {c_tech['score']}점 / 20점")
                    st.progress(min(1.0, max(0.0, c_tech['score'] / 20.0)))

                    st.caption(f"📰 사실성/일치도 (가수명, 조회수·순위 등 숫자 검증, 자극적 왜곡 차단): {c_fact['score']}점 / 30점")
                    st.progress(min(1.0, max(0.0, c_fact['score'] / 30.0)))

                    st.caption(f"🔄 반복/다양성 (가수 과거 영상 대비 사진/B-roll/훅 중복 방지): {c_rep['score']}점 / 25점")
                    st.progress(min(1.0, max(0.0, c_rep['score'] / 25.0)))

                    if ai_not_run:
                        st.caption("🤖 콘텐츠 완성도 (멀티모달 AI 심층 리뷰): ⚠️ 미실행 (API 확인 필요)")
                        st.progress(0.0)
                    else:
                        score_val = c_content.get("score", 0.0)
                        st.caption(f"🤖 콘텐츠 완성도 (대본-화면 조화, 호흡, 문맥 자연스러움): {score_val}점 / 25점")
                        st.progress(min(1.0, max(0.0, score_val / 25.0)))

                    # Recommendations section
                    recs = qa_data.get("recommendations", [])
                    if recs:
                        st.markdown("---")
                        st.markdown("##### 💡 검수관 조치 권장사항")
                        for r in recs:
                            st.markdown(f"- {r}")

                    # Issues section
                    issues = qa_data.get("issues", [])
                    if issues:
                        st.markdown("---")
                        st.markdown("##### ⚠️ 발견된 세부 점검 항목")
                        for iss in issues:
                            itype = iss.get("type", "warning")
                            sev = iss.get("severity", "medium")
                            icon = "🔴" if (sev == "high" or itype == "error") else ("🟡" if sev == "medium" else "ℹ️")
                            comp = iss.get("component", "검증")
                            itype_tag = iss.get("issue_type")
                            prefix = f"[{comp.upper()} | {itype_tag}]" if itype_tag else f"[{comp.upper()}]"
                            msg = iss.get("message", "")
                            repairable = iss.get("repairable", False)
                            raction = iss.get("repair_action")
                            rtag = f" *(🛠️ 권장조치: {raction})*" if (repairable and raction) else ""
                            st.markdown(f"{icon} **{prefix}** {msg}{rtag}")
                    else:
                        st.success("🎉 감점 항목이 없습니다! 최고 품질로 검증되었습니다.")

                st.markdown('</div>', unsafe_allow_html=True) # End Card 4

        # === TAB 2: 블로그 원고 ===
        with tab_blog:
            st.markdown("#### 📋 트롯매거진 공식 4단 완성형 블로그 원고")
            st.caption("체류 시간 극대화 4단 서식 (사진 위치 지정 + 4번의 댓글 유도 질문 + 하단 트래픽 깔때기)")
            
            # 기사 내 추출된 사진 갤러리
            if parsed["images"]:
                head_col1, head_col2 = st.columns([3, 1])
                with head_col1:
                    st.markdown("##### 📸 블로그 삽입용 사진 4선 ([사진 1] 기사 대표컷 + [사진 2~4] 무작위 고화질컷)")
                with head_col2:
                    if st.button("🎲 사진 무작위 다시 섞기", help="수집된 20여 장의 가수 사진 풀에서 겹치지 않는 새로운 사진들을 즉시 무작위로 다시 뽑습니다."):
                        if len(parsed["images"]) > 4:
                            first = parsed["images"][0]
                            rest = parsed["images"][1:]
                            random.shuffle(rest)
                            st.session_state.parsed_data["images"] = [first] + rest
                            st.rerun()

                cols_img = st.columns(min(4, len(parsed["images"])))
                for i, c_img in enumerate(cols_img):
                    if i < len(parsed["images"]):
                        sub_cap = "(기사 보도사진)" if i == 0 else "(무작위 고화질)"
                        c_img.image(parsed["images"][i], caption=f"[사진 {i+1}] {sub_cap}", use_container_width=True)

            st.text_area("블로그 포스팅 본문", value=ai_res["blog_post"], height=550)
            
            # 클립보드 복사용 다운로드
            st.download_button(
                label="📄 블로그 원고 텍스트(.txt) 다운로드",
                data=ai_res["blog_post"],
                file_name=f"{parsed['singer']}_블로그원고.txt",
                mime="text/plain"
            )

# =========================================================================
# TAB 2: 가수별 무대 짤(클립) 보관함 관리
# =========================================================================
with main_tab_library:
    st.markdown("### 🎬 가수별 무대 짤(클립) 라이브러리 관리")
    st.markdown("유튜브 영상 링크나 소장 중인 동영상을 넣으면 **4초 단위의 무음(-an) 세로형(1080x1920) 짤로 자동 분할**하여 보관합니다.<br>매일 쇼츠를 만들 때 이 보관함에서 무작위로 2~3개를 섞어 합성하므로 **시청자가 '어제 봤던 영상 돌려막기'로 오해할 확률이 0%가 됩니다.**", unsafe_allow_html=True)
    st.write("")

    col_singer_sel, col_singer_stats = st.columns([2, 2])
    
    with col_singer_sel:
        singers_list = get_all_singers()
        selected_singer = st.selectbox("관리할 가수를 선택하세요", singers_list)
        
        new_singer_input = st.text_input("➕ 다른 가수를 추가하려면 이름을 입력하세요", placeholder="예: 박지현, 전유진...")
        if new_singer_input.strip():
            selected_singer = new_singer_input.strip()

    curr_count = get_singer_clip_count(selected_singer)
    with col_singer_stats:
        st.metric(label=f"[{selected_singer}] 현재 보유 짤 수", value=f"{curr_count} 개")
        if curr_count >= 20:
            st.success("🟢 충분한 짤이 확보되어 있어 장기 운영 시 완벽한 무작위 로테이션이 가능합니다!")
        elif curr_count >= 5:
            st.info("🟡 짤이 등록되어 있습니다. 15~20개 이상 모으시면 더욱 다양한 연출이 가능합니다.")
        else:
            st.warning("🔴 보유 짤이 부족합니다. 아래 유튜브 링크를 입력해 4초 짤을 자동 생성해 보세요!")

    st.divider()

    # 짤 추가 섹션
    st.subheader(f"📥 [{selected_singer}] 새 무대 짤 추가하기")
    method_tab1, method_tab2 = st.tabs(["🌐 유튜브 영상 링크로 자동 추출 (추천!)", "📁 내 컴퓨터 동영상 파일(MP4) 업로드"])

    # [방법 1: 유튜브 다운로드 & 분할]
    with method_tab1:
        st.caption("가수의 무대 직캠, 방송 클립, 쇼츠 유튜브 URL을 입력하면 자동으로 무음 세로 짤을 생성합니다.")
        yt_url = st.text_input("유튜브 동영상 링크 입력", placeholder="https://www.youtube.com/watch?v=... 또는 https://youtube.com/shorts/...", key="yt_url_input")
        
        c_dur, c_max = st.columns(2)
        with c_dur:
            clip_dur = st.slider("클립 1개당 길이(초)", min_value=3.0, max_value=6.0, value=4.0, step=0.5, key="yt_dur_slider")
        with c_max:
            max_clips_count = st.slider("최대 추출할 짤 개수", min_value=3, max_value=20, value=10, step=1, key="yt_max_slider")

        yt_btn = st.button("🚀 유튜브 영상 다운로드 & 4초 짤 자동 분할 저장", type="primary", use_container_width=True)
        if yt_btn:
            if not yt_url.strip():
                st.error("유튜브 링크를 입력해 주세요!")
            else:
                progress_bar = st.progress(0.0)
                status_text = st.empty()
                status_text.text("유튜브 영상 다운로드 중... 잠시만 기다려주세요.")

                def yt_progress(done, total):
                    progress_bar.progress(done / total)
                    status_text.text(f"4초 짤 변환 및 저장 중... ({done}/{total})")

                try:
                    res_clips = download_youtube_and_slice(
                        youtube_url=yt_url.strip(),
                        singer_name=selected_singer,
                        clip_duration=clip_dur,
                        max_clips=max_clips_count,
                        progress_callback=yt_progress
                    )
                    status_text.text("")
                    progress_bar.empty()
                    st.success(f"🎉 축하합니다! [{selected_singer}] 짤 {len(res_clips)}개가 성공적으로 추출되어 보관함에 저장되었습니다!")
                    time.sleep(1)
                    st.rerun()
                except Exception as ex:
                    st.error(f"유튜브 다운로드 및 분할 실패: {ex}")

    # [방법 2: 로컬 MP4 파일 업로드]
    with method_tab2:
        st.caption("소장 중인 MP4 동영상 파일을 올려주시면 4초 단위로 잘라 보관함에 넣습니다.")
        uploaded_video = st.file_uploader("MP4 동영상 파일 선택", type=["mp4", "mov", "avi", "mkv"], key="local_video_uploader")
        
        col_ldur, col_lmax = st.columns(2)
        with col_ldur:
            local_dur = st.slider("클립 1개당 길이(초)", min_value=3.0, max_value=6.0, value=4.0, step=0.5, key="local_dur_slider")
        with col_lmax:
            local_max = st.slider("최대 추출할 짤 개수", min_value=3, max_value=20, value=10, step=1, key="local_max_slider")

        local_btn = st.button("✂️ 업로드 영상 4초 짤 분할 & 저장", use_container_width=True)
        if local_btn:
            if not uploaded_video:
                st.error("동영상 파일을 선택해 주세요!")
            else:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_v:
                    tmp_v.write(uploaded_video.read())
                    tmp_v_path = tmp_v.name

                pbar = st.progress(0.0)
                stext = st.empty()
                stext.text("업로드 영상 분할 변환 중...")

                def local_progress(done, total):
                    pbar.progress(done / total)
                    stext.text(f"무음 세로 짤 생성 중... ({done}/{total})")

                try:
                    res_clips = slice_video_into_clips(
                        source_video_path=tmp_v_path,
                        singer_name=selected_singer,
                        clip_duration=local_dur,
                        max_clips=local_max,
                        progress_callback=local_progress
                    )
                    pbar.empty()
                    stext.text("")
                    st.success(f"🎉 [{selected_singer}] 짤 {len(res_clips)}개 저장 완료!")
                    time.sleep(1)
                    st.rerun()
                except Exception as ex:
                    st.error(f"영상 분할 처리 실패: {ex}")
                finally:
                    if os.path.exists(tmp_v_path):
                        os.remove(tmp_v_path)

    st.divider()

    # 보관함 갤러리 및 삭제
    st.subheader(f"📂 [{selected_singer}] 보관된 짤 갤러리 ({curr_count}개)")
    clips = get_singer_clips(selected_singer)
    
    if not clips:
        st.info("현재 보관된 짤이 없습니다. 위에서 유튜브 링크나 동영상을 넣어 짤을 등록해 보세요!")
    else:
        # 무작위 2개 미리보기 테스트 버튼
        col_test_btn, _ = st.columns([2, 3])
        with col_test_btn:
            if st.button("🎲 쇼츠 합성용 무작위 2개 짤 테스트 추출"):
                test_picks = get_random_singer_clips(selected_singer, count=2)
                st.markdown("##### 🎲 무작위 선별된 짤 미리보기 (이번 쇼츠에 들어갈 영상 후보)")
                c1, c2 = st.columns(2)
                if len(test_picks) > 0:
                    c1.video(test_picks[0])
                if len(test_picks) > 1:
                    c2.video(test_picks[1])

        st.write("")
        # 4열 그리드로 클립 표시
        cols = st.columns(4)
        for idx, cp in enumerate(clips):
            with cols[idx % 4]:
                st.markdown('<div class="compact-video-box">', unsafe_allow_html=True)
                st.video(cp)
                st.markdown('</div>', unsafe_allow_html=True)
                fsize = os.path.getsize(cp) / 1024
                c_fname = os.path.basename(cp)
                st.caption(f"클립 #{idx+1} ({fsize:.0f}KB)")
                
                if st.button(f"🗑️ 삭제", key=f"del_clip_{idx}_{c_fname}"):
                    delete_clip(cp)
                    st.success("클립이 삭제되었습니다.")
                    time.sleep(0.5)
                    st.rerun()
