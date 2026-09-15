import os
import ssl
import asyncio
import truststore
truststore.inject_into_ssl()
import edge_tts
import edge_tts.constants
import re

# SSL 인증서 프록시 환경 지원
edge_tts.constants._SSL_CTX = ssl._create_unverified_context()

DEFAULT_VOICE = "ko-KR-SunHiNeural"  # 또렷하고 따뜻한 여성 성우 (시니어 선호도 1위)
MALE_VOICE = "ko-KR-InJoonNeural"    # 신뢰감 있는 남성 성우

from datetime import timedelta

def create_single_line_srt(word_chunks, max_chars=13, max_words=4) -> str:
    """
    단어 단위(WordBoundary) 타임스탬프를 묶어서
    유튜브 쇼츠 규격에 최적화된 '무조건 1줄' 자막(SRT)을 생성합니다.
    - 한 번에 최대 10~13글자 / 3~4단어 내외만 노출
    - 문장부호(, . ! ?)에서 자연스럽게 끊어 호흡 일치
    - 화면 전체를 가리는 줄바꿈 대참사 원천 차단
    """
    cues = []
    current_words = []
    current_start = None
    current_end = None

    for w in word_chunks:
        text = w.get("text", "").strip()
        if not text:
            continue
        
        start_us = w["offset"] / 10
        end_us = (w["offset"] + w["duration"]) / 10
        
        if not current_words:
            current_start = start_us
            current_words.append(text)
            current_end = end_us
        else:
            candidate = " ".join(current_words + [text])
            prev_has_punct = current_words[-1].endswith(('.', '!', '?', ',', '~'))
            
            # 글자수 초과, 단어수 초과, 또는 쉼표/마침표 등의 구두점인 경우 1줄 단위로 분할
            if prev_has_punct or len(candidate) > max_chars or len(current_words) >= max_words:
                cues.append({
                    "start": current_start,
                    "end": current_end,
                    "text": " ".join(current_words)
                })
                current_start = start_us
                current_words = [text]
                current_end = end_us
            else:
                current_words.append(text)
                current_end = end_us

    if current_words:
        cues.append({
            "start": current_start,
            "end": current_end,
            "text": " ".join(current_words)
        })

    def format_ts(us):
        td = timedelta(microseconds=us)
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        millis = int(td.microseconds / 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    lines = []
    for idx, cue in enumerate(cues, 1):
        lines.append(f"{idx}")
        lines.append(f"{format_ts(cue['start'])} --> {format_ts(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")

    return "\n".join(lines)

def split_text_into_chunks(text, max_chars=11, max_words=3):
    words = text.split()
    chunks = []
    curr = []
    for w in words:
        cand = " ".join(curr + [w])
        if curr and (len(cand) > max_chars or len(curr) >= max_words or curr[-1].endswith(('.', '!', '?', ',', '~'))):
            chunks.append(" ".join(curr))
            curr = [w]
        else:
            curr.append(w)
    if curr:
        chunks.append(" ".join(curr))
    return chunks

def split_sentences_into_single_line_srt(sentence_chunks, max_chars=11, max_words=3):
    cues = []
    for sc in sentence_chunks:
        text = sc.get("text", "").strip()
        if not text:
            continue
        start_sec = sc["offset"] / 10000000.0
        dur_sec = sc["duration"] / 10000000.0
        
        pieces = split_text_into_chunks(text, max_chars=max_chars, max_words=max_words)
        if not pieces:
            continue
        
        piece_dur = dur_sec / len(pieces)
        for i, piece in enumerate(pieces):
            p_start = start_sec + i * piece_dur
            p_end = p_start + piece_dur
            cues.append({
                "start": p_start,
                "end": p_end,
                "text": piece
            })
            
    lines = []
    def format_ts_sec(seconds):
        td = timedelta(seconds=seconds)
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        millis = int(td.microseconds / 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    for idx, cue in enumerate(cues, 1):
        lines.append(f"{idx}")
        lines.append(f"{format_ts_sec(cue['start'])} --> {format_ts_sec(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")
    return "\n".join(lines)

async def _synthesize_async(text: str, output_audio: str, output_vtt: str = None, voice: str = DEFAULT_VOICE):
    communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    word_chunks = []
    sentence_chunks = []
    
    with open(output_audio, "wb") as file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_chunks.append(chunk)
            elif chunk["type"] == "SentenceBoundary":
                sentence_chunks.append(chunk)

    if output_vtt:
        if word_chunks:
            srt_content = create_single_line_srt(word_chunks, max_chars=11, max_words=3)
        elif sentence_chunks:
            srt_content = split_sentences_into_single_line_srt(sentence_chunks, max_chars=11, max_words=3)
        else:
            # 절대 텍스트 전체를 한 번에 띄우지 않고 1줄 단위로 균등 분할
            fake_sc = [{"offset": 0, "duration": 50000000, "text": text}]
            srt_content = split_sentences_into_single_line_srt(fake_sc, max_chars=11, max_words=3)
            
        with open(output_vtt, "w", encoding="utf-8") as f:
            f.write(srt_content)

def synthesize_speech(text: str, output_dir: str = "outputs/audio", voice: str = DEFAULT_VOICE) -> tuple[str, str]:
    """
    텍스트를 입력받아 Edge-TTS로 고품질 MP3 음성과 SRT 자막 파일을 생성하고
    (mp3_path, srt_path) 튜플을 반환합니다.
    """
    os.makedirs(output_dir, exist_ok=True)
    clean_text = re.sub(r'\[.*?\]|\(.*?\)', '', text).strip()
    output_audio = os.path.join(output_dir, "narration.mp3")
    output_srt = os.path.join(output_dir, "subtitles.srt")
    
    asyncio.run(_synthesize_async(clean_text, output_audio, output_srt, voice))
    return os.path.abspath(output_audio), os.path.abspath(output_srt)

if __name__ == "__main__":
    audio, srt = synthesize_speech("안녕하세요. 오늘 임영웅 가수의 특별한 소식을 전해드립니다.")
    print("TTS generated:", audio)
    print("SRT generated:", srt)
