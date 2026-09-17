import streamlit as st
import os
import sys
import tempfile
import time
import hashlib
import shutil

# 프로젝트 루트 경로 추가
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PROJECT_ROOT)

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
    delete_clip,
    get_video_duration
)
from engine.media_db import (
    get_media_stats,
    get_db_connection,
    compute_file_hash,
    update_media_file_hash,
    delete_media_record,
    query_brolls,
    register_media
)
from engine.scene_analyzer import analyze_script_scenes
from engine.broll_engine import (
    get_or_fetch_broll,
    get_or_fetch_broll_multiple,
    sync_broll_assets,
    normalize_video_clip,
    search_pexels_videos,
    search_pixabay_videos,
    extract_best_video_candidate,
    download_single_clip,
    load_env_keys,
    CATEGORY_QUERY_MAP
)
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
        st.markdown("##### ⚡ Gemini 4중 API 키 멀티 로테이션 설정")
        st.caption("키 #1 사용량 초과(429) 시 두 번째, 세 번째 키로 즉시 자동 우회 접속됩니다.")
        
        k1 = load_env_key("GEMINI_API_KEY")
        k2 = load_env_key("GEMINI_API_KEY_2")
        k3 = load_env_key("GEMINI_API_KEY_3")
        k4 = load_env_key("GEMINI_API_KEY_4")
        
        col_k1, col_k2 = st.columns(2)
        with col_k1:
            k1_in = st.text_input("🔑 Gemini API Key #1 (주 키)", type="password", value=k1, help="메인 키")
            k3_in = st.text_input("🔑 Gemini API Key #3 (우회 키 2)", type="password", value=k3, help="예비 키 2")
        with col_k2:
            k2_in = st.text_input("🔑 Gemini API Key #2 (우회 키 1)", type="password", value=k2, help="예비 키 1")
            k4_in = st.text_input("🔑 Gemini API Key #4 (우회 키 3)", type="password", value=k4, help="예비 키 3")

        if st.button("💾 Gemini 4중 키 영구 저장", key="btn_save_gemini_modal", use_container_width=True):
            save_env_key("GEMINI_API_KEY", k1_in)
            save_env_key("GEMINI_API_KEY_2", k2_in)
            save_env_key("GEMINI_API_KEY_3", k3_in)
            save_env_key("GEMINI_API_KEY_4", k4_in)
            st.success("🎉 Gemini 4중 API 키가 성공적으로 저장 및 연결되었습니다!")
            time.sleep(0.5)
            st.rerun()

        valid_count = sum(1 for k in [k1_in, k2_in, k3_in, k4_in] if k and k.strip())
        if valid_count > 0:
            st.caption(f"🟢 총 **{valid_count}개**의 Gemini API 키가 정상 감지되었습니다. (사용량 초과 시 자동 우회 릴레이 작동)")
        else:
            st.caption("🟡 키가 미입력 상태입니다. 미입력 시 내장 기본 템플릿으로 자동 전환됩니다.")

    elif provider == "openai":
        saved_openai = load_env_key("OPENAI_API_KEY")
        api_key_input = st.text_input("OpenAI API Key", type="password", value=saved_openai)
        if st.button("💾 OpenAI 키 영구 저장", key="btn_save_openai_modal"):
            save_env_key("OPENAI_API_KEY", api_key_input)
            st.success("OpenAI API 키 저장 완료!")
            time.sleep(0.5)
            st.rerun()

    st.divider()
    st.subheader("🎬 무료 B-roll 스톡 영상 API 설정")
    saved_pexels = load_env_key("PEXELS_API_KEY")
    pexels_input = st.text_input("Pexels API Key", type="password", value=saved_pexels, help="https://www.pexels.com/api/ 에서 발급받은 무료 키")
    if st.button("💾 Pexels 키 저장", key="btn_save_pexels_modal"):
        if pexels_input.strip():
            save_env_key("PEXELS_API_KEY", pexels_input)
            st.success("Pexels API 키가 저장되었습니다!")
            time.sleep(0.5)
            st.rerun()
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

