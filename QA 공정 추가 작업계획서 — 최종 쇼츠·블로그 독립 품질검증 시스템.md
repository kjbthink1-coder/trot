# [추가 작업계획서]
# 최종 제작물 AI + 규칙 기반 독립 QA 공정 추가

## 1. 작업 목적

현재 진행 중인

기사 → Gemini 콘텐츠 생성 → 이미지 수집/선택 → Media DB → B-roll → Video Engine → Shorts/Blog 완성

전체 제작 시스템이 완성된 이후,

**최종 결과물을 자동으로 검사하는 독립적인 QA 공정**을 추가한다.

중요:

이 작업은 기존 제작 기능을 수정하거나 재작성하는 작업이 아니다.

현재 정상 작동하는 제작 시스템이 완성된 후,

**최종 출력물 뒤에 QA 단계를 하나 추가하는 작업**으로만 구현한다.

기존 기능은 절대 변경하지 않는다.

---

# 2. 가장 중요한 설계 원칙

## 2-1. Gemini 자기검수 방식으로 구현하지 않는다.

다음과 같은 방식은 금지한다.

```text
Gemini가 쇼츠 대본 생성
        ↓
같은 Gemini에게
"이 대본 잘 만들었니?"
        ↓
PASS
```

이것은 실질적인 품질검수 효과가 낮으므로 사용하지 않는다.

---

# 3. QA의 기본 구조

최종 제작이 완료된 이후 다음 공정을 추가한다.

```text
                 기존 제작 시스템
                       ↓
              최종 Shorts MP4
              최종 Blog TXT
                       ↓
              ┌────────────────┐
              │   QA Engine    │
              └────────────────┘
                       ↓
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
   규칙 기반 검사   원문 대조 검사   AI 분석 검사
        ↓              ↓              ↓
        └──────────────┼──────────────┘
                       ↓
                  종합 QA Score
                       ↓
          ┌────────────┼────────────┐
          ↓            ↓            ↓
        PASS         WARNING       FAIL
          ↓            ↓            ↓
       최종완료      사용자 확인     수정 필요
```

---

# 4. QA는 "콘텐츠 생성"이 아니라 "검사"만 수행

QA Engine은 기존 콘텐츠를 임의로 수정하지 않는다.

특히 다음을 금지한다.

- 기존 Gemini Shorts Script 수정
- 기존 블로그 내용 임의 수정
- 기존 이미지 교체
- 기존 B-roll 교체
- 기존 TTS 재생성
- 기존 Ken Burns 변경
- 기존 자막 생성 방식 변경
- 기존 Video Engine 변경

QA의 역할은 오직:

> **문제를 찾아서 보고하는 것**

이다.

---

# 5. QA 입력 데이터

최종 QA Engine에 다음 데이터를 전달한다.

## 필수 입력

### A. 원문 기사

```text
article_url
article_title
article_text
article_source
```

### B. Gemini 생성 결과

```text
shorts_script
blog_article
thumbnail_candidates
```

### C. 최종 영상

```text
final_shorts.mp4
```

### D. 영상 제작 메타데이터

```text
tts_duration
video_duration
image_list
image_usage_history
broll_list
broll_tags
scene_plan
caption_data
```

### E. 과거 제작 이력

가능한 경우 최근 제작한 동일 가수 콘텐츠를 조회한다.

```text
previous_titles
previous_scripts
previous_images
previous_broll
previous_scene_patterns
```

---

# 6. QA를 4개 검사 영역으로 분리

QA Engine은 다음 4개 검사 모듈로 구성한다.

```text
QA Engine
│
├── QA-1 Technical Validator
├── QA-2 Content/Factual Validator
├── QA-3 Repetition Validator
└── QA-4 AI Content Reviewer
```

---

# 7. QA-1 Technical Validator

AI에게 맡기지 말고 Python/프로그램 로직으로 검사한다.

## 검사 항목

### 영상 파일

- MP4 정상 생성 여부
- 파일 손상 여부
- 영상 재생 가능 여부
- 영상 길이
- 해상도
- FPS
- 오디오 존재 여부

### TTS

- TTS 길이와 영상 길이 비교
- 마지막 음성이 잘리지 않았는지 확인
- 영상이 음성보다 지나치게 길거나 짧지 않은지 확인

### 자막

