import os
import glob
import random
import time
import subprocess
import uuid
import imageio_ffmpeg
import truststore

# SSL 검증 환경 보호
truststore.inject_into_ssl()

BASE_SINGERS_DIR = os.path.abspath("assets/singers")
os.makedirs(BASE_SINGERS_DIR, exist_ok=True)

DEFAULT_SINGERS = ["임영웅", "박서진", "김용빈", "이찬원", "영탁", "정동원", "송가인", "양지은", "안성훈", "손태진"]

def get_singer_dir(singer_name: str) -> str:
    """가수별 클립 보관 디렉토리 경로 반환 (없으면 자동 생성)"""
    safe_name = singer_name.strip().replace(" ", "_")
    singer_path = os.path.join(BASE_SINGERS_DIR, safe_name, "clips")
    os.makedirs(singer_path, exist_ok=True)
    return singer_path

def get_all_singers() -> list[str]:
    """등록된 가수 목록 및 기본 추천 가수 반환"""
    existing = []
    if os.path.exists(BASE_SINGERS_DIR):
        for d in os.listdir(BASE_SINGERS_DIR):
            if os.path.isdir(os.path.join(BASE_SINGERS_DIR, d)):
                existing.append(d)
    
    # 합치기 및 중복 제거 (기본 가수 우선)
    combined = list(dict.fromkeys(DEFAULT_SINGERS + existing))
    return combined

def get_singer_clips(singer_name: str) -> list[str]:
    """특정 가수의 저장된 4초 짤 클립 MP4 목록 반환"""
    clips_dir = get_singer_dir(singer_name)
    clips = glob.glob(os.path.join(clips_dir, "*.mp4"))
    return sorted(clips, key=os.path.getmtime, reverse=True)

def get_singer_clip_count(singer_name: str) -> int:
    """가수별 보관 클립 개수 반환"""
    return len(get_singer_clips(singer_name))

def get_random_singer_clips(singer_name: str, count: int = 2) -> list[str]:
    """가수 보관함에서 무작위 n개의 클립 추출 (돌려막기 방지용 무작위 셔플)"""
    clips = get_singer_clips(singer_name)
    if not clips:
        return []
    if len(clips) <= count:
        return clips.copy()
    return random.sample(clips, count)

def delete_clip(clip_path: str) -> bool:
    """선택한 클립 파일 삭제"""
    try:
        if os.path.exists(clip_path):
            os.remove(clip_path)
            return True
    except Exception as e:
        print(f"[Clip Manager] 삭제 실패: {e}")
    return False

def get_video_duration(video_path: str) -> float:
    """FFmpeg를 사용해 동영상의 총 재생 시간(초)을 측정"""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg_exe, "-i", video_path]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, errors='ignore')
    for line in res.stderr.split("\n"):
        if "Duration:" in line:
            parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return 0.0

