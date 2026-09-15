import os
import subprocess
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

def ensure_stock_video():
    """
    유튜브 '재사용 콘텐츠' 제재를 회피하기 위한
    무료 스톡 비디오 클립을 확인하고, 없을 경우 PIL과 FFmpeg로
    고화질 네티즌 반응 연출 클립을 자동 생성합니다.
    """
    stock_dir = "assets/stock_videos"
    os.makedirs(stock_dir, exist_ok=True)
    stock_file = os.path.join(stock_dir, "stock_reaction_1.mp4")
    
    if os.path.exists(stock_file) and os.path.getsize(stock_file) > 1000:
        return stock_file

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    
    # PIL을 사용해 한글 폰트(맑은 고딕)가 완벽하게 적용된 1080x1920 카드 이미지 생성
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (18, 26, 40))
    draw = ImageDraw.Draw(img)

    # 폰트 로드 (윈도우 맑은 고딕)
    font_path = "C:/Windows/Fonts/malgun.ttf"
    font_bold_path = "C:/Windows/Fonts/malgunbd.ttf"
    try:
        font_tag = ImageFont.truetype(font_path, 42)
        font_main = ImageFont.truetype(font_bold_path if os.path.exists(font_bold_path) else font_path, 50)
        font_sub = ImageFont.truetype(font_path, 38)
    except Exception:
        font_tag = font_main = font_sub = ImageFont.load_default()

    # 중앙 반응 카드 박스
    card_w, card_h = 920, 360
    card_x = (w - card_w) // 2
    card_y = (h - card_h) // 2
    draw.rounded_rectangle(
        [card_x, card_y, card_x + card_w, card_y + card_h],
        radius=28,
        fill=(32, 44, 66),
        outline=(65, 85, 120),
        width=3
    )

    draw.text((w // 2, card_y + 70), "💬 [네티즌 실시간 응원 반응]", font=font_tag, fill=(180, 210, 255), anchor="mm")
    draw.text((w // 2, card_y + 175), '"역시 믿고 듣는 우리 가수 최고입니다!"', font=font_main, fill=(255, 225, 80), anchor="mm")
    draw.text((w // 2, card_y + 265), "항상 곁에서 끝까지 함께 응원합니다 ❤️", font=font_sub, fill=(230, 235, 245), anchor="mm")

    temp_img_path = os.path.join(stock_dir, "temp_reaction_card.jpg")
    img.save(temp_img_path, "JPEG", quality=95)

    # 3.5초 MP4 클립으로 변환
    cmd = [
        ffmpeg_exe, "-y",
        "-loop", "1", "-i", os.path.abspath(temp_img_path),
        "-t", "3.5",
        "-vf", "scale=1080:1920,format=yuv420p",
        "-r", "30",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-an",
        stock_file
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print("Generated stock reaction video:", stock_file)
    except Exception as e:
        print(f"스톡 비디오 생성 실패: {e}")
    finally:
        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)
    
    return stock_file

if __name__ == "__main__":
    ensure_stock_video()