- 자막 영역이 화면 밖으로 나가는지
- 자막이 지나치게 긴지
- 한 줄 자막 원칙 유지 여부
- 자막이 얼굴을 과도하게 가리는지

### 이미지

- 누락 이미지
- 깨진 이미지
- 중복 이미지
- 이미지 파일 존재 여부

### B-roll

- 파일 존재 여부
- 영상 길이 정상 여부
- 9:16 처리 여부
- 무음 여부
- 삽입 구간 정상 여부

---

# 8. QA-2 Content / Factual Validator

이 부분은 **원문 기사와 최종 생성 콘텐츠를 비교**한다.

목적:

> Gemini가 기사를 기반으로 콘텐츠를 만들면서 사실을 추가하거나 왜곡하지 않았는지 검사한다.

## 검사 대상

### Shorts

```text
원문 기사
      ↓
Shorts Script
```

### Blog

```text
원문 기사
      ↓
Blog Article
```

---

## 검사 항목

### 사실 추가

기사에 없는 사실을 새롭게 만들어냈는지 확인.

예:

```text
기사:
"최근 방송에서 신곡을 공개했다."

생성:
"지난 3개월 동안 매일 신곡을 연습했다."
```

→ 기사 근거가 없으면 WARNING 또는 FAIL.

---

### 인물/날짜/장소 오류

다음 항목을 비교한다.

- 인물명
- 프로그램명
- 날짜
- 장소
- 사건
- 숫자
- 금액
- 경력
- 발언 내용

---

### 과장 표현

예:

```text
기사:
"팬들의 관심을 받고 있다."

생성:
"전 국민을 충격에 빠뜨렸다."
```

처럼 원문보다 의미가 과도하게 확대되는 표현을 탐지한다.

---

### 제목과 본문 일치

제목이 본문보다 지나치게 과장되어 있는지 확인한다.

---

# 9. QA-3 Repetition Validator

이 모듈은 **저품질 위험을 줄이기 위해 매우 중요하게 구현한다.**

AI의 주관적인 판단보다 **실제 과거 데이터 비교**를 우선한다.

## 비교 대상

최근 동일 가수의 콘텐츠와 비교한다.

### 제목

```text
현재 제목
vs
최근 제목
```

### Shorts Script

```text
현재 Script
vs
과거 Script
```

### 이미지

```text
현재 이미지
vs
최근 사용 이미지
```

### B-roll

```text
현재 B-roll
vs
최근 사용 B-roll
```

### 장면 구성

```text
현재:

사진 → 사진 → B-roll → 사진 → 사진 → 무대

과거:

사진 → 사진 → B-roll → 사진 → 사진 → 무대
```

처럼 지나치게 동일한 구조인지 검사한다.

---

# 10. 이미지 반복률

Media DB에 저장된 사용 이력을 이용한다.

예:

```text
최근 5개 영상에서
동일 이미지가 4회 이상 사용
```

→ WARNING

```text
현재 영상 이미지의
50% 이상이 최근 영상과 동일
```

→ HIGH WARNING

단, 동일 사진 사용 자체를 무조건 FAIL 처리하지 않는다.

뉴스 특성상 특정 사진이 핵심 자료인 경우가 있기 때문이다.

---

# 11. B-roll 반복률

B-roll 역시 동일하게 검사한다.

예:

```text
최근 5개 영상
keyboard.mp4 반복 5회
```

→ WARNING

가능하면 동일 태그의 다른 B-roll을 사용하도록 다음 제작에서 참고 정보로 남긴다.

---

# 12. 콘텐츠 구조 반복 검사

최근 영상과 다음 요소를 비교한다.

- 영상 길이
- Hook 형태
- 장면 수
- 사진/B-roll 비율
- B-roll 위치
- 결론 구조
- CTA 구조

단순히 같은 비율이라는 이유만으로 FAIL하지 않는다.

**여러 요소가 동시에 반복될 경우 위험 점수를 높인다.**

---

# 13. QA-4 AI Content Reviewer

이 단계에서만 AI를 사용한다.

단, AI에게 단순히

> "잘 만들었는지 평가해줘."

라고 하지 않는다.

다음 원칙을 사용한다.

```text
칭찬 금지
근거 없는 PASS 금지
문제가 없으면 "문제 없음"이라고만 표시
문제가 있으면 반드시 근거 제시
확신할 수 없는 내용은 WARNING
```

---

# 14. AI에게 전달할 검사 지시

