import os
import sys

from crawler.news_parser import parse_naver_news
from engine.ai_generator import generate_contents
from engine.tts_engine import synthesize_speech
from engine.thumbnail_drawer import create_high_contrast_thumbnail
from engine.video_renderer import render_shorts_video
from assets.generate_stock_clips import ensure_stock_video

def run_test():
    test_url = "https://www.sportsseoul.com/news/read/1634840?ref=naver"
    print("=== 1. 기사 크롤링 시작 ===")
    parsed = parse_naver_news(test_url)
    print(f"가수: {parsed['singer']}")
    print(f"제목: {parsed['title']}")
    print(f"이미지 수: {len(parsed['images'])}")

    print("\n=== 2. AI 대본 및 블로그 생성 ===")
    ai_res = generate_contents(parsed["title"], parsed["content"], parsed["singer"])
    print(f"쇼츠 대본: {ai_res['shorts_script'][:150]}...")
    print(f"썸네일 1안: {ai_res['thumbnails'][0]}")

    print("\n=== 3. 썸네일 이미지 생성 ===")
    thumb_path = create_high_contrast_thumbnail(
        bg_image_path=parsed["images"][0] if parsed["images"] else None,
        line1=ai_res["thumbnails"][0]["line1"],
        line2=ai_res["thumbnails"][0]["line2"],
        output_path="outputs/thumbnails/thumb_e2e.jpg"
    )
    print(f"썸네일 저장: {thumb_path}")

    print("\n=== 4. Edge-TTS 음성 합성 ===")
    audio_path, srt_path = synthesize_speech(ai_res["shorts_script"], output_dir="outputs/audio")
    print(f"음성 파일: {audio_path}")
    print(f"자막 파일: {srt_path}")

    print("\n=== 5. 스톡 비디오 확인 및 쇼츠 영상 렌더링 ===")
    stock_clip = ensure_stock_video()
    video_path = render_shorts_video(
        audio_path=audio_path,
        thumbnail_path=thumb_path,
        image_paths=parsed["images"],
        stock_video_path=stock_clip,
        srt_path=srt_path,
        output_path="outputs/videos/trot_shorts_e2e.mp4"
    )
    print(f"\n[성공] 최종 쇼츠 영상 출력 완료: {video_path}")
    print(f"파일 크기: {os.path.getsize(video_path)} bytes")

if __name__ == "__main__":
    run_test()