def slice_video_into_clips(
    source_video_path: str,
    singer_name: str,
    clip_duration: float = 4.0,
    max_clips: int = 15,
    progress_callback=None
) -> list[str]:
    """
    원본 동영상에서 3~4초 단위의 무음(-an) 세로형(1080x1920) 짤을 추출하여
    가수 보관함에 영구 저장합니다.
    - 저작권 회피: 오디오 100% 제거 (-an)
    - 화면 포맷: 모던 블러 배경 세로 9:16 최적화
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    clips_dir = get_singer_dir(singer_name)
    
    total_dur = get_video_duration(source_video_path)
    if total_dur < clip_duration:
        print(f"[Clip Manager] 영상이 너무 짧습니다: {total_dur:.1f}초")
        return []

    # 오프닝/엔딩(블랙스크린, 인트로) 제외: 앞 3초, 뒤 3초 여유
    start_offset = 3.0 if total_dur > 10.0 else 0.0
    end_offset = total_dur - (3.0 if total_dur > 10.0 else 0.0)
    usable_dur = max(clip_duration, end_offset - start_offset)
    
    possible_clips = int(usable_dur // clip_duration)
    target_count = min(possible_clips, max_clips)
    
    if target_count <= 0:
        target_count = 1

    # 균등 간격으로 분할 시작 지점 계산
    step = usable_dur / target_count
    start_times = [start_offset + i * step for i in range(target_count)]
    
    generated_clips = []
    blur_filter = (
        "split[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bgb];"
        "[fg]scale=1080:-1:force_original_aspect_ratio=decrease[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,format=yuv420p"
    )

    for idx, st_sec in enumerate(start_times):
        clip_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}_{idx+1}"
        out_clip_path = os.path.join(clips_dir, f"clip_{clip_id}.mp4")
        
        cmd = [
            ffmpeg_exe, "-y",
            "-ss", f"{st_sec:.2f}",
            "-i", source_video_path,
            "-t", f"{clip_duration:.2f}",
            "-vf", blur_filter,
            "-r", "30",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-an",  # 오디오 완전 제거 (저작권 회피)
            out_clip_path
        ]
        
        try:
            res = subprocess.run(cmd, check=True, capture_output=True)
            if os.path.exists(out_clip_path) and os.path.getsize(out_clip_path) > 1000:
                generated_clips.append(out_clip_path)
        except subprocess.CalledProcessError as e:
            print(f"[Clip Manager] 클립 생성 실패 ({idx+1})")
            # fallback 단순 pad 방식
            cmd_fallback = [
                ffmpeg_exe, "-y",
                "-ss", f"{st_sec:.2f}",
                "-i", source_video_path,
                "-t", f"{clip_duration:.2f}",
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p",
                "-r", "30",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-an",
                out_clip_path
            ]
            try:
                subprocess.run(cmd_fallback, check=True, capture_output=True)
                if os.path.exists(out_clip_path):
                    generated_clips.append(out_clip_path)
            except Exception as e2:
                print(f"[Clip Manager] Fallback도 실패: {e2}")

        if progress_callback:
            progress_callback(idx + 1, target_count)

    print(f"[Clip Manager] '{singer_name}' 짤 클립 {len(generated_clips)}개 추출 완료!")
    return generated_clips

def download_youtube_and_slice(
    youtube_url: str,
    singer_name: str,
    clip_duration: float = 4.0,
    max_clips: int = 12,
    progress_callback=None
) -> list[str]:
    """
    유튜브 영상/쇼츠 링크를 받아 임시 다운로드 후 4초 짤로 자동 분할 저장
    - 오디오는 짤 생성 시 어차피 무음(-an) 처리하므로 비디오 스트림만 빠르게 단독 수집하여
      FFmpeg 병합 에러 및 속도 저하를 원천 방지합니다.
    - 다운로드 완료 후 원본 대용량 영상은 즉시 자동 삭제하여 디스크 용량 절약
    """
    import yt_dlp
    
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dir = os.path.dirname(ffmpeg_exe)
    if ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    temp_dir = os.path.abspath("outputs/temp_youtube")
    os.makedirs(temp_dir, exist_ok=True)
    
    ydl_opts = {
        # 비디오 단독 최우선 수집 (오디오 병합 불필요 & 초고속 다운로드 & 저작권 안전)
        'format': 'bestvideo[height<=720][protocol^=http]/bestvideo[height<=720]/bestvideo[protocol^=http]/bestvideo[height<=1080]/best',
        'ffmpeg_location': ffmpeg_dir,
        'outtmpl': os.path.join(temp_dir, "raw_video.%(ext)s"),
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True
    }
    
    try:
        print(f"[Clip Manager] 유튜브 영상 다운로드 시작: {youtube_url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        
        actual_files = glob.glob(os.path.join(temp_dir, "raw_video.*"))
        target_file = None
        for f in actual_files:
            if not f.endswith(".part") and not f.endswith(".ytdl") and os.path.getsize(f) > 10000:
                target_file = f
                break

        if not target_file or not os.path.exists(target_file):
            raise FileNotFoundError("유튜브 영상 다운로드 파일이 생성되지 않았습니다.")
            
        print(f"[Clip Manager] 다운로드 완료 ({os.path.getsize(target_file)/1024/1024:.1f}MB). 4초 짤 분할 시작...")
        clips = slice_video_into_clips(
            source_video_path=target_file,
            singer_name=singer_name,
            clip_duration=clip_duration,
            max_clips=max_clips,
            progress_callback=progress_callback
        )
        return clips
    finally:
        # 원본 임시 다운로드 파일 청소
        try:
            for f in glob.glob(os.path.join(temp_dir, "*.*")):
                os.remove(f)
        except Exception:
            pass
