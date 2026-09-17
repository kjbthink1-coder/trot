import os
import json
import re
import truststore
truststore.inject_into_ssl()

# =============================================================================
# Standard Length Requirements (100% Synchronized with engine/qa/factual_validator.py)
# =============================================================================
SHORTS_MIN_CHARS: int = 400
SHORTS_MAX_CHARS: int = 500
BLOG_TARGET_CHARS: int = 2400
BLOG_TOLERANCE_RATIO: float = 0.10  # ±10%
BLOG_MIN_CHARS: int = int(BLOG_TARGET_CHARS * (1.0 - BLOG_TOLERANCE_RATIO))  # 2,160
BLOG_MAX_CHARS: int = int(BLOG_TARGET_CHARS * (1.0 + BLOG_TOLERANCE_RATIO))  # 2,640

ONE_SHOT_PROMPT_TEMPLATE = """당신은 수백만 조회수를 기록하는 유튜브 트로트 전문 채널('영웅대학', '서진대학')의 메인 스토리텔러 작가이자 네이버 1등 트로트 전문 블로그 '트롯매거진'의 수석 에디터입니다.
제공된 트로트 뉴스 기사를 분석하여 5070 시니어 여성 팬덤이 열광하는 (1) 기사의 진짜 주인공 가수 이름, (2) 60초 쇼츠 대본, (3) 2줄 썸네일 카피 5종, (4) 2,400자 4단 블로그 원고를 아래 JSON 형식으로 한 번에 생성하세요.

[필수 JSON 규격]
{
  "target_singer": "기사 문맥상의 핵심 주인공 가수 이름 (예: 조항조, 임영웅, 박서진 등 1개 단어)",
  "shorts_script": "50~55초 분량의 나레이션 대본 (한글 공백포함 360~400자 엄수, 절대 410자 초과 금지! 초과 시 60초 쇼츠 음성 잘림 발생). 0~5초 오프닝 3초 후킹(정답을 미리 말하지 않고 결론 은닉형 질문으로 시작) -> 가수의 평소 인품/미담 빌드업 -> 본론 사건과 네티즌들의 감동 댓글/전문가 평가 인용 -> 훈훈한 감동 마무리. 특수기호나 효과음 지문 없이 성우가 바로 읽을 나레이션 본문만 작성할 것.",
  "thumbnails": [
    {"line1": "윗줄 카피 1", "line2": "아랫줄 카피 1!!"},
    {"line1": "윗줄 카피 2", "line2": "아랫줄 카피 2..ㄷㄷ"},
    {"line1": "윗줄 카피 3", "line2": "아랫줄 카피 3?!"},
    {"line1": "윗줄 카피 4", "line2": "아랫줄 카피 4!!"},
    {"line1": "윗줄 카피 5", "line2": "아랫줄 카피 5!!"}
  ],
  "blog_post": "트롯매거진 공식 4단 블로그 원고 (제목, 4단 본문, 링크, 해시태그 포함, 한글 공백포함 2,400자 ±10% 즉 2,160~2,640자 엄수. [사진 1] 반가움 도입부 + 질문1, [사진 2] 현장 디테일 묘사 + 질문2, [사진 3] 팬덤 반응 및 업계 인정 + 질문3, [사진 4] 훈훈한 행보 응원 + 질문4, 하단 📌 더 재밌는 영상 클릭 링크 3개 및 #해시태그 10개 포함)"
}

[절대 금지 사항]
기사 웹사이트의 메뉴, 네비게이션, 광고 문구, 기자 이름 등은 절대 포함하지 마시고, 순수하게 가수의 활약과 미담을 중심으로 감동적이고 흥미진진한 팬덤 스토리텔링으로 재창작하세요.

[기사 정보]
가수: [SINGER_NAME]
제목: [ARTICLE_TITLE]
본문:
[ARTICLE_CONTENT]
"""

CANDIDATE_GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash"
]

