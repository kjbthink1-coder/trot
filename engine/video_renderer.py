import os
import json
import subprocess
from typing import Optional, Union, List, Dict, Any
import imageio_ffmpeg
import cv2
import numpy as np
from PIL import Image

LAST_TIMELINE_SEGMENTS: List[Dict[str, Any]] = []

def get_last_timeline_segments() -> List[Dict[str, Any]]:
    """최근 렌더링된 쇼츠 영상의 타임라인 세그먼트 메타데이터 목록을 반환합니다."""
    global LAST_TIMELINE_SEGMENTS
    return list(LAST_TIMELINE_SEGMENTS)


def get_media_duration(file_path: str) -> float:
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg_exe, "-i", file_path]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, errors='ignore')
    for line in res.stderr.split('\n'):
        if "Duration:" in line:
            parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return 50.0

def create_face_aware_base_image(
    img_path: str,
    target_w: int = 1080,
    target_h: int = 1920,
    out_path: str = None
) -> str:
    """
    OpenCV Haar Cascade 얼굴 인식을 활용하여
    가로/정방형/세로 사진 모두 가수의 얼굴과 상반신이 9:16(1080x1920) 숏츠 화면 중심에
    완벽히 오도록 스마트 크롭 & 리사이즈합니다.
    - 얼굴이 프레임 밖으로 짤리거나 엉뚱한 배경/벽면이 찍히는 현상을 원천 방지
    """
    if not img_path or not os.path.exists(img_path):
        return img_path
    if out_path is None:
        out_path = img_path

    try:
        # PIL을 통해 이미지 로드 (Windows 한글 폴더 경로 100% 호환)
        with Image.open(img_path) as pim:
            im_cv = cv2.cvtColor(np.array(pim.convert("RGB")), cv2.COLOR_RGB2BGR)

        if im_cv is None:
            return img_path

        h_orig, w_orig = im_cv.shape[:2]
        gray = cv2.cvtColor(im_cv, cv2.COLOR_BGR2GRAY)
        
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
        
        if len(faces) > 0:
            # 가장 면적이 큰 메인 얼굴 선택 (가수 주인공)
            faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
            fx, fy, fw, fh = faces[0]
            face_cx = fx + fw / 2.0
            face_cy = fy + fh / 2.0
        else:
            # 얼굴 미검출 시 인물 사진 일반적 구도(가로 중앙, 세로 상단 35%) 적용
            face_cx = w_orig / 2.0
            face_cy = h_orig * 0.35

        target_ratio = target_w / target_h
        orig_ratio = w_orig / h_orig

        if orig_ratio > target_ratio:
            # 가로형 사진 (보도사진, 16:9, 4:3 등): 세로 높이 기준으로 9:16 너비 크롭
            crop_h = h_orig
            crop_w = int(h_orig * target_ratio)
            # 얼굴 중심이 크롭 영역의 중앙에 위치하도록 계산
            crop_x1 = max(0, min(int(face_cx - crop_w / 2.0), w_orig - crop_w))
            crop_x2 = crop_x1 + crop_w
            cropped = im_cv[0:crop_h, crop_x1:crop_x2]
        else:
            # 세로형 사진: 가로 너비 기준으로 9:16 높이 크롭
            crop_w = w_orig
            crop_h = int(w_orig / target_ratio)
            # 얼굴이 9:16 프레임의 상단 약 28%~30% 황금비율 영역에 위치하도록 계산
            crop_y1 = max(0, min(int(face_cy - crop_h * 0.30), h_orig - crop_h))
            crop_y2 = crop_y1 + crop_h
            cropped = im_cv[crop_y1:crop_y2, 0:crop_w]

        out_w = max(target_w, 1200)
        out_h = int(out_w * (target_h / target_w))
        resized = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        # PIL을 통해 JPEG 저장 (Windows 한글 경로 호환 보장)
        Image.fromarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)).save(out_path, "JPEG", quality=95)
        return os.path.abspath(out_path)
    except Exception as e:
        print(f"[Face Aware Crop Warning] {e}")
        return img_path

KEN_BURNS_MOTIONS = [
    "zoom_in",
    "pan_left_right",
    "zoom_out",
    "pan_bottom_top",
    "pan_right_left",
    "pan_top_bottom"
]