AI는 다음 자료를 함께 받는다.

```text
[원문 기사]

[Shorts Script]

[Blog Article]

[최근 제작 콘텐츠 요약]

[영상 대표 프레임]

[영상 메타데이터]
```

AI의 역할:

### Shorts

- 대본과 실제 영상 장면의 일치 여부
- 장면이 대사의 의미와 맞는지
- B-roll이 억지스럽게 삽입되지 않았는지
- 지나친 반복 여부
- 과장된 Hook 여부
- 내용 없는 반복 문장이 많은지

### Blog

- 기사 내용과 일치하는지
- 반복 문장이 많은지
- 불필요하게 부풀린 내용이 있는지
- 독자에게 실제 정보가 있는지
- 제목과 본문의 불일치
- 과도한 키워드 반복
- 기계적으로 작성된 느낌이 지나치게 강한지

---

# 15. 영상 자체를 AI가 검사하는 방법

완성 MP4 전체를 그대로 전달하는 것이 아니라,

프로그램에서 대표 프레임을 추출한다.

예:

```text
0초
3초
6초
9초
12초
...
마지막
```

또는 장면 전환 기준으로 대표 프레임을 추출한다.

그리고 AI에게 다음과 같이 전달한다.

```text
원문
+
대본
+
대표 프레임
+
장면 정보
```

AI는

> "대사에서 말하는 장면과 실제 화면이 의미적으로 일치하는가?"

를 검사한다.

---

# 16. QA 점수 체계

100점 만점으로 계산한다.

권장 기준:

```text
Technical          20점
Factual            30점
Repetition         25점
Content Quality    25점
-------------------------
TOTAL             100점
```

---

# 17. 최종 판정

## PASS

```text
90~100점
```

또는

중대한 오류가 없을 경우 PASS.

---

## WARNING

```text
70~89점
```

콘텐츠 제작은 정상 완료하지만 사용자에게 확인 메시지를 표시한다.

예:

```text
⚠ QA WARNING

종합점수: 82

주의사항:
- 최근 영상과 이미지 3장 중복
- Hook 문장이 이전 영상과 유사
- B-roll 1개 관련성 보통

업로드 여부를 확인하세요.
```

---

## FAIL

```text
0~69점
```

또는 점수와 관계없이 아래 중 하나라도 발견하면 FAIL.

### 강제 FAIL

- 영상 파일 손상
- 음성 심각한 누락
- 자막 심각한 오류
- 기사에 없는 중요 사실을 생성
- 인물/날짜/사건의 중대한 오류
- 제목과 실제 내용이 현저하게 다름
- 영상 제작 결과물 누락

---

# 18. 매우 중요한 예외

QA 실패가 발생했다고 해서 프로그램 전체가 중단되어서는 안 된다.

기존 제작 기능의 Fail-Safe 원칙을 그대로 유지한다.

```text
QA Engine 오류
     ↓
QA 결과 없음
     ↓
기존 최종 결과물은 정상 저장
     ↓
"QA 미실행" 상태 표시
```

즉,

**QA 오류 ≠ 영상 제작 실패**

이다.

---

# 19. QA 결과 저장

QA 결과를 DB에 저장한다.

기존 `project_history` 구조를 활용하거나 별도 테이블을 추가한다.

권장:

```text
qa_results
```

필드 예:

```text
id
project_id
created_at

technical_score
factual_score
repetition_score
content_score
total_score

status
issues_json

shorts_result
blog_result

qa_model
qa_version
```

---

# 20. 과거 QA 결과도 축적

프로그램을 사용할수록 QA 데이터가 쌓이도록 한다.

예:

```text
프로젝트 001 → 87점
프로젝트 002 → 91점
프로젝트 003 → 76점
프로젝트 004 → 94점
```

향후 다음과 같은 통계를 확인할 수 있도록 한다.

```text
평균 QA 점수
최근 10개 평균
가수별 평균
WARNING 비율
FAIL 비율
반복성 경고 횟수
사실 오류 횟수
```

---

# 21. UI 추가

기존 UI를 크게 변경하지 않는다.

최종 제작 화면에 다음 영역만 추가한다.

```text
[최종 제작 완료]

Shorts     ✅
Blog       ✅

────────────────

AI/Rule QA

종합점수       91 / 100
상태           PASS

Technical      20/20
Factual        28/30
Repetition     21/25
Content        22/25

[상세 검수 결과]
```

