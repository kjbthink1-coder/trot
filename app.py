import streamlit as st
import os
import sys
import tempfile
import time

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crawler.news_parser import parse_naver_news
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
from engine.media_db import get_media_stats, get_db_connection, compute_file_hash
from engine.scene_analyzer import analyze_script_scenes
from engine.broll_engine import get_or_fetch_broll
from crawler.image_enricher import save_curated_photos
from engine.qa import run_full_qa

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

# 커스텀 CSS (시니어 친화적 고대비 & 직관적 UI)
st.markdown("""
<style>
    .main-title { font-size: 2.2rem; font-weight: 800; color: #1E88E5; margin-bottom: 0.2rem; }
    .sub-title { font-size: 1.1rem; color: #555; margin-bottom: 1.5rem; }
    .card-box { background: #f8f9fa; padding: 1.2rem; border-radius: 10px; border-left: 5px solid #1E88E5; margin-bottom: 1rem; }
    .stButton>button { font-weight: bold; border-radius: 8px; height: 3rem; }
    .engine-badge { display: inline-block; padding: 0.3rem 0.8rem; border-radius: 20px; font-weight: bold; font-size: 0.9rem; margin-bottom: 1rem; }
    .clip-stat-badge { display: inline-block; background-color: #E3F2FD; color: #0D47A1; padding: 0.4rem 0.8rem; border-radius: 6px; font-weight: bold; margin-bottom: 0.8rem; }
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
    st.header("⚙️ 환경 설정")
    
    provider = st.selectbox("AI 엔진 선택", ["gemini", "openai", "내장 템플릿 (API 키 없이 즉시 생성)"])
    
    current_key = ""
    if provider == "gemini":
        saved_gemini = load_env_key("GEMINI_API_KEY")
        api_key_input = st.text_input("Gemini API Key", type="password", value=saved_gemini, help="Google AI Studio에서 무료 발급받은 키를 넣으세요")
        
        col_save, _ = st.columns([1, 1])
        with col_save:
            if st.button("💾 키 영구 저장"):
                if api_key_input.strip():
                    save_env_key("GEMINI_API_KEY", api_key_input)
                    st.success("API 키가 저장되었습니다!")
                else:
                    st.warning("키를 입력해 주세요.")
        
        current_key = api_key_input.strip() or saved_gemini
        if current_key:
            st.caption("🟢 API 키가 설정되어 있습니다.")
        else:
            st.caption("🟡 키가 없으면 내장 템플릿으로 자동 생성됩니다.")

    elif provider == "openai":
        saved_openai = load_env_key("OPENAI_API_KEY")
        api_key_input = st.text_input("OpenAI API Key", type="password", value=saved_openai)
        if st.button("💾 키 영구 저장"):
            save_env_key("OPENAI_API_KEY", api_key_input)
            st.success("API 키 저장 완료!")
        current_key = api_key_input.strip() or saved_openai

    st.markdown("---")
    st.markdown("🎬 **무료 B-roll 영상 API 설정**")
    saved_pexels = load_env_key("PEXELS_API_KEY")
    pexels_input = st.text_input(
        "Pexels API Key",
        type="password",
        value=saved_pexels,
        help="https://www.pexels.com/api/ 에서 발급받은 무료 키"
    )
    if st.button("💾 Pexels 키 저장", key="btn_save_pexels"):
        if pexels_input.strip():
            save_env_key("PEXELS_API_KEY", pexels_input)
            st.success("Pexels API 키가 저장되었습니다!")
        else:
            st.warning("키를 입력해 주세요.")
    if pexels_input.strip() or saved_pexels:
        st.caption("🟢 고화질 9:16 B-roll 자동 다운로드 활성화됨")
    else:
        st.caption("⚪ 키 미입력 시 기저장된 로컬 DB B-roll 우선 재사용")
    
    st.divider()
    voice_choice = st.radio("AI 성우 목소리", ["여성 성우 (선희 - 따뜻한 감동)", "남성 성우 (인준 - 묵직한 신뢰)"])
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
            broll_mode = "사용 안 함 (가수 무대 짤만 사용 - 기본)"
            selected_broll_cat = None
            selected_broll_tag = None

            col_left, col_right = st.columns([1, 1])
            
            with col_left:
                st.markdown("#### 🎯 5070 후킹 썸네일 카피 선택 (결론 은닉형)")
                thumb_options = [
                    f"{idx+1}. 윗줄: [{item['line1']}] / 아랫줄: [{item['line2']}]"
                    for idx, item in enumerate(ai_res["thumbnails"])
                ]
                selected_thumb_idx = st.radio("마음에 드는 썸네일 카피를 선택하세요", range(len(thumb_options)), format_func=lambda x: thumb_options[x])
                chosen_thumb = ai_res["thumbnails"][selected_thumb_idx]
                
                # 📸 수집 사진 선별 & 썸네일 지정 스튜디오 (사용자 큐레이션)
                st.markdown("#### 📸 수집 사진 선별 & 썸네일 지정")
                if parsed["images"]:
                    cur_count = len(parsed["images"])
                    
                    # 미디어 DB 재사용 vs 외부 신규 수집 집계
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
                    
                    bar_col1, bar_col2 = st.columns([2.8, 1])
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

                    cols_per_row = 4
                    for r_idx in range(0, total_imgs, cols_per_row):
                        row_slice = parsed["images"][r_idx:r_idx + cols_per_row]
                        cols = st.columns(cols_per_row)
                        for c_idx, img_p in enumerate(row_slice):
                            global_idx = r_idx + c_idx
                            is_sel = (global_idx == cur_img_idx)
                            with cols[c_idx]:
                                st.image(img_p, use_container_width=True)
                                b_c1, b_c2 = st.columns([1.3, 1])
                                with b_c1:
                                    btn_txt = "⭐선택됨" if is_sel else "⭐선택"
                                    btn_t = "primary" if is_sel else "secondary"
                                    if st.button(btn_txt, key=f"thumb_pick_{global_idx}", type=btn_t, use_container_width=True):
                                        st.session_state.selected_thumb_img_idx = global_idx
                                        st.rerun()
                                with b_c2:
                                    if st.button("🗑️", key=f"img_del_{global_idx}", help="이 사진을 영상 및 블로그에서 제외", use_container_width=True):
                                        parsed["images"].pop(global_idx)
                                        if st.session_state.selected_thumb_img_idx >= len(parsed["images"]):
                                            st.session_state.selected_thumb_img_idx = max(0, len(parsed["images"]) - 1)
                                        st.rerun()

                    if parsed["images"]:
                        selected_bg = parsed["images"][st.session_state.selected_thumb_img_idx]
                    else:
                        selected_bg = None
                else:
                    st.info("선택된 사진이 없습니다. '🔄 원본 전체 복원'을 누르세요.")
                    selected_bg = None

                st.markdown("#### 📜 60초 쇼츠 나레이션 대본 (영웅대학/서진대학 공식)")
                edited_script = st.text_area("대본 수정 (필요 시 수정 가능)", value=ai_res["shorts_script"], height=160)

                # 가수 무대 짤 보관함 연동 상태 확인
                singer_name = parsed["singer"]
                stored_clip_count = get_singer_clip_count(singer_name)
                
                st.markdown("#### 🎥 영상 연출 & 무대 짤 교차 합성")
                if stored_clip_count > 0:
                    use_stage_clips = st.checkbox(
                        f"✅ [{singer_name}] 보관함에서 무작위 짤 2개 자동 선별 합성 (현재 {stored_clip_count}개 보유 중)",
                        value=True,
                        help="가수 보관함의 짤들을 무작위 추출하여 사진 사이사이에 교차 배치합니다. 100% 무음 처리되어 저작권 걱정이 없습니다."
                    )
                else:
                    st.info(f"💡 [{singer_name}] 보관함에 등록된 무대 짤이 없습니다. 상단 '🎬 가수별 무대 짤 보관함' 탭에서 유튜브 영상 링크를 넣으면 자동으로 4초 짤이 생성되어 쇼츠에 합성됩니다.")
                    use_stage_clips = False

                use_reaction_card = st.checkbox(
                    "💬 [네티즌 실시간 반응] 연출 카드 삽입 (선택 사항)",
                    value=False,
                    help="영상 중간에 3초간 네티즌 응원 반응 카드를 삽입합니다. 체크를 해제하면 100% 가수 고화질 사진과 무대 짤로만 쾌적하게 이어집니다."
                )

                st.markdown("---")
                st.markdown("##### 🎬 스마트 B-roll 삽입")
                broll_mode = st.radio(
                    "🎬 스마트 B-roll 삽입",
                    [
                        "사용 안 함 (가수 무대 짤만 사용 - 기본)",
                        "💡 추천 B-roll 1개 자동 결합",
                        "🎨 B-roll 카테고리 직접 선택"
                    ],
                    index=0,
                    horizontal=True,
                    help="대본 문맥에 어울리는 HD 세로형 B-roll 영상을 30~40초 구간에 스마트하게 결합합니다."
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

                        st.info(f"🎯 **대본 분석 추천:** [{selected_broll_cat}] 태그: '{selected_broll_tag}' (문맥: \"{rec_sent[:40]}...\")\n\n📌 **선정 사유:** {rec_reason}")

                        candidates = analysis.get("candidates", [])
                        if len(candidates) > 1:
                            cand_tags = [f"[{c['category']}] {c['tag']}" for c in candidates[1:4]]
                            st.caption(f"🔍 **추가 감지된 후보군:** {', '.join(cand_tags)}")
                    except Exception as e_sc:
                        st.warning(f"대본 분석 중 오류 발생, 기본 관객 B-roll로 대체: {e_sc}")
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
                    sel_cat_key = st.selectbox(
                        "B-roll 카테고리 직접 선택 (7대 표준 카테고리)",
                        list(cat_map.keys())
                    )
                    selected_broll_cat, selected_broll_tag = cat_map[sel_cat_key]
                    st.caption(f"선택: **[{selected_broll_cat}]** (로컬 DB 축적 미디어 우선 활용 후 미보유 시 자동 조달)")

            with col_right:
                st.markdown("#### 👁️ 고대비 썸네일 실시간 디자인 스튜디오")
                
                col_t_img, col_t_ctrl = st.columns([1, 1.1])
                
                with col_t_ctrl:
                    st.markdown("##### 🎨 폰트 크기 & 색상 조절")
                    st.caption("슬라이더를 조절하면 왼쪽 썸네일 미리보기에 즉시 반영됩니다.")
                    
                    st.markdown("🔹 **윗줄 텍스트 설정**")
                    cs1, cc1 = st.columns([3, 2])
                    with cs1:
                        line1_size = st.slider("윗줄 크기", min_value=40, max_value=120, value=76, step=2, key="slider_line1")
                    with cc1:
                        line1_color = st.color_picker("윗줄 색상", value="#00D2FF", key="picker_line1")
                        
                    st.markdown("🔸 **아랫줄 텍스트 설정**")
                    cs2, cc2 = st.columns([3, 2])
                    with cs2:
                        line2_size = st.slider("아랫줄 크기", min_value=40, max_value=120, value=76, step=2, key="slider_line2")
                    with cc2:
                        line2_color = st.color_picker("아랫줄 색상", value="#FFF200", key="picker_line2")

                    st.markdown("🟡 **쇼츠 1줄 자막 설정**")
                    cs3, cc3 = st.columns([3, 2])
                    with cs3:
                        sub_size = st.slider("자막 크기", min_value=12, max_value=24, value=16, step=1, key="slider_sub")
                    with cc3:
                        sub_color = st.color_picker("자막 색상", value="#FFF000", key="picker_sub")

                # 썸네일 실시간 동적 생성
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
                    st.image(thumb_path, caption="유튜브 쇼츠 첫 프레임 & 썸네일 커버", use_container_width=True)
                
                st.markdown("#### 🚀 원클릭 쇼츠 영상 렌더링")
                st.caption("Edge-TTS 음성 + 음성 싱크 자막 합성 + 기사 사진 & 켄 번스 무빙 + 고대비 썸네일 (1080x1920 MP4)")
                
                render_btn = st.button("🎬 쇼츠 영상(MP4) 즉시 렌더링", type="primary", use_container_width=True)
                
                if render_btn:
                    with st.spinner("Edge-TTS 음성 합성 및 무대 짤 교차 편집 렌더링 중... (약 15~25초 소요)"):
                        try:
                            # 1. 음성 합성
                            audio_path, srt_path = synthesize_speech(edited_script, voice=selected_voice)
                            
                            # 2. 스톡 영상 확보 (선택 시에만)
                            stock_clip = ensure_stock_video() if use_reaction_card else None
                            
                            # 3. 무대 짤 추출 (체크 시 무작위 2개)
                            stage_clips = []
                            if use_stage_clips:
                                stage_clips = get_random_singer_clips(singer_name, count=2)
                            
                            # 선택된 썸네일 사진을 영상 첫 번째 사진 컷으로 배치하여 연속성 극대화
                            all_imgs = parsed["images"]
                            if selected_bg and selected_bg in all_imgs:
                                video_imgs = [selected_bg] + [p for p in all_imgs if p != selected_bg]
                            else:
                                video_imgs = all_imgs

                            # [미디어 DB 연동] 사용자가 최종 선별한 생존 사진들을 영구 Media DB에 축적
                            proj_id = f"shorts_{singer_name}_{int(time.time())}"
                            try:
                                save_curated_photos(singer_name=singer_name, approved_photos=video_imgs, project_id=proj_id)
                            except Exception as e_db:
                                print(f"[MediaDB] 선별 사진 저장 알림: {e_db}")

                            # 🎬 B-roll 영상 확보 (B-roll 모드가 '사용 안 함'이 아닐 때)
                            broll_clip = None
                            if broll_mode != "사용 안 함 (가수 무대 짤만 사용 - 기본)" and selected_broll_cat:
                                try:
                                    with st.spinner(f"스마트 B-roll [{selected_broll_cat}] 영상 확보 중... (미디어 DB 우선 검색)"):
                                        broll_clip = get_or_fetch_broll(
                                            category=selected_broll_cat,
                                            tag=selected_broll_tag,
                                            target_duration=3.5
                                        )
                                        print(f"[B-roll Engine] B-roll 클립 확보: {broll_clip}")
                                except Exception as e_br:
                                    print(f"[B-roll Engine] B-roll 확보 실패: {e_br}")
                                    broll_clip = None

                            # 4. 비디오 렌더링
                            video_path = render_shorts_video(
                                audio_path=audio_path,
                                thumbnail_path=thumb_path,
                                image_paths=video_imgs,
                                stock_video_path=stock_clip,
                                singer_clips=stage_clips,
                                srt_path=srt_path,
                                sub_font_size=sub_size,
                                sub_color=sub_color,
                                broll_video_path=broll_clip
                            )
                            st.session_state.rendered_video = video_path
                            st.success("쇼츠 영상 렌더링 성공! 무작위 짤 및 스마트 B-roll 교차 편집이 완료되었습니다.")

                            # 🔍 쇼츠 품질 검증(QA) 자동 종합 검수 (기술/사실/중복/AI 4대 영역)
                            with st.spinner("🔍 쇼츠 품질 검증(QA) 진행 중... (기술/사실/중복/AI 종합 심사)"):
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
                                        images=video_imgs,
                                        broll_path=broll_clip,
                                        api_key=current_key if current_key else None,
                                        project_id=proj_id
                                    )
                                    st.session_state.qa_result = qa_res
                                except Exception as e_qa:
                                    print(f"[QA Aggregator] 검수 실행 오류: {e_qa}")
                        except Exception as e:
                            st.error(f"영상 제작 중 오류 발생: {e}")

                if st.session_state.rendered_video and os.path.exists(st.session_state.rendered_video):
                    st.video(st.session_state.rendered_video)
                    with open(st.session_state.rendered_video, "rb") as vf:
                        st.download_button(
                            label="⬇️ 완성된 쇼츠 영상(MP4) 다운로드",
                            data=vf.read(),
                            file_name=f"{parsed['singer']}_쇼츠_최종.mp4",
                            mime="video/mp4",
                            use_container_width=True
                        )

                    # 🔍 시니어 친화적 직관적 품질검증(QA) 스코어 카드
                    if st.session_state.get("qa_result"):
                        qa_data = st.session_state.qa_result
                        status = qa_data.get("status", "NOT_RUN")
                        score = qa_data.get("total_score", 0.0)

                        if status == "PASS":
                            st.markdown(
                                f"""
                                <div style="background-color: #E8F5E9; border: 2px solid #4CAF50; border-radius: 12px; padding: 14px 20px; margin-top: 15px; margin-bottom: 12px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #1B5E20;">
                                            🟢 <b>품질검증 PASS ({score}점)</b> &nbsp;—&nbsp; <span style="font-size: 1.05rem; color: #2E7D32;">유튜브 업로드 추천</span>
                                        </div>
                                        <span style="background: #4CAF50; color: white; padding: 4px 14px; border-radius: 20px; font-weight: bold; font-size: 0.9rem;">
                                            안전도 100%
                                        </span>
                                    </div>
                                    <div style="margin-top: 6px; font-size: 0.95rem; color: #2E7D32; font-weight: 500;">
                                        유튜브 알고리즘 적합성 및 팩트 체크를 모두 통과했습니다. 안심하고 채널에 업로드하세요!
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )
                        elif status == "WARNING":
                            st.markdown(
                                f"""
                                <div style="background-color: #FFFDE7; border: 2px solid #FBC02D; border-radius: 12px; padding: 14px 20px; margin-top: 15px; margin-bottom: 12px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #F57F17;">
                                            🟡 <b>품질검증 WARNING ({score}점)</b> &nbsp;—&nbsp; <span style="font-size: 1.05rem; color: #E65100;">확인 권장 항목 있음</span>
                                        </div>
                                        <span style="background: #FBC02D; color: #212121; padding: 4px 14px; border-radius: 20px; font-weight: bold; font-size: 0.9rem;">
                                            확인 권장
                                        </span>
                                    </div>
                                    <div style="margin-top: 6px; font-size: 0.95rem; color: #E65100; font-weight: 500;">
                                        업로드는 가능하나 일부 주의 항목이 감지되었습니다. 아래 세부 리포트를 가볍게 확인해 보세요.
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )
                        else:
                            st.markdown(
                                f"""
                                <div style="background-color: #FFEBEE; border: 2px solid #E53935; border-radius: 12px; padding: 14px 20px; margin-top: 15px; margin-bottom: 12px;">
                                    <div style="display: flex; align-items: center; justify-content: space-between;">
                                        <div style="font-size: 1.25rem; font-weight: 800; color: #B71C1C;">
                                            🔴 <b>품질검증 FAIL ({score}점)</b> &nbsp;—&nbsp; <span style="font-size: 1.05rem; color: #C62828;">수정 권장</span>
                                        </div>
                                        <span style="background: #E53935; color: white; padding: 4px 14px; border-radius: 20px; font-weight: bold; font-size: 0.9rem;">
                                            재점검 필요
                                        </span>
                                    </div>
                                    <div style="margin-top: 6px; font-size: 0.95rem; color: #C62828; font-weight: 500;">
                                        사실 왜곡이나 기술적 미비점, 또는 심한 중복이 감지되었습니다. 대본이나 사진을 수정한 후 다시 렌더링하세요.
                                    </div>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )

                        # Collapsible detailed report
                        with st.expander("🔍 품질검증(QA) 세부 리포트 (유튜브 알고리즘 안전 점검)", expanded=False):
                            cat_scores = qa_data.get("category_scores", {})
                            c_tech = cat_scores.get("technical", {"score": 0.0, "max_score": 20.0})
                            c_fact = cat_scores.get("factual", {"score": 0.0, "max_score": 30.0})
                            c_rep = cat_scores.get("repetition", {"score": 0.0, "max_score": 25.0})
                            c_content = cat_scores.get("content_quality") or cat_scores.get("ai_review", {"score": None, "max_score": 25.0})

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
        # 3열 그리드로 클립 표시
        cols = st.columns(3)
        for idx, cp in enumerate(clips):
            with cols[idx % 3]:
                st.video(cp)
                fsize = os.path.getsize(cp) / 1024
                c_fname = os.path.basename(cp)
                st.caption(f"클립 #{idx+1} ({fsize:.0f}KB)")
                
                if st.button(f"🗑️ 삭제", key=f"del_clip_{idx}_{c_fname}"):
                    delete_clip(cp)
                    st.success("클립이 삭제되었습니다.")
                    time.sleep(0.5)
                    st.rerun()
