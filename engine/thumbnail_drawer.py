import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_PATH = "C:/Windows/Fonts/malgunbd.ttf"
if not os.path.exists(FONT_PATH):
    FONT_PATH = "C:/Windows/Fonts/malgun.ttf"

def create_high_contrast_thumbnail(
    bg_image_path: str,
    line1: str,
    line2: str,
    output_path: str = "outputs/thumbnails/thumb_main.jpg",
    width: int = 1080,
    height: int = 1920,
    font_size_1: int = 76,
    font_size_2: int = 76,
    color_1: str = "#00D2FF",
    color_2: str = "#FFF200",
    sub_preview_text: str = None,
    sub_font_size: int = 16,
    sub_color: str = "#FFF000",
    sub_margin_v: int = 45
) -> str:
    """
    5070 시니어 맞춤 고대비 썸네일 생성:
    - 9:16 (1080x1920) 규격
    - 윗줄(Line 1): 커스텀 크기 및 색상 + 두꺼운 블랙 테두리
    - 아랫줄(Line 2): 커스텀 크기 및 색상 + 두꺼운 블랙 테두리
    - 상단 안전지대(Safe Zone)에 배치하여 가수 얼굴 가림 방지
    - 자막 세로 위치(sub_margin_v) 실시간 가상 오버레이 연동
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 1. 배경 이미지 로드 및 9:16 얼굴 중심 스마트 크롭/리사이즈
    bg_canvas = None
    if bg_image_path and os.path.exists(bg_image_path):
        try:
            from engine.video_renderer import create_face_aware_base_image
            temp_face_bg = os.path.join(os.path.dirname(output_path), "temp_face_thumb_bg.jpg")
            processed_bg = create_face_aware_base_image(bg_image_path, target_w=width, target_h=height, out_path=temp_face_bg)
            if processed_bg and os.path.exists(processed_bg):
                bg_canvas = Image.open(processed_bg).convert('RGB').resize((width, height), Image.Resampling.LANCZOS)
        except Exception as e:
            print(f"[Thumbnail Face Warning] {e}")

    if bg_canvas is None:
        if bg_image_path and os.path.exists(bg_image_path):
            try:
                img = Image.open(bg_image_path).convert('RGB')
            except Exception:
                img = Image.new('RGB', (width, height), color=(20, 30, 48))
        else:
            img = Image.new('RGB', (width, height), color=(20, 30, 48))

        # 블러 배경 생성 + 중앙 원본 유지
        bg_canvas = Image.new('RGB', (width, height), color=(15, 20, 30))
        bg_blur = img.resize((width, height)).filter(ImageFilter.GaussianBlur(15))
        bg_canvas.paste(bg_blur, (0, 0))

        scale = min(width / img.width, height / img.height)
        nw, nh = int(img.width * scale), int(img.height * scale)
        img_resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
        offset_x = (width - nw) // 2
        offset_y = (height - nh) // 2 + 100
        bg_canvas.paste(img_resized, (offset_x, offset_y))

    # 상단 텍스트 가독성을 위한 은은한 다크 그라데이션 오버레이 (상단 650px)
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    for y in range(0, 650):
        alpha = int(190 * (1 - (y / 650)))
        draw_overlay.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    bg_canvas.paste(overlay, (0, 0), overlay)

    # 2. 텍스트 폰트 설정
    try:
        font1 = ImageFont.truetype(FONT_PATH, font_size_1)
        font2 = ImageFont.truetype(FONT_PATH, font_size_2)
    except Exception:
        font1 = font2 = ImageFont.load_default()

    draw = ImageDraw.Draw(bg_canvas)

    # 3. 텍스트 위치 계산 (상단 15~25% 영역, 중앙 정렬)
    # Line 1
    bbox1 = draw.textbbox((0, 0), line1, font=font1)
    w1, h1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
    x1 = (width - w1) // 2
    y1 = 200

    # Line 2
    bbox2 = draw.textbbox((0, 0), line2, font=font2)
    w2, h2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
    x2 = (width - w2) // 2
    y2 = y1 + h1 + 35

    # 4. 블랙 스트로크(외곽선) + 텍스트 렌더링
    stroke_w1 = max(4, int(font_size_1 * 0.1))
    stroke_w2 = max(4, int(font_size_2 * 0.1))
    draw.text((x1, y1), line1, font=font1, fill=color_1, stroke_width=stroke_w1, stroke_fill="black")
    draw.text((x2, y2), line2, font=font2, fill=color_2, stroke_width=stroke_w2, stroke_fill="black")

    # 영상 렌더링용 깨끗한 썸네일 원본 먼저 저장
    bg_canvas.save(output_path, quality=95)
    final_preview_path = os.path.abspath(output_path)

    # 5. 쇼츠 1줄 자막 가상 실시간 위치 오버레이 (UI 미리보기 전용)
    if sub_preview_text:
        try:
            preview_canvas = bg_canvas.copy()
            canvas_sub_size = int(sub_font_size * 3.8)
            try:
                sub_font = ImageFont.truetype(FONT_PATH, canvas_sub_size)
            except Exception:
                sub_font = ImageFont.load_default()

            sub_y = int(height - (sub_margin_v * 4.8) - 100)
            sub_y = max(350, min(height - 130, sub_y))

            draw_p = ImageDraw.Draw(preview_canvas)
            bbox_sub = draw_p.textbbox((0, 0), sub_preview_text, font=sub_font)
            sw, sh = bbox_sub[2] - bbox_sub[0], bbox_sub[3] - bbox_sub[1]
            sx = (width - sw) // 2

            pad_x, pad_y = 26, 14
            sub_bg_box = [
                max(10, sx - pad_x),
                max(0, sub_y - pad_y),
                min(width - 10, sx + sw + pad_x),
                min(height - 10, sub_y + sh + pad_y)
            ]

            sub_overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            sub_draw = ImageDraw.Draw(sub_overlay)
            sub_draw.rounded_rectangle(sub_bg_box, radius=14, fill=(0, 0, 0, 215))
            preview_canvas.paste(sub_overlay, (0, 0), sub_overlay)

            stroke_sub = max(3, int(canvas_sub_size * 0.08))
            draw_p = ImageDraw.Draw(preview_canvas)
            draw_p.text((sx, sub_y), sub_preview_text, font=sub_font, fill=sub_color, stroke_width=stroke_sub, stroke_fill="black")

            base, ext = os.path.splitext(output_path)
            preview_path = f"{base}_preview{ext}"
            preview_canvas.save(preview_path, quality=95)
            final_preview_path = os.path.abspath(preview_path)
        except Exception as e_sub:
            print(f"[SubPreview Error] {e_sub}")

    return final_preview_path


if __name__ == "__main__":
    out = create_high_contrast_thumbnail(
        bg_image_path=None,
        line1="TV조선이 박서진 ‘이것’ 보고",
        line2="땅치고 후회한 상황!!",
        output_path="outputs/thumbnails/test_thumb.jpg"
    )
    print("Thumbnail created at:", out)