---

# 22. 문제가 있을 경우 상세 표시

예:

```text
⚠ 반복성 주의

최근 3개 콘텐츠와 동일 이미지 4장 발견

⚠ B-roll 주의

00:18~00:21
대사: "팬들의 뜨거운 응원"

현재 B-roll:
도시 거리 영상

권장:
관객/응원 관련 B-roll
```

중요:

**QA는 자동 수정하지 않는다.**

1차 버전에서는 문제를 표시하는 것까지만 구현한다.

---

# 23. 1차 버전에서 자동 재제작은 하지 않는다.

다음과 같은 자동 루프는 이번 작업에서 구현하지 않는다.

```text
FAIL
 ↓
자동 수정
 ↓
재제작
 ↓
재검수
 ↓
무한 반복
```

이것은 시스템 복잡도와 오류 가능성을 크게 높인다.

1차 QA는:

```text
제작
 ↓
검수
 ↓
PASS / WARNING / FAIL
 ↓
사용자 확인
```

까지만 구현한다.

향후 안정화된 후에만 자동 수정 기능을 검토한다.

---

# 24. QA Agent의 독립성

QA Agent는 제작 Agent와 논리적으로 분리한다.

권장 구조:

```text
agents/

pm/
content/
media/
broll/
video/
ui/

qa/
    technical_validator
    factual_validator
    repetition_validator
    ai_reviewer
    qa_aggregator
```

QA Agent가 기존 제작 모듈의 내부 로직을 직접 수정하지 못하도록 한다.

---

# 25. QA 결과 JSON 표준

AI Reviewer는 반드시 구조화된 JSON으로 반환한다.

예:

```json
{
  "status": "WARNING",
  "total_score": 84,
  "technical": {
    "score": 20,
    "issues": []
  },
  "factual": {
    "score": 27,
    "issues": []
  },
  "repetition": {
    "score": 19,
    "issues": [
      "최근 3개 영상과 동일 이미지 3장"
    ]
  },
  "content_quality": {
    "score": 18,
    "issues": [
      "Hook 문장이 최근 콘텐츠와 유사"
    ]
  },
  "critical_error": false,
  "recommendations": [
    "다음 제작에서 이미지 다양성 확대"
  ]
}
```

JSON 파싱 실패 시에도 기존 영상 제작 결과에는 영향을 주지 않는다.

---

# 26. API/Gemini 오류 처리

QA용 AI 호출이 실패할 수 있다.

예:

```text
Gemini API 오류
Timeout
JSON 파싱 실패
Network 오류
Quota 초과
```

이 경우:

```text
영상 제작 성공
블로그 제작 성공
QA = NOT_RUN
```

으로 처리한다.

프로그램 전체를 실패시키지 않는다.

---

# 27. 기존 Media DB와 연결

이번 QA는 현재 구축 중인 Media DB를 적극 활용한다.

현재 계획에서 가수별 사진과 B-roll을 축적하고 사용 이력을 관리하도록 되어 있으므로 , QA에서는 그 사용 이력을 읽기만 한다.

예:

```text
media
 ├── singer
 ├── media_type
 ├── hash
 ├── usage_count
 └── last_used

project_history
 ├── project_id
 ├── singer
 ├── images
 └── broll
```

QA는 이 데이터를 이용하여 반복성을 검사한다.

**QA가 Media DB 자체를 변경해서는 안 된다.**

---

# 28. 기존 제작 시스템 보호

다음 기능은 QA 추가 작업에서도 절대 수정하지 않는다.

```text
Gemini Shorts Script
Gemini Blog
Thumbnail
Image Collection
Image Selection
2.8 sec Ken Burns
Edge-TTS
1-line Bold Caption
OpenCV Face Center Crop
기존 무대 영상 2개 자동 합성
Media DB
B-roll 기본 제작 기능
```

QA는 위 결과물을 **읽고 검사만 한다.**

---

# 29. 구현 순서

## QA Phase 0

현재 정상 작동 상태 백업 확인.

QA 추가 전 기존 제작 테스트 1회 실행.

---

## QA Phase 1

Technical Validator 구현.

```text
영상
오디오
자막
이미지
B-roll
파일
```

검사.

---

## QA Phase 2

Factual Validator 구현.

```text
기사 ↔ Shorts
기사 ↔ Blog
```

비교.

---

## QA Phase 3