def build_ken_burns_filter(motion: str, width: int, height: int, dur: float) -> str:
    """
    정지 사진에 영웅대학/서진대학 스타일의 다이내믹 켄 번즈(Ken Burns) 카메라 무빙 적용
    - 사전 얼굴 중심 스마트 크롭(9:16)된 이미지를 기반으로,
      가수의 얼굴과 상반신이 프레임 밖으로 나가지 않도록 우아하고 안정적인 무빙 보장
    """
    d = max(1.0, dur)

    if motion == "zoom_in":
        # 중앙(가수 얼굴)을 향해 1.0x -> 1.20x 부드러운 클로즈업 줌인
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"scale=w='2*trunc({width}*(1+0.20*t/{d:.2f})/2)':h='2*trunc({height}*(1+0.20*t/{d:.2f})/2)':eval=frame,"
            f"crop={width}:{height}:(in_w-{width})/2:(in_h-{height})/2,format=yuv420p"
        )
    elif motion == "zoom_out":
        # 클로즈업(1.20x)에서 시원하게 줌아웃 (가수 전신과 무대 조명 공개)
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"scale=w='2*trunc({width}*(1.20-0.20*t/{d:.2f})/2)':h='2*trunc({height}*(1.20-0.20*t/{d:.2f})/2)':eval=frame,"
            f"crop={width}:{height}:(in_w-{width})/2:(in_h-{height})/2,format=yuv420p"
        )
    elif motion == "pan_bottom_top":
        # 상반신/마이크에서 상단(가수 얼굴)으로 수직 훑어 올리기 (아래->위 패닝)
        return (
            f"scale={width}:{height + 220}:force_original_aspect_ratio=increase,crop={width}:{height + 220},"
            f"crop=w={width}:h={height}:x='(in_w-{width})/2':y='(1-t/{d:.2f})*(in_h-{height})',format=yuv420p"
        )
    elif motion == "pan_top_bottom":
        # 상단(얼굴)에서 아래(의상/무대)로 수직 훑어 내리기 (위->아래 패닝)
        return (
            f"scale={width}:{height + 220}:force_original_aspect_ratio=increase,crop={width}:{height + 220},"
            f"crop=w={width}:h={height}:x='(in_w-{width})/2':y='(t/{d:.2f})*(in_h-{height})',format=yuv420p"
        )
    elif motion == "pan_left_right":
        # 좌 -> 우 부드러운 140px 슬라이드 글라이드
        return (
            f"scale={width + 140}:{height}:force_original_aspect_ratio=increase,crop={width + 140}:{height},"
            f"crop=w={width}:h={height}:x='(t/{d:.2f})*(in_w-{width})':y='(in_h-{height})/2',format=yuv420p"
        )
    else:  # pan_right_left
        # 우 -> 좌 부드러운 140px 슬라이드 글라이드
        return (
            f"scale={width + 140}:{height}:force_original_aspect_ratio=increase,crop={width + 140}:{height},"
            f"crop=w={width}:h={height}:x='(1-t/{d:.2f})*(in_w-{width})':y='(in_h-{height})/2',format=yuv420p"
        )

def hex_to_ass_color(hex_str: str) -> str:
    """CSS #RRGGBB 색상을 ASS 자막 포맷 (&HAABBGGRR)으로 변환합니다."""
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 6:
        r, g, b = hex_str[0:2], hex_str[2:4], hex_str[4:6]
        return f"&H00{b}{g}{r}".upper()
    return "&H0000FFFF"

