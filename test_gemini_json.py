import os
import truststore
truststore.inject_into_ssl()
import json
import time

key = ""
with open(".env", "r", encoding="utf-8") as f:
    for line in f:
        if line.startswith("GEMINI_API_KEY="):
            key = line.strip().split("=", 1)[1]

from google import genai
client = genai.Client(api_key=key)

prompt = """당신은 수백만 조회수 유튜브 트로트 전문 채널('영웅대학', '서진대학')의 메인 작가이자 네이버 1등 트로트 전문 블로그 '트롯매거진'의 수석 에디터입니다.
제공된 기사를 분석하여 5070 시니어 여성 팬덤이 열광하는 (1) 60초 쇼츠 대본, (2) 2줄 썸네일 카피 5종, (3) 2,400자 4단 블로그 원고를 아래 JSON 형식으로 한 번에 생성하세요:

{
  "shorts_script": "0~5초 오프닝 3초 후킹으로 시작하여, 가수의 미담과 본론 사건, 네티즌 감동 댓글, 훈훈한 마무리까지 성우가 바로 읽을 50~60초 나레이션 대본 (한글 400~500자, 특수기호/효과음 제외)",
  "thumbnails": [
    {"line1": "가수명 ‘이것’ 보고", "line2": "방송국 난리난 진짜 이유!!"},
    {"line1": "가수명 최근 화제 장면 속", "line2": "네티즌 폭발적인 반응..ㄷㄷ"},
    {"line1": "가수명이 몰래 건넨", "line2": "전국민 울린 한마디?!"},
    {"line1": "가수명 깜짝 근황 공개되자", "line2": "팬들이 단체로 눈물흘린 사연!!"},
    {"line1": "가수명 특급 의리 소식에", "line2": "동료들이 감동한 상황!!"}
  ],
  "blog_post": "트롯매거진 공식 4단 블로그 원고 (제목, [사진 1] 반가움 도입부 + 질문1, [사진 2] 현장 디테일 + 질문2, [사진 3] 팬덤 반응 및 업계 인정 + 질문3, [사진 4] 훈훈한 행보 응원 + 질문4, 하단 📌 더 재밌는 영상 클릭 링크 3개 및 #해시태그 10개 포함, 약 2,000자 이상)"
}

[기사 정보]
가수: 임영웅
제목: 임영웅, 아이돌차트 285주 연속 1위 독보적 화제성
본문:
가수 임영웅이 아이돌차트 평점랭킹에서 29만 2931표를 얻어 285주 연속 1위를 차지했습니다. 
임영웅은 콘서트와 음원 모두에서 압도적인 팬덤 화력을 입증하며 대기록을 이어가고 있습니다. 
음악계 관계자들은 임영웅의 독보적인 진정성과 무대 매너를 극찬했습니다.
"""

t0 = time.time()
res = client.models.generate_content(
    model="gemini-3.6-flash",
    contents=prompt,
    config={"response_mime_type": "application/json"}
)
print("Time taken:", round(time.time() - t0, 2), "s")
data = json.loads(res.text)
print("Keys in json:", list(data.keys()))
print("\n--- [SHORTS SCRIPT] ---\n", data["shorts_script"])
print("\n--- [THUMBNAILS] ---\n", data["thumbnails"][:2])
print("\n--- [BLOG POST PREVIEW] ---\n", data["blog_post"][:300])