def _get_gemini_api_keys(primary_key: str = None) -> list:
    keys = []
    if primary_key and primary_key.strip():
        keys.append(primary_key.strip())

    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        if k.startswith("GEMINI_API_KEY") and v.strip():
                            val = v.strip().strip('"').strip("'")
                            if val not in keys:
                                keys.append(val)
        except Exception:
            pass

    for key_name in ["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4"]:
        val = os.environ.get(key_name, "")
        if val and val.strip() and val.strip() not in keys:
            keys.append(val.strip())

    return keys

def generate_contents(article_title: str, article_content: str, singer_name: str, api_key: str = None, provider: str = "gemini") -> dict:
    """
    뉴스 기사를 입력받아
    1) 60초 쇼츠 대본
    2) 2줄 썸네일 카피 5종 (JSON 리스트)
    3) 2,400자 4단 블로그 원고
    를 생성합니다. (Gemini 4중 멀티 API 키 로테이션 지원)
    """
    gemini_keys = _get_gemini_api_keys(api_key)

    # .replace()를 사용하여 JSON 중괄호 충돌(KeyError) 원천 방지
    prompt = (
        ONE_SHOT_PROMPT_TEMPLATE
        .replace("[SINGER_NAME]", singer_name)
        .replace("[ARTICLE_TITLE]", article_title)
        .replace("[ARTICLE_CONTENT]", article_content[:3500])
    )

    if provider == "gemini" and gemini_keys:
        try:
            from google import genai
            last_error_msg = ""
            import time

            for key_idx, current_key in enumerate(gemini_keys):
                try:
                    client = genai.Client(api_key=current_key)
                except Exception as e_client:
                    continue

                key_failed_429 = False
                for model_name in CANDIDATE_GEMINI_MODELS:
                    if key_failed_429:
                        break

                    for attempt in range(2):
                        try:
                            res = client.models.generate_content(
                                model=model_name,
                                contents=prompt,
                                config={"response_mime_type": "application/json"}
                            )
                            raw_text = res.text.strip() if res and res.text else ""
                            if raw_text.startswith("```"):
                                import re
                                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
                                raw_text = re.sub(r"\s*```$", "", raw_text)

                            data = json.loads(raw_text)
                            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                                data = data[0]

                            if not isinstance(data, dict):
                                raise ValueError(f"Gemini response structure is not a dict: {type(data)}")

                            key_label = f"Key #{key_idx + 1}" if len(gemini_keys) > 1 else "Primary Key"
                            return {
                                "target_singer": data.get("target_singer", singer_name),
                                "shorts_script": data.get("shorts_script", ""),
                                "thumbnails": data.get("thumbnails", _fallback_thumbnails(singer_name, article_title)),
                                "blog_post": data.get("blog_post", ""),
                                "engine_used": f"Gemini ({model_name} | {key_label})"
                            }
                        except Exception as me:
                            last_error_msg = str(me)
                            if "429" in last_error_msg or "RESOURCE_EXHAUSTED" in last_error_msg:
                                print(f"Key #{key_idx + 1} quota exhausted (429). Moving to Key #{key_idx + 2} immediately!")
                                key_failed_429 = True
                                break
                            elif "503" in last_error_msg or "UNAVAILABLE" in last_error_msg or "NOT_FOUND" in last_error_msg:
                                print(f"Model [{model_name}] busy/unavailable ({last_error_msg[:40]}). Switching to next model instantly...")
                                break
                            else:
                                break

            # 모든 모델 시도 실패 시
            fallback = _generate_fallback(article_title, article_content, singer_name)
            fallback["engine_used"] = f"대체 생성기 (Gemini 응답 실패: {last_error_msg[:60]})"
            return fallback

        except Exception as e:
            print(f"Gemini API 호출 실패: {e}")
            fallback = _generate_fallback(article_title, article_content, singer_name)
            fallback["engine_used"] = f"대체 생성기 (Gemini 오류: {str(e)[:100]})"
            return fallback

    elif api_key and provider == "openai":
        try:
            import openai
            client = openai.OpenAI(api_key=api_key)
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            data = json.loads(res.choices[0].message.content)
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                data = data[0]
            return {
                "target_singer": data.get("target_singer", singer_name),
                "shorts_script": data.get("shorts_script", ""),
                "thumbnails": data.get("thumbnails", _fallback_thumbnails(singer_name, article_title)),
                "blog_post": data.get("blog_post", ""),
                "engine_used": "OpenAI (gpt-4o-mini)"
            }
        except Exception as e:
            fallback = _generate_fallback(article_title, article_content, singer_name)
            fallback["engine_used"] = f"대체 생성기 (OpenAI 오류: {str(e)[:100]})"
            return fallback

    fallback = _generate_fallback(article_title, article_content, singer_name)
    fallback["engine_used"] = "내장 기본 템플릿 (API 미사용)"
    return fallback