def render_shorts_video(
    audio_path: str,
    thumbnail_path: str,
    image_paths: list[str],
    stock_video_path: str = None,
    singer_clips: list[str] = None,
    singer_cc_clips: list[str] = None,
    broll_video_path: str = None,
    broll_video_paths: list[str] = None,
    srt_path: str = None,
    output_path: str = "outputs/videos/shorts_final.mp4",
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    sub_font_size: int = 16,
    sub_color: str = "#FFF000",
    return_timeline: bool = False
) -> Union[str, tuple[str, list[dict]]]:
    """
    고대비 썸네일, 2.5~3.0초 단위 다이내믹 켄 번즈(줌/패닝) 사진 컷들, 가수 무대 짤(클립),
    가수별 3~4초 CC 영상 클립, 스톡 리액션 영상 / B-roll 영상, Edge-TTS 음성을 결합하여 영웅대학 스타일의 고몰입 세로 쇼츠 MP4를 렌더링합니다.
    - Master Clock: TTS 오디오 길이 기준 strictly <= 60.0s 바운딩
    - timeline_segments 메타데이터 생성 및 shorts_timeline.json 자동 저장
    """
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    
    # 60초 마스터 클락 제어: Edge-TTS 오디오 길이 기준으로 엄격히 바운딩
    raw_duration = get_media_duration(audio_path)
    if raw_duration > 60.0:
        print(f"[Video Renderer] 경고: 오디오 길이({raw_duration:.2f}초)가 유튜브 쇼츠 제한(60초)을 초과하여 60.0초로 제한(clamp)합니다.")
        total_duration = 60.0
    elif raw_duration <= 0.0:
        total_duration = 50.0
    else:
        total_duration = round(raw_duration, 2)
    print(f"[Video Renderer] 최종 기준 재생시간(Master Clock): {total_duration:.2f}초 (원본: {raw_duration:.2f}초)")

    temp_dir = os.path.abspath("outputs/temp_render")
    os.makedirs(temp_dir, exist_ok=True)

    # [핵심] 모든 이미지와 썸네일을 표준 baseline RGB JPEG로 정규화
    from PIL import Image
    norm_thumb_path = os.path.join(temp_dir, "norm_thumb.jpg")
    try:
        with Image.open(thumbnail_path) as im:
            im.convert("RGB").save(norm_thumb_path, "JPEG", quality=95)
        thumbnail_path = norm_thumb_path
    except Exception:
        pass

    raw_images = [os.path.abspath(img) for img in image_paths if os.path.exists(img)]
    if not raw_images:
        raw_images = [thumbnail_path]

    valid_images = []
    for idx, img_p in enumerate(raw_images):
        norm_p = os.path.join(temp_dir, f"norm_img_{idx}.jpg")
        try:
            processed_p = create_face_aware_base_image(img_p, target_w=width, target_h=height, out_path=norm_p)
            if processed_p and os.path.exists(processed_p):
                valid_images.append(processed_p)
            else:
                with Image.open(img_p) as im:
                    im.convert("RGB").save(norm_p, "JPEG", quality=95)
                valid_images.append(norm_p)
        except Exception:
            valid_images.append(img_p)

    valid_singer_clips = [os.path.abspath(c) for c in (singer_clips or []) if os.path.exists(c)]
    valid_cc_clips = [os.path.abspath(c) for c in (singer_cc_clips or []) if os.path.exists(c)]

    all_broll_paths = []
    if broll_video_paths:
        all_broll_paths.extend([os.path.abspath(bp) for bp in broll_video_paths if os.path.exists(bp)])
    if broll_video_path and os.path.exists(broll_video_path):
        abs_bp = os.path.abspath(broll_video_path)
        if abs_bp not in all_broll_paths:
            all_broll_paths.append(abs_bp)

    thumb_dur = 2.0
    clip_dur = 3.5

    # 영상 클립 풀 구성 (가수 무대 짤 + 가수 CC 영상 클립 + B-roll 리스트 + 스톡 영상)
    active_video_clips = []
    for sc in valid_singer_clips:
        active_video_clips.append(("stage_clip", sc))
    for cc in valid_cc_clips:
        active_video_clips.append(("singer_cc_video", cc))
    for br in all_broll_paths:
        active_video_clips.append(("broll", br))
    if stock_video_path and os.path.exists(stock_video_path):
        active_video_clips.append(("stock", os.path.abspath(stock_video_path)))

    print(f"[Video Renderer] 커스텀 영상 클립 조합 구성 완료 (총 {len(active_video_clips)}개 클립: Stage={len(valid_singer_clips)}, CC={len(valid_cc_clips)}, Broll={len(all_broll_paths)})")

    total_video_dur = len(active_video_clips) * clip_dur
    min_img_total = len(valid_images) * 2.0

    if thumb_dur + total_video_dur + min_img_total > total_duration:
        clip_dur = max(2.0, (total_duration - thumb_dur - min_img_total) / max(1, len(active_video_clips)))
        total_video_dur = len(active_video_clips) * clip_dur

    remaining_img_time = max(len(valid_images) * 2.0, total_duration - thumb_dur - total_video_dur)

    # [핵심] 영웅대학 공식: 사진 1장당 2.5~3.0초 단위 빠른 컷 전환 (총 14~18컷)
    target_photo_cut_dur = 2.8
    num_photo_cuts = max(len(valid_images), int(round(remaining_img_time / target_photo_cut_dur)))
    img_dur = remaining_img_time / num_photo_cuts
    frames_per_cut = int(round(img_dur * fps))

    print(f"[Video Renderer] 다이내믹 켄 번즈 컷: 총 {num_photo_cuts}컷 (각 {img_dur:.2f}초, {frames_per_cut}프레임) | 영상클립 {len(active_video_clips)}개")

    # (1) 썸네일 클립 (첫 2초 타이틀 카드)
    thumb_clip = os.path.join(temp_dir, "clip_0_thumb.mp4")
    cmd_thumb = [
        ffmpeg_exe, "-y",
        "-loop", "1", "-i", os.path.abspath(thumbnail_path),
        "-t", str(thumb_dur),
        "-vf", f"scale={width}:{height},format=yuv420p,setsar=1",
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-video_track_timescale", "30000",
        "-an",
        thumb_clip
    ]
    subprocess.run(cmd_thumb, check=True, capture_output=True)
    thumb_obj = {
        "file": thumb_clip,
        "type": "photo",
        "path": thumbnail_path,
        "duration": thumb_dur
    }

    # (2) 기사 및 가수 사진 슬라이드 클립들 (영웅대학 스타일 6대 켄 번즈 무빙 적용)
    img_clips = []
    img_objs = []
    for idx in range(num_photo_cuts):
        img_p = valid_images[idx % len(valid_images)]
        motion = KEN_BURNS_MOTIONS[idx % len(KEN_BURNS_MOTIONS)]
        c_file = os.path.join(temp_dir, f"clip_img_{idx}_{motion}.mp4")

        kb_filter = build_ken_burns_filter(motion, width, height, img_dur) + ",setsar=1"
        cmd_img = [
            ffmpeg_exe, "-y",
            "-loop", "1", "-i", img_p,
            "-t", f"{img_dur:.2f}",
            "-vf", kb_filter,
            "-r", str(fps),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-video_track_timescale", "30000",
            "-an",
            c_file
        ]
        try:
            subprocess.run(cmd_img, check=True, capture_output=True)
            img_clips.append(c_file)
            img_objs.append({
                "file": c_file,
                "type": "photo",
                "path": img_p,
                "duration": img_dur
            })
        except Exception:
            # Fallback pad 방식
            cmd_simple = [
                ffmpeg_exe, "-y",
                "-loop", "1", "-i", img_p,
                "-t", f"{img_dur:.2f}",
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p,setsar=1",
                "-r", str(fps),
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-video_track_timescale", "30000",
                "-an",
                c_file
            ]
            subprocess.run(cmd_simple, check=True, capture_output=True)
            img_clips.append(c_file)
            img_objs.append({
                "file": c_file,
                "type": "photo",
                "path": img_p,
                "duration": img_dur
            })

    # (3) 영상 클립들 (가수 무대 짤 + 스톡 리액션 영상) 통일 포맷 변환
    v_clips = []
    v_objs = []
    blur_v_filter = (
        f"split[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=20:5[bgb];"
        f"[fg]scale={width}:-1:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,format=yuv420p,setsar=1"
    )
    for idx, (vtype, vpath) in enumerate(active_video_clips):
        c_file = os.path.join(temp_dir, f"clip_v_{idx}_{vtype}.mp4")
        cmd_v = [
            ffmpeg_exe, "-y",
            "-i", vpath,
            "-t", f"{clip_dur:.2f}",
            "-vf", blur_v_filter,
            "-r", str(fps),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-video_track_timescale", "30000",
            "-an",
            c_file
        ]
        try:
            subprocess.run(cmd_v, check=True, capture_output=True)
            v_clips.append(c_file)
            v_objs.append({
                "file": c_file,
                "type": "stage_clip" if vtype in ("stage_clip", "singer") else ("stock" if vtype == "stock" else "broll"),
                "path": vpath,
                "duration": clip_dur
            })
        except Exception as e:
            print(f"[Video Renderer] 영상 클립 {idx} 처리 실패: {e}")

    # (4) 균등 인터리빙 배치: 썸네일 -> 다이내믹 사진컷 사이사이에 무대 짤/리액션 영상 고르게 분배
    ordered_objs = [thumb_obj]
    if not v_objs:
        ordered_objs.extend(img_objs)
    else:
        step = max(1, len(img_objs) // (len(v_objs) + 1))
        v_idx = 0
        for i, io in enumerate(img_objs):
            ordered_objs.append(io)
            if (i + 1) % step == 0 and v_idx < len(v_objs):
                ordered_objs.append(v_objs[v_idx])
                v_idx += 1
        while v_idx < len(v_objs):
            ordered_objs.append(v_objs[v_idx])
            v_idx += 1

    # 타임라인 세그먼트 메타데이터 계산 및 total_duration 바운딩
    timeline_segments = []
    ordered_clips = []
    curr_time = 0.0

    for obj in ordered_objs:
        if curr_time >= total_duration:
            break
        t0 = round(curr_time, 2)
        dur = obj['duration']
        t1 = round(min(total_duration, curr_time + dur), 2)
        if t1 > t0:
            timeline_segments.append({
                "type": obj["type"],
                "path": obj["path"],
                "start_time": t0,
                "end_time": t1
            })
            ordered_clips.append(obj["file"])
            curr_time = t1

    # shorts_timeline.json 저장 (QA 및 후속 검증용)
    timeline_meta = {
        "video_path": os.path.abspath(output_path),
        "total_duration": total_duration,
        "segments": timeline_segments
    }
    save_targets = {
        os.path.join(os.path.dirname(os.path.abspath(output_path)), "shorts_timeline.json"),
        os.path.abspath("outputs/videos/shorts_timeline.json")
    }
    for target_json in save_targets:
        try:
            os.makedirs(os.path.dirname(target_json), exist_ok=True)
            with open(target_json, "w", encoding="utf-8") as f:
                json.dump(timeline_meta, f, ensure_ascii=False, indent=2)
        except Exception as e_json:
            print(f"[Video Renderer Warning] timeline json 저장 실패 ({target_json}): {e_json}")

    global LAST_TIMELINE_SEGMENTS
    LAST_TIMELINE_SEGMENTS = timeline_segments

    # 2단계: concat 리스트 파일 생성
    concat_list_path = os.path.join(temp_dir, "concat_list.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for c in ordered_clips:
            base_name = os.path.basename(c)
            f.write(f"file '{base_name}'\n")

    # 3단계: 무음 비디오 트랙 합성 (timestamps 연속성 보장을 위한 ultrafast 인코딩)
    combined_video = os.path.join(temp_dir, "combined_no_audio.mp4")
    cmd_concat = [
        ffmpeg_exe, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", "concat_list.txt",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-r", str(fps),
        "-an",
        "combined_no_audio.mp4"
    ]
    subprocess.run(cmd_concat, cwd=temp_dir, check=True, capture_output=True)

    # 4단계: 오디오 결합 및 음성 싱크 자막 합성(Burn-in) 최종 MP4 인코딩
    vf_sub = []
    if srt_path and os.path.exists(srt_path) and os.path.getsize(srt_path) > 10:
        local_srt = os.path.join(temp_dir, "shorts_sub.srt")
        import shutil
        shutil.copy(os.path.abspath(srt_path), local_srt)
        ass_color = hex_to_ass_color(sub_color)
        # 5070 시니어 맞춤 고대비 볼드 자막 스타일 (커스텀 크기/색상 + 블랙 두꺼운 테두리 + 하단 안전지대 MarginV=45 + WrapStyle=2로 복수 줄바꿈 원천 차단)
        style = f"Fontname=Malgun Gothic,Fontsize={sub_font_size},Bold=1,PrimaryColour={ass_color},OutlineColour=&H00000000,BorderStyle=1,Outline=2.4,Shadow=1,Alignment=2,MarginV=45,WrapStyle=2"
        vf_sub = ["-vf", f"subtitles=shorts_sub.srt:force_style='{style}'"]

    cmd_final = [
        ffmpeg_exe, "-y",
        "-i", "combined_no_audio.mp4",
        "-i", os.path.abspath(audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
    ] + vf_sub + [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{total_duration:.2f}",
        "-shortest",
        os.path.abspath(output_path)
    ]
    subprocess.run(cmd_final, cwd=temp_dir, check=True, capture_output=True)

    print(f"[Video Renderer] 최종 쇼츠 렌더링 완료 (자막 합성 포함): {output_path} (길이: {total_duration:.2f}s)")
    if return_timeline:
        return output_path, timeline_segments
    return output_path