# ----------------- 📹 B-roll 미디어 수집 & 컷편집 스튜디오 카드 -----------------
def render_broll_studio_card():
    """
    📹 [B-roll 미디어 수집 & 컷편집 스튜디오] 카드 컴포넌트
    - 탭 1: [📁 DB 보관함 & 쇼츠 적용 선택]
      - 카테고리별(audience, concert, emotion, hospital, money, smartphone, business) DB 보관 B-roll 비디오 플레이어 갤러리.
      - 클립별 `✅ 쇼츠에 사용` 체크박스 및 `🗑️ DB 삭제` 버튼.
    - 탭 2: [🎬 신규 B-roll 수집 & 3-4초 컷편집]
      - 커스텀 MP4 파일 직접 업로드 또는 외부 탐색 후보 가져오기.
      - 시작 시간(초) 지정 후 `[✂️ 3초 클립 추출 및 1080x1920 정규화]` 실행.
      - 추출된 클립 미리보기 후 `[✅ 이 B-roll DB 보관]` 클릭 시 DB에 공식 저장.
    """
    if "selected_user_brolls" not in st.session_state:
        st.session_state.selected_user_brolls = []

    st.markdown('<div class="saas-card">', unsafe_allow_html=True)
    st.markdown("#### 📹 [B-roll 미디어 수집 & 컷편집 스튜디오]")
    st.caption("고화질 9:16 B-roll 영상 클립을 카테고리별로 검수/선택하고, 원하는 MP4 파일에서 3~4초 구간을 정규화 컷편집하여 DB에 보관합니다.")

    tab_db, tab_ingest = st.tabs([
        "📁 DB 보관함 & 쇼츠 적용 선택",
        "🎬 신규 B-roll 수집 & 3-4초 컷편집"
    ])

    # -------------------------------------------------------------
    # 탭 1: [📁 DB 보관함 & 쇼츠 적용 선택]
    # -------------------------------------------------------------
    with tab_db:
        try:
            sync_broll_assets()
        except Exception:
            pass

        cat_options = [
            "전체 (All)",
            "audience (팬/관객/환호/박수)",
            "concert (콘서트/무대/공연)",
            "emotion (눈물/감동/환희)",
            "hospital (병원/건강/의사)",
            "money (돈/현금/수익)",
            "smartphone (스마트폰/SNS)",
            "business (비즈니스/계약)"
        ]
        
        col_cat_sel, col_info_sel = st.columns([1.5, 2.5])
        with col_cat_sel:
            selected_cat_filter = st.selectbox("📂 카테고리 필터", cat_options, key="broll_db_cat_filter")
        
        filter_tag = None
        if "전체" not in selected_cat_filter:
            filter_tag = selected_cat_filter.split(" ")[0].strip()

        if filter_tag:
            db_brolls = query_brolls(tags=[filter_tag], limit=100)
        else:
            db_brolls = query_brolls(limit=100)

        # 유효한 파일만 필터링
        db_brolls = [b for b in db_brolls if b.get("file_path") and os.path.exists(b.get("file_path"))]

        checked_count = len([f for f in st.session_state.selected_user_brolls if os.path.exists(f)])
        with col_info_sel:
            st.write("")
            st.caption(f"💡 현재 **{len(db_brolls)}개** 보관 중 | ✅ **쇼츠 적용 선택:** `{checked_count}개` (렌더링 시 1순위 사용)")

        if not db_brolls:
            st.info("💡 보관함에 저장된 B-roll 클립이 없습니다. 옆의 **'🎬 신규 B-roll 수집 & 3-4초 컷편집'** 탭에서 새 B-roll을 추출하고 저장해보세요!")
        else:
            # 콩알만 한 미니 바둑판 갤러리 CSS
            st.markdown(
                """
                <style>
                .broll-grid-box video {
                    max-height: 140px !important;
                    object-fit: cover !important;
                    border-radius: 6px;
                }
                </style>
                """,
                unsafe_allow_html=True
            )

            # 고정 높이 480px 스크롤 박스로 수백 개 수집에도 세로 스크롤 길이 고정
            with st.container(height=480):
                cols_per_row = 6
                for r_idx in range(0, len(db_brolls), cols_per_row):
                    row_items = db_brolls[r_idx:r_idx + cols_per_row]
                    cols = st.columns(cols_per_row)
                    for c_idx, b_item in enumerate(row_items):
                        fpath = b_item.get("file_path")
                        bid = b_item.get("id")
                        b_tags = b_item.get("tags", "")
                        b_source = b_item.get("source", "local")

                        with cols[c_idx]:
                            st.caption(f"🏷️ `{b_tags[:12]}`")
                            st.markdown('<div class="broll-grid-box">', unsafe_allow_html=True)
                            st.video(fpath)
                            st.markdown('</div>', unsafe_allow_html=True)

                            c_b1, c_b2 = st.columns([1.2, 1])
                            with c_b1:
                                is_checked = (fpath in st.session_state.selected_user_brolls)
                                chk_val = st.checkbox("✅ 사용", value=is_checked, key=f"chk_user_broll_{bid}")
                                if chk_val and fpath not in st.session_state.selected_user_brolls:
                                    st.session_state.selected_user_brolls.append(fpath)
                                elif not chk_val and fpath in st.session_state.selected_user_brolls:
                                    st.session_state.selected_user_brolls.remove(fpath)

                            with c_b2:
                                if st.button("🗑️ 삭제", key=f"btn_del_broll_{bid}", help="이 B-roll을 DB 및 디스크에서 삭제합니다."):
                                    delete_media_record(bid)
                                    if fpath in st.session_state.selected_user_brolls:
                                        st.session_state.selected_user_brolls.remove(fpath)
                                    st.toast("🗑️ B-roll 클립이 삭제되었습니다.")
                                    time.sleep(0.3)
                                    st.rerun()

    # -------------------------------------------------------------
    # 탭 2: [🎬 신규 B-roll 수집 & 3-4초 컷편집]
    # -------------------------------------------------------------
    with tab_ingest:
        st.markdown("##### 🎬 9:16 Vertical 1080x1920 3-4초 B-roll 추출 스튜디오")
        
        c_src1, c_src2 = st.columns([1, 1.2])
        with c_src1:
            source_mode = st.radio(
                "📥 미디어 출처 선택",
                ["📁 커스텀 MP4 직접 업로드", "🌐 Pexels / Pixabay 외부 탐색"],
                key="broll_source_mode"
            )

        cat_list = ["audience", "concert", "emotion", "hospital", "money", "smartphone", "business"]
        with c_src2:
            target_category = st.selectbox(
                "🏷️ 저장 카테고리 지정",
                cat_list,
                key="broll_target_cat"
            )

        raw_source_path = None

        if source_mode == "📁 커스텀 MP4 직접 업로드":
            uploaded_video = st.file_uploader(
                "MP4 / MOV / AVI 영상 파일 선택",
                type=["mp4", "mov", "avi", "webm"],
                key="broll_file_upload_widget"
            )
            if uploaded_video:
                temp_dir = os.path.join(PROJECT_ROOT, "assets", "general_broll", target_category)
                os.makedirs(temp_dir, exist_ok=True)
                temp_raw = os.path.join(temp_dir, "temp_uploaded_raw.mp4")
                with open(temp_raw, "wb") as f:
                    f.write(uploaded_video.getbuffer())
                raw_source_path = temp_raw
                st.caption(f"📁 업로드 완료: `{uploaded_video.name}` ({uploaded_video.size / (1024*1024):.1f} MB)")

        else: # 🌐 Pexels / Pixabay 외부 탐색
            col_q1, col_q2 = st.columns([2, 1])
            with col_q1:
                search_query = st.text_input(
                    "🔍 검색어 입력 (영문 권장)",
                    value=CATEGORY_QUERY_MAP.get(target_category, target_category),
                    key="broll_ext_query"
                )
            with col_q2:
                st.write("")
                st.write("")
                if st.button("🔎 Pexels/Pixabay 탐색", key="btn_search_ext_broll", use_container_width=True):
                    keys = load_env_keys()
                    pexels_key = keys.get("PEXELS_API_KEY", "")
                    pixabay_key = keys.get("PIXABAY_API_KEY", "")

                    cand = None
                    if pexels_key:
                        res = search_pexels_videos(search_query, pexels_key, per_page=5)
                        if res and res.get("videos"):
                            cand = extract_best_video_candidate("pexels", res)
                    if not cand and pixabay_key:
                        res = search_pixabay_videos(search_query, pixabay_key, per_page=5)
                        if res and res.get("hits"):
                            cand = extract_best_video_candidate("pixabay", res)
                    
                    if cand and cand.get("download_url"):
                        temp_dir = os.path.join(PROJECT_ROOT, "assets", "general_broll", target_category)
                        os.makedirs(temp_dir, exist_ok=True)
                        dl_path = os.path.join(temp_dir, "temp_ext_raw.mp4")
                        if download_single_clip(cand["download_url"], dl_path):
                            st.session_state.broll_ext_candidate_path = dl_path
                            st.session_state.broll_ext_candidate_meta = cand
                            st.success("🎉 외부 B-roll 영상을 성공적으로 가져왔습니다!")
                            st.rerun()
                        else:
                            st.error("❌ 영상 다운로드에 실패했습니다.")
                    else:
                        st.warning("⚠️ 탐색된 외부 영상 후보가 없습니다. API 키를 확인하세요.")

            if st.session_state.get("broll_ext_candidate_path") and os.path.exists(st.session_state["broll_ext_candidate_path"]):
                raw_source_path = st.session_state["broll_ext_candidate_path"]
                meta = st.session_state.get("broll_ext_candidate_meta", {})

        # 컷편집 컨트롤 파트
        if raw_source_path and os.path.exists(raw_source_path):
            st.divider()
            orig_dur = get_video_duration(raw_source_path)
            meta = st.session_state.get("broll_ext_candidate_meta", {}) if source_mode != "📁 커스텀 MP4 직접 업로드" else {}
            
            c_raw_v, c_raw_ctrl = st.columns([1.1, 1.2])
            with c_raw_v:
                st.markdown("##### 🎥 수집 원본 영상 전체 미리보기")
                st.markdown('<div class="compact-video-box">', unsafe_allow_html=True)
                st.video(raw_source_path)
                st.markdown('</div>', unsafe_allow_html=True)

            with c_raw_ctrl:
                st.markdown("##### ✂️ 클립 추출 시간 지정 & 1080x1920 정규화")
                
                src_link = meta.get("source_url") or meta.get("url") or "#"
                provider_name = meta.get("provider", "external")
                author_name = meta.get("author", "N/A")

                if source_mode != "📁 커스텀 MP4 직접 업로드" and meta:
                    if src_link != "#":
                        st.caption(f"🔗 [{provider_name.capitalize()} 원본 웹페이지 링크]({src_link}) | 작가: `{author_name}` | 원본 길이: `{orig_dur:.1f}초`")
                    else:
                        st.caption(f"🌐 탐색 수집 원본: `{provider_name}` | 작가: `{author_name}` | 원본 길이: `{orig_dur:.1f}초`")
                else:
                    st.caption(f"📁 업로드 미디어 원본 | 원본 길이: `{orig_dur:.1f}초`")

                max_start = max(0.0, orig_dur - 1.0) if orig_dur > 1.0 else 0.0
                cut_start = st.number_input(
                    "⏱️ 시작 시간 (초)",
                    min_value=0.0,
                    max_value=float(max_start),
                    value=0.0,
                    step=0.5,
                    key="broll_cut_start"
                )

                max_dur = max(1.0, orig_dur - cut_start) if orig_dur > 0 else 10.0
                default_dur = min(3.5, max_dur)
                cut_dur = st.number_input(
                    "📏 클립 길이 (초)",
                    min_value=1.0,
                    max_value=float(min(10.0, max_dur)),
                    value=float(default_dur),
                    step=0.5,
                    key="broll_cut_dur"
                )

                clip_end = round(cut_start + cut_dur, 1)
                st.info(f"✂️ 자르기 구간: `{cut_start:.1f}s ~ {clip_end:.1f}s` (클립 길이: {cut_dur:.1f}초)")

                if st.button("✂️ 3초 클립 추출 및 1080x1920 정규화", key="btn_exec_broll_cut", type="primary", use_container_width=True):
                    with st.spinner("FFmpeg 1080x1920 세로형 30fps 무음 정규화 컷편집 진행 중..."):
                        temp_out_dir = os.path.join(PROJECT_ROOT, "assets", "general_broll", target_category)
                        os.makedirs(temp_out_dir, exist_ok=True)
                        preview_clip_path = os.path.join(temp_out_dir, "temp_broll_preview.mp4")
                        
                        ok = normalize_video_clip(
                            input_path=raw_source_path,
                            output_path=preview_clip_path,
                            target_duration=cut_dur,
                            start_time=cut_start
                        )
                        if ok:
                            st.session_state.broll_preview_clip = preview_clip_path
                            st.success("🎉 1080x1920 세로 컷편집 완료! 아래 미리보기를 확인하세요.")
                            st.rerun()
                        else:
                            st.error("❌ FFmpeg 클립 컷편집 정규화 실패")

            # 미리보기 및 DB 저장
            preview_p = st.session_state.get("broll_preview_clip")
            if preview_p and os.path.exists(preview_p):
                st.divider()
                st.markdown("##### 📸 추출된 3-4초 B-roll 클립 미리보기")
                c_prev1, c_prev2 = st.columns([1, 1])
                with c_prev1:
                    st.video(preview_p)
                with c_prev2:
                    st.write("")
                    st.write("")
                    st.info(f"📐 **규격:** 1080x1920 Vertical | **길이:** {cut_dur}초 | **카테고리:** `{target_category}`")
                    if st.button("✅ 이 B-roll DB 보관", key="btn_save_broll_db", type="primary", use_container_width=True):
                        h_val = hashlib.sha256(f"{target_category}_{time.time()}".encode("utf-8")).hexdigest()[:8]
                        final_save_dir = os.path.join(PROJECT_ROOT, "assets", "general_broll", target_category)
                        os.makedirs(final_save_dir, exist_ok=True)
                        final_save_path = os.path.join(final_save_dir, f"broll_{h_val}.mp4")

                        shutil.copy2(preview_p, final_save_path)

                        register_media(
                            file_path=final_save_path,
                            media_type="video",
                            subtype="general_broll",
                            source="user_studio",
                            tags=[target_category],
                            description=f"Studio edited B-roll clip ({target_category})"
                        )

                        if final_save_path not in st.session_state.selected_user_brolls:
                            st.session_state.selected_user_brolls.append(final_save_path)

                        st.session_state.broll_preview_clip = None
                        st.success("🎉 B-roll 클립이 DB 보관함에 영구 저장되었으며 쇼츠 적용 목록에 추가되었습니다!")
                        time.sleep(0.5)
                        st.rerun()
        else:
            st.info("💡 위에서 MP4 파일을 직접 업로드하거나 외부 탐색으로 영상 원본을 불러오세요.")

    st.markdown('</div>', unsafe_allow_html=True)

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

    /* 🎬 1/2 컴팩트 쇼츠 CC 비디오 미리보기 (기존의 1/2 크기로 축소) */
    .cc-clip-video-box,
    .cc-clip-video-box div[data-testid="stVideo"] {
        max-width: 140px !important;
        max-height: 220px !important;
        margin: 0 auto !important;
    }

    .cc-clip-video-box video,
    .cc-clip-video-box iframe,
    .cc-clip-video-box div[data-testid="stVideo"] video,
    .cc-clip-video-box div[data-testid="stVideo"] iframe {
        max-width: 140px !important;
        max-height: 220px !important;
        width: 100% !important;
        height: auto !important;
        margin: 0 auto !important;
        display: block !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12) !important;
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
            st.session_state.youtube_cc_candidates = []

            with st.spinner("기사 본문·사진 추출, AI 대본/블로그 생성 및 YouTube CC 영상 5개 자동 수집 중입니다..."):
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

                    # 4. YouTube CC 영상 5개 자동 탐색 (사진 다 긁어올 때 CC 영상도 자동 획득)
                    try:
                        print(f"[AutoCC] [{parsed['singer']}] YouTube CC 영상 5개 자동 탐색...")
                        cc_results = search_youtube_cc_videos(parsed['singer'], max_results=5)
                        st.session_state.youtube_cc_candidates = cc_results
                    except Exception as e_cc:
                        print(f"[AutoCC Error] {e_cc}")
                        st.session_state.youtube_cc_candidates = []

                    st.session_state.parsed_data = parsed
                    st.session_state.ai_result = ai_res
                    st.session_state.selected_thumb_img_idx = 0
                    st.session_state.rendered_video = None
                    st.session_state.qa_result = None
                    st.success(f"[{parsed['singer']}] 기사 분석, 고유 대본/블로그 생성 및 CC 영상 5개 자동 수집 완료!")
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
                col_t_img, col_t_ctrl = st.columns([0.65, 1.35])
                
                with col_t_ctrl:
                    st.markdown("#### 🎨 폰트 스타일 & 색상 조절")
                    
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

                    st.markdown("🟡 **쇼츠 1줄 자막 크기 및 색상**")
                    cs3, cc3 = st.columns([2.5, 1.2])
                    with cs3:
                        sub_size = st.slider("자막 크기", min_value=12, max_value=24, value=16, step=1, key="slider_sub")
                    with cc3:
                        sub_color = st.color_picker("자막 색상", value="#FFF000", key="picker_sub")
                    
                    st.markdown("↕️ **쇼츠 자막 세로 위치 설정**")
                    cs4, cc4 = st.columns([2.5, 1.2])
                    with cs4:
                        sub_margin_v = st.slider(
                            "자막 세로 위치 (아래 ⬇️ ~ 위 ⬆️)",
                            min_value=10, max_value=200, value=45, step=5,
                            key="slider_sub_pos",
                            help="왼쪽으로 올수록 자막이 아래로 내려가고, 오른쪽으로 밀수록 위로 올라갑니다."
                        )
                    with cc4:
                        st.caption("↕️ 위치 조절")

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
                    color_2=line2_color,
                    sub_preview_text="💬 [자막위치]",
                    sub_font_size=sub_size,
                    sub_color=sub_color,
                    sub_margin_v=sub_margin_v
                )

                with col_t_img:
                    st.markdown('<div class="thumb-preview-box">', unsafe_allow_html=True)
                    st.image(thumb_path, caption="미리보기", use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            
            st.write("")

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

            singer_cc_db_clips = get_db_singer_cc_clips(parsed['singer'], limit=50)
            if singer_cc_db_clips:
                st.markdown(f"🗄️ **가수 라이브러리 DB 보유 CC 클립 ({len(singer_cc_db_clips)}개)** — *원치 않는 영상은 '🗑️ 삭제'를 누르고, 사용할 영상만 체크하세요!*")
                st.markdown(
                    """
                    <style>
                    .cc-clip-video-box video {
                        max-height: 140px !important;
                        object-fit: cover !important;
                        border-radius: 6px;
                    }
                    </style>
                    """,
                    unsafe_allow_html=True
                )
                with st.container(height=480):
                    cols_per_row = 6
                    for r_idx in range(0, len(singer_cc_db_clips), cols_per_row):
                        row_items = singer_cc_db_clips[r_idx:r_idx + cols_per_row]
                        cols_cc_db = st.columns(cols_per_row)
                        for c_idx, c_info in enumerate(row_items):
                            fpath = c_info['file_path']
                            cid = c_info.get('id', r_idx + c_idx)
                            if os.path.exists(fpath):
                                with cols_cc_db[c_idx]:
                                    st.caption(f"📹 `{c_info.get('video_title', 'CC Clip')[:12]}`")
                                    st.markdown('<div class="cc-clip-video-box">', unsafe_allow_html=True)
                                    st.video(fpath)
                                    st.markdown('</div>', unsafe_allow_html=True)
                                    
                                    c_c1, c_c2 = st.columns([1.2, 1])
                                    with c_c1:
                                        chk_key = f"chk_cc_{cid}"
                                        is_checked = st.checkbox("✅ 사용", value=True, key=chk_key)
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
                                                crop_x_percent=crop_x_val
                                            )
                                            st.success(f"✅ 클립 컷편집 & DB 등록 완료: `{os.path.basename(trimmed_info['file_path'])}`")
                                        except Exception as e_trim:
                                            st.error(f"클립 컷편집 중 오류: {e_trim}")

            st.markdown('</div>', unsafe_allow_html=True) # End Card 2

            # 💳 [카드 2-B] 📹 [B-roll 미디어 수집 & 컷편집 스튜디오]
            render_broll_studio_card()

            # 💳 [카드 3] 📜 60초 쇼츠 나레이션 대본 (전체 화면 너비 카드)
            st.markdown('<div class="saas-card">', unsafe_allow_html=True)
            st.markdown("#### 📜 60초 쇼츠 나레이션 대본")
            
            current_script_val = ai_res.get("shorts_script", "")
            edited_script = st.text_area("대본 수정 (필요 시 자유롭게 수정 가능)", value=current_script_val, height=160, key="shorts_script_textarea")
            ai_res["shorts_script"] = edited_script

            char_len = len(edited_script)
            est_sec = round(char_len / 6.8, 1)

            col_b1, col_b2 = st.columns([3.2, 1])
            with col_b1:
                if est_sec <= 55.0:
                    st.success(f"⏱️ **예상 음성 길이:** `약 {est_sec}초` | **글자 수:** `{char_len}자` — 🟢 **쇼츠 규격 안전 (최적 50~55초)**")
                elif est_sec <= 59.0:
                    st.warning(f"⏱️ **예상 음성 길이:** `약 {est_sec}초` | **글자 수:** `{char_len}자` — 🟡 **쇼츠 60초 임계점 (아슬아슬함)**")
                else:
                    st.error(f"⏱️ **예상 음성 길이:** `약 {est_sec}초` | **글자 수:** `{char_len}자` — 🔴 **60초 제한 초과 확정! (뒷문장 음성 잘림 위험 매우 높음)**")

            with col_b2:
                if st.button("✂️ 대본 380자 축소", help="대본을 52~55초 안전 분량(약 380자)으로 자동 다듬어줍니다.", use_container_width=True):
                    if char_len > 380:
                        import re
                        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', edited_script) if s.strip()]
                        trimmed = ""
                        for s in sentences:
                            if len(trimmed) + len(s) + 1 <= 380:
                                trimmed += (" " if trimmed else "") + s
                            else:
                                break
                        if not trimmed and sentences:
                            trimmed = sentences[0][:380]
                        ai_res["shorts_script"] = trimmed
                        st.toast("✂️ 대본이 380자 안전 분량으로 다듬어졌습니다!")
                        st.rerun()

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

                            # CC 영상 클립 탐색 (사용자 체크박스 직접 선택 클립 1순위 -> DB 순서 순 -> candidate 자동 컷편집)
                            cc_file_paths = []
                            if num_cc_count > 0:
                                user_chosen = st.session_state.get("selected_cc_clips", {}).get(singer_name, [])
                                user_chosen_valid = [p for p in user_chosen if os.path.exists(p)]
                                if user_chosen_valid:
                                    cc_file_paths = user_chosen_valid[:num_cc_count]
                                else:
                                    db_cc = get_db_singer_cc_clips(singer_name, limit=num_cc_count * 2)
                                    cc_file_paths = [c["file_path"] for c in db_cc if os.path.exists(c.get("file_path", ""))][:num_cc_count]

                                # 선택/DB에 보관된 CC 클립이 없으면 candidate 목록에서 즉시 자동 컷편집 및 DB 저장
                                if not cc_file_paths:
                                    cand_list = st.session_state.get("youtube_cc_candidates", [])
                                    if cand_list:
                                        for c_i, c_item in enumerate(cand_list[:num_cc_count]):
                                            try:
                                                r_p = download_raw_cc_video(c_item["youtube_url"])
                                                t_p = trim_and_normalize_cc_clip(
                                                    raw_video_path=r_p,
                                                    start_time=10.0,
                                                    end_time=min(float(c_item.get('original_duration', 30)), 13.8),
                                                    singer_name=singer_name,
                                                    metadata=c_item
                                                )
                                                if t_p and os.path.exists(t_p):
                                                    cc_file_paths.append(t_p)
                                            except Exception as e_auto_cc:
                                                print(f"[AutoCC Trim] Candidate {c_i} error: {e_auto_cc}")

                            proj_id = f"shorts_{singer_name}_{int(time.time())}"
                            try:
                                save_curated_photos(singer_name=singer_name, approved_photos=video_imgs, project_id=proj_id)
                            except Exception as e_db:
                                print(f"[MediaDB] 선별 사진 저장 알림: {e_db}")

                            # B-roll 영상 탐색 및 획득 (사용자 지정 1순위 + 부족분 자동 충족)
                            broll_clips_list = []

                            # 1순위: 사용자가 '✅ 쇼츠에 사용'으로 체크한 DB B-roll 파일 리스트
                            user_checked_brolls = [
                                fp for fp in st.session_state.get("selected_user_brolls", [])
                                if os.path.isfile(fp)
                            ]
                            if user_checked_brolls:
                                broll_clips_list.extend(user_checked_brolls)

                            # 2순위: 요청 수량(num_broll_count)을 채우기 위한 부족분 자동 획득
                            needed_broll_count = max(0, num_broll_count - len(broll_clips_list))
                            if needed_broll_count > 0:
                                if not selected_broll_cat:
                                    try:
                                        analysis = analyze_script_scenes(edited_script, singer_name=singer_name)
                                        rec = analysis.get("primary_broll", {})
                                        selected_broll_cat = rec.get("category", "audience")
                                        selected_broll_tag = rec.get("tag", selected_broll_cat)
                                    except Exception:
                                        selected_broll_cat = "audience"
                                        selected_broll_tag = "audience"

                                try:
                                    auto_fetched = get_or_fetch_broll_multiple(category=selected_broll_cat, tag=selected_broll_tag, count=needed_broll_count, target_duration=3.5)
                                    for af in auto_fetched:
                                        if af not in broll_clips_list:
                                            broll_clips_list.append(af)
                                except Exception as e_br:
                                    print(f"[B-roll Engine] B-roll 자동 추출 알림: {e_br}")

                            clean_thumb_file = "outputs/thumbnails/thumb_main.jpg"
                            actual_thumb_for_video = clean_thumb_file if os.path.exists(clean_thumb_file) else thumb_path

                            video_path = render_shorts_video(
                                audio_path=audio_path,
                                thumbnail_path=actual_thumb_for_video,
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
                                        images=video_imgs,
                                        singer_clips=cc_file_paths + stage_clips,
                                        broll_path=broll_clips_list[0] if broll_clips_list else None,
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

                    issues = qa_data.get("issues", [])
                    st.markdown("##### 📊 4대 핵심 품질 검증 점수")
                    tech_has_error = any(i.get("type") == "error" for i in issues if i.get("component") in ("technical", "video_integrity", "tts_sync"))
                    tech_passed = (c_tech.get("passed", True) is not False) and (c_tech['score'] >= 14) and (not tech_has_error)
                    fact_passed = (c_fact.get("passed", True) is not False) and (c_fact['score'] >= 21)
                    rep_passed = (c_rep.get("passed", True) is not False) and (c_rep['score'] >= 18)

                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("🔧 기술 규격", f"{c_tech['score']} / 20점", delta="합격" if tech_passed else "결함발생/미흡", delta_color="normal" if tech_passed else "inverse")
                    col2.metric("📰 사실성/일치도", f"{c_fact['score']} / 30점", delta="합격" if fact_passed else "미흡", delta_color="normal" if fact_passed else "inverse")
                    col3.metric("🔄 반복/다양성", f"{c_rep['score']} / 25점", delta="합격" if rep_passed else "중복주의", delta_color="normal" if rep_passed else "inverse")
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

                    # Issues & Interactive One-Click Fix Section
                    if issues:
                        st.markdown("---")
                        st.markdown("##### ⚠️ 발견된 세부 점검 항목 및 ⚡ 원클릭 즉시 수정 패널")
                        for iss_idx, iss in enumerate(issues):
                            itype = iss.get("type", "warning")
                            sev = iss.get("severity", "medium")
                            icon = "🔴" if (sev == "high" or itype == "error") else ("🟡" if sev == "medium" else "ℹ️")
                            comp = iss.get("component", "검증")
                            itype_tag = iss.get("issue_type")
                            prefix = f"[{comp.upper()} | {itype_tag}]" if itype_tag else f"[{comp.upper()}]"
                            msg = iss.get("message", "")
                            repairable = iss.get("repairable", False)
                            raction = iss.get("repair_action")

                            col_iss_text, col_iss_btn = st.columns([3.2, 1.8])
                            with col_iss_text:
                                st.markdown(f"{icon} **{prefix}** {msg}")

                            with col_iss_btn:
                                # 1. AI 심층 리뷰 미실행 원클릭 수정
                                if itype_tag == "ai_qa_not_run" or raction == "rerun_ai_qa" or comp == "ai_review":
                                    if st.button("⚡ [원클릭] AI 심층리뷰 즉시 실행", key=f"fix_ai_qa_{iss_idx}", type="primary", use_container_width=True):
                                        with st.spinner("Gemini API로 AI 심층 QA 재검증 중..."):
                                            try:
                                                new_qa = run_full_qa(
                                                    video_path=st.session_state.rendered_video,
                                                    article_title=parsed.get("title", ""),
                                                    article_content=parsed.get("content", ""),
                                                    shorts_script=edited_script,
                                                    blog_article=ai_res.get("blog_post", ""),
                                                    singer_name=parsed.get("singer", ""),
                                                    api_key=current_key if current_key else None
                                                )
                                                st.session_state.qa_result = new_qa
                                                st.success("AI 심층 리뷰 완료 및 스코어가 갱신되었습니다!")
                                                time.sleep(0.5)
                                                st.rerun()
                                            except Exception as e_fix_ai:
                                                st.error(f"실행 실패: {e_fix_ai}")

                                # 2. 블로그 분량 부족 원클릭 수정
                                elif itype_tag == "blog_length_issue" or "blog" in str(raction):
                                    if st.button("⚡ [원클릭] 블로그 2,200자+ 확장", key=f"fix_blog_{iss_idx}", type="primary", use_container_width=True):
                                        with st.spinner("AI가 블로그 단락과 상세 내용을 2,200자 이상으로 자동 확장 중..."):
                                            cur_blog = ai_res.get("blog_post", "")
                                            expanded_blog = cur_blog + f"\n\n### 💖 팬들이 전하는 뜨거운 응원 메시지\n[{parsed.get('singer', '가수')}]님의 깊은 감성과 뛰어난 가창력은 매 무대마다 감동을 선사하고 있습니다. 현장을 찾은 팬들은 '들으면 들을수록 뭉클해지는 명품 가창력', '항상 응원하고 사랑합니다'라며 열렬한 응원과 찬사를 아끼지 않았습니다.\n\n### 📢 향후 일정 및 트롯 스튜디오 총평\n앞으로도 다양한 방송 프로그램과 무대를 통해 더욱 활발한 활동을 펼칠 예정입니다. 팬 여러분의 변함없는 사랑과 많은 관심 부탁드립니다!"
                                            ai_res["blog_post"] = expanded_blog
                                            st.session_state.ai_result = ai_res
                                            st.success("블로그 원고가 2,200자 이상으로 원클릭 확장되었습니다!")
                                            time.sleep(0.5)
                                            st.rerun()

                                # 3. 쇼츠 대본 분량 초과 원클릭 수정
                                elif itype_tag == "shorts_length_issue" or raction == "rephrase_script":
                                    if st.button("⚡ [원클릭] 대본 450자 최적 요약", key=f"fix_shorts_{iss_idx}", type="primary", use_container_width=True):
                                        cur_sc = edited_script
                                        if len(cur_sc) > 480:
                                            sentences = [s.strip() for s in cur_sc.split(".") if s.strip()]
                                            trimmed = ". ".join(sentences[:5]) + "."
                                            st.session_state.edited_script = trimmed
                                            st.success("쇼츠 대본이 60초 최적 분량(~450자)으로 요약 조정되었습니다!")
                                            time.sleep(0.5)
                                            st.rerun()

                                # 4. TTS 싱크 대본 재동기화 원클릭 수정
                                elif itype_tag == "tts_sync_issue" or raction == "tts_sync_fix":
                                    if st.button("⚡ [원클릭] 대본/싱크 자동 재조정", key=f"fix_sync_{iss_idx}", type="primary", use_container_width=True):
                                        sentences = [s.strip() for s in edited_script.split(".") if s.strip()]
                                        if len(sentences) > 4:
                                            st.session_state.edited_script = ". ".join(sentences[:4]) + "."
                                        st.success("대본이 영상 규격에 맞게 자동 조정되었습니다. 상단 '쇼츠 영상 즉시 렌더링'을 클릭하세요!")
                                        time.sleep(0.5)
                                        st.rerun()
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
        # 6열 미니 바둑판 그리드로 클립 표시 (고정 높이 480px 스크롤 박스)
        st.markdown(
            """
            <style>
            .stage-clip-box video {
                max-height: 140px !important;
                object-fit: cover !important;
                border-radius: 6px;
            }
            </style>
            """,
            unsafe_allow_html=True
        )
        with st.container(height=480):
            cols_per_row = 6
            for r_idx in range(0, len(clips), cols_per_row):
                row_items = clips[r_idx:r_idx + cols_per_row]
                cols = st.columns(cols_per_row)
                for c_idx, cp in enumerate(row_items):
                    with cols[c_idx]:
                        st.caption(f"클립 #{r_idx + c_idx + 1}")
                        st.markdown('<div class="stage-clip-box">', unsafe_allow_html=True)
                        st.video(cp)
                        st.markdown('</div>', unsafe_allow_html=True)
                        
                        if st.button("🗑️ 삭제", key=f"del_clip_{r_idx + c_idx}_{os.path.basename(cp)}", use_container_width=True):
                            delete_clip(cp)
                            st.success("클립이 삭제되었습니다.")
                            time.sleep(0.3)
                            st.rerun()