def _fallback_thumbnails(singer: str, title: str) -> list:
    return [
        {"line1": f"{singer} ‘이것’ 보고", "line2": "방송 관계자들 깜짝 놀란 이유!!"},
        {"line1": f"{singer} 최근 화제 장면 속", "line2": "네티즌 폭발적인 반응..ㄷㄷ"},
        {"line1": f"{singer}의 진심 어린 한마디", "line2": "전국 팬들 눈물바다 만든 순간?!"},
        {"line1": f"{singer} 깜짝 근황 공개되자", "line2": "팬들이 단체로 환호한 상황!!"},
        {"line1": f"{singer} 몰래 보여준 특급 의리", "line2": "팬들 가슴 뭉클하게 만든 사연!!"}
    ]

def _generate_fallback(title: str, content: str, singer: str) -> dict:
    meaningful_sentences = []
    for s in content.replace('\n', ' ').split('.'):
        s = s.strip()
        if len(s) > 20 and not any(k in s for k in ['바로가기', '메뉴', '기자', '저작권', '무단']):
            meaningful_sentences.append(s)

    core_fact = meaningful_sentences[0] if meaningful_sentences else f"{singer}의 새로운 감동 소식이 전해졌습니다."
    second_fact = meaningful_sentences[1] if len(meaningful_sentences) > 1 else f"팬들과 현장 관객들에게 큰 울림을 주었습니다."
    third_fact = meaningful_sentences[2] if len(meaningful_sentences) > 2 else f"전문가들도 이번 소식에 아낌없는 찬사를 보냈습니다."

    shorts_script = (
        f"최근 {singer}의 놀라운 소식이 전해지며 전국 팬들의 가슴을 뜨겁게 달구고 있습니다. "
        f"그런데 이번 소식을 접하고 방송 관계자들과 팬들이 깜짝 놀란 진짜 이유가 있다는데요. 과연 무슨 사연일까요? "
        f"평소 {singer}은 무대 위에서뿐만 아니라 일상 속에서도 늘 주변을 먼저 챙기는 따뜻한 인성으로 잘 알려져 있죠. "
        f"알려진 바에 따르면, {core_fact}. "
        f"이 소식이 알려지자마자 온라인 커뮤니티에서는 '역시 믿고 듣는 우리 가수다', '보는 내내 눈물이 핑 돌았다'라며 폭발적인 반응이 쏟아졌는데요. "
        f"한 가요계 관계자 역시 {singer}만이 보여줄 수 있는 독보적인 진정성이라며 극찬을 아끼지 않았습니다. "
        f"늘 겸손하고 따뜻한 진심으로 우리 곁을 지켜주는 {singer}, 앞으로의 멋진 행보에도 힘찬 응원의 박수를 보냅니다!"
    )

    thumbnails = _fallback_thumbnails(singer, title)

    blog_post = f"""{singer}, 최근 전해진 깜짝 소식에…팬들 난리난 반응 2가지..!!

[사진 1]
{singer}, 드디어 전해진 감동의 소식, 이 소식이 주는 묵직한 울림
최근 트로트 가수 {singer} 님에 대한 새로운 소식이 전해지며 큰 화제를 모으고 있어요. {core_fact}.
솔직히 이 소식을 처음 접했을 때 저도 모르게 "어머, 세상에!" 하고 반가움과 감동이 확 밀려왔답니다. 늘 팬들을 먼저 생각하며 묵묵히 자신의 길을 걸어온 {singer} 님의 진심이 또 한 번 증명된 것 같아 괜히 코끝이 찡해지더라고요.
혹시 여러분도 이 소식 처음 들으셨을 때 가슴이 한 번 쿵 하셨나요? 댓글로 첫 느낌을 살짝 알려주세요!

[사진 2]
현장을 뜨겁게 달군 {singer}의 진솔한 매력과 디테일
이번 소식의 구체적인 내용을 살펴보면 더욱 감탄이 나올 수밖에 없어요. {second_fact}.
무대 위에서 폭발적인 가창력으로 우리를 울리고 웃기던 {singer} 님이잖아요. 그런데 무대 밖에서도 이렇게 한결같이 겸손하고 다정한 매력을 뿜어내니, 오래 응원해 오신 팬분들이라면 더더욱 자부심이 느껴지셨을 거예요. 단순한 화제성을 넘어, 사람 자체의 깊이가 느껴지는 순간이었답니다.
여러분은 {singer} 님의 이런 따뜻하고 진솔한 모습, 평소에 어떻게 보셨나요? 

[사진 3]
팬덤의 폭발적인 반응과 업계 전문가들의 찬사
이 소식이 전해지자마자 팬 커뮤니티와 SNS는 그야말로 축제 분위기였어요. 팬분들은 "역시 우리 가수 최고다", "응원해 온 시간이 너무 자랑스럽다"라며 눈물 섞인 응원 댓글을 쏟아냈답니다.
뿐만 아니라 가요계 관계자들도 {third_fact}라며 {singer} 님의 남다른 스타성과 진정성을 높이 평가했다고 해요. 동료들과 전문가들이 먼저 인정하는 가수라는 사실이 팬들에게는 그 어떤 선물보다 값지게 다가왔을 거예요.
팬으로서 이런 소식을 접할 때마다 가슴 한구석이 벅차오르는데, 여러분은 어떠셨나요?

[사진 4]
{singer}, 앞으로의 눈부신 행보가 더욱 기대되는 이유
이번 소식은 단순히 스쳐 지나가는 이슈가 아니라, {singer} 님이 팬들과 함께 쌓아온 신뢰가 얼마나 단단한지 보여주는 뜻깊은 이정표예요. 스스로 기준을 높여가며 언제나 진심을 다하는 그의 모습은 앞으로의 행보를 더욱 기대하게 만듭니다. 트롯매거진에서도 새로운 소식이 들어오는 대로 가장 빠르게 전해드릴게요!
여러분은 {singer} 님 하면 가장 먼저 떠오르는 명곡이나 추억이 있으신가요? 댓글로 여러분의 따뜻한 응원을 나눠주시면 정말 감사하겠습니다!

​
📌 더 재밌는 영상과 자세한 내용을 원하신다면?
👇👇 클릭 👇👇
{singer}, 무대 뒤에서 동료에게 몰래 건넨 한마디…팬들 눈물 쏟아진 이유..!!
{singer}, 방송국 관계자가 직접 밝힌 인성 비하인드 2가지..ㄷㄷ
{singer}, 팬클럽이 만든 기적 같은 기록…전국이 들썩인 순간?!

#트롯매거진
#트로트
#트로트가수
#유명트로트가수
#{singer}
#{singer}소식
#{singer}영상
#{singer}팬덤
#트로트이슈
"""

    return {
        "target_singer": singer,
        "shorts_script": shorts_script,
        "thumbnails": thumbnails,
        "blog_post": blog_post
    }