Repetition Validator 구현.

```text
현재 프로젝트
       ↕
최근 프로젝트
```

비교.

---

## QA Phase 4

대표 프레임 추출 기능 구현.

```text
final.mp4
 ↓
scene/frame extraction
 ↓
대표 이미지
```

---

## QA Phase 5

AI Reviewer 구현.

원문 + 대본 + 블로그 + 대표 프레임 + 과거 콘텐츠 요약을 전달한다.

---

## QA Phase 6

QA Aggregator 구현.

```text
Technical
Factual
Repetition
AI
       ↓
Final Score
       ↓
PASS / WARNING / FAIL
```

---

## QA Phase 7

UI 표시.

---

## QA Phase 8

QA 결과 DB 저장.

---

## QA Phase 9

전체 회귀 테스트.

---

# 30. 필수 테스트

### 테스트 A

정상적인 콘텐츠.

결과:

```text
PASS
```

---

### 테스트 B

기사에 없는 사실을 의도적으로 대본에 삽입.

결과:

```text
Factual WARNING 또는 FAIL
```

---

### 테스트 C

과거 영상과 동일한 이미지 다수 사용.

결과:

```text
Repetition WARNING
```

---

### 테스트 D

자막 영역을 화면 밖으로 설정.

결과:

```text
Technical FAIL
```

---

### 테스트 E

B-roll을 대사와 관계없는 영상으로 설정.

결과:

```text
Content Quality WARNING
```

---

### 테스트 F

Gemini QA 호출 실패.

결과:

```text
QA = NOT_RUN
기존 최종 영상 = 정상
```

---

### 테스트 G

QA JSON 파싱 실패.

결과:

```text
QA = NOT_RUN
기존 제작 결과 = 정상
```

---

### 테스트 H

정상적인 동일 사진이 핵심 뉴스 사진으로 반복 사용됨.

결과:

```text
무조건 FAIL하지 않음
WARNING 또는 정상
```

---

# 31. 최종 목표

최종 프로그램의 구조를 다음과 같이 만든다.

```text
기사 입력
   ↓
Gemini
   ↓
Shorts + Blog
   ↓
Media DB / B-roll
   ↓
Video Engine
   ↓
최종 Shorts
   ↓
┌─────────────────────────┐
│       FINAL QA           │
│                         │
│ Technical               │
│ Factual                 │
│ Repetition              │
│ AI Content Review       │
└─────────────────────────┘
   ↓
PASS / WARNING / FAIL
   ↓
최종 저장 및 사용자 확인
```

핵심은:

> **AI가 자기 콘텐츠를 칭찬하는 검수가 아니라, 실제 데이터와 규칙을 먼저 검사하고 AI는 그 위에서 문제를 찾는 보조 검수 역할만 수행하도록 한다.**

---

# 32. Antigravity 최종 작업 지시

이 문서는 현재 진행 중인 Media DB + B-roll 구현이 완료된 이후 추가하는 **독립 QA 공정 추가 작업**으로 해석한다.

현재 제작 시스템을 재작성하지 않는다.

기존 기능을 수정하지 않는다.

QA는 최종 결과물을 읽고 검사하는 독립 모듈로 구현한다.

특히 Gemini가 생성한 콘텐츠를 동일한 방식으로 단순 재평가하는 자기검수 구조를 만들지 않는다.

반드시 다음 우선순위를 따른다.

```text
1. 프로그램 규칙 기반 검사
2. 원문 기사와 생성 콘텐츠 비교
3. 과거 제작 이력과 반복성 비교
4. 실제 최종 영상 대표 프레임 검사
5. AI Reviewer 보조 판단
6. QA Aggregator 종합
```

그리고 반드시 기억할 것:

```text
QA 오류
≠
콘텐츠 제작 실패
```

QA Engine에 오류가 발생하더라도 기존 Shorts/Blog 제작 결과는 정상적으로 저장되어야 한다.

이번 추가 작업의 목표는 콘텐츠를 자동으로 수정하는 것이 아니라,

**"최종 제작물이 업로드 가능한 수준인지 자동으로 한 번 더 걸러주는 품질관리 공정"**

을 추가하는 것이다.

1차 버전에서는 자동 재제작 기능을 구현하지 않는다.

반드시 `PASS / WARNING / FAIL` 결과와 구체적인 문제점을 사용자에게 보여주는 것까지 구현한다.