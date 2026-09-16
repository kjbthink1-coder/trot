# YouTube 가수별 CC 영상 라이선스 검증 강화 작업지시서

## 1. 작업 목적

현재 구현된 `가수별 CC 영상 검색 → 미리보기 → 3~4초 구간 선택 → DB 저장` 기능에서 가장 중요한 문제는 다음과 같다.

현재 검색 결과의 `CC`가

- YouTube 자막(Subtitles/CC) 표시인지
- 실제 Creative Commons 라이선스(CC BY)인지

명확하게 구분되지 않을 가능성이 있다.

따라서 앞으로는 **실제 Creative Commons Attribution(CC BY) 라이선스가 확인된 영상만 `singer_cc_video` 후보로 인정**하도록 검증 로직을 강화한다.

YouTube 공식 문서상 Creative Commons 콘텐츠는 CC BY 라이선스에 따라 재사용할 수 있으며, 사용할 경우 저작자·작품명·원본 URL·라이선스 정보를 표시해야 한다.

---

# 2. 가장 중요한 원칙

## 절대 금지

검색 결과에 다음과 같은 이유만으로 CC 영상으로 판정하지 않는다.

- 검색어에 `CC`가 포함됨
- 영상 제목에 `CC`가 있음
- YouTube 검색 화면에 `CC` 아이콘이 있음
- 자막/Closed Captions가 있음
- `yt-dlp` 검색 결과에 subtitle 관련 정보가 있음
- 영상 설명에 "CC"라는 단어가 있음

### 특히 중요

**Subtitles/CC(자막)**와 **Creative Commons(CC BY 라이선스)**는 완전히 다른 개념이다.

따라서 자막이 있는 영상은 Creative Commons 영상으로 판단하면 안 된다.

---

# 3. 허용하는 라이선스

현재 기능에서 자동으로 `singer_cc_video` 라이브러리에 등록할 수 있는 라이선스는 기본적으로:

```text
Creative Commons Attribution
CC BY
```

만 인정한다.

다음은 자동 등록하지 않는다.

```text
Standard YouTube License
UNKNOWN
UNVERIFIED
LICENSE_NOT_FOUND
```

---

# 4. 검색 단계

가수명으로 YouTube Creative Commons 후보를 검색한다.

예:

```text
임영웅
임영웅 official
임영웅 concert
임영웅 performance
임영웅 interview
```

단, 검색 결과 자체를 CC 영상으로 확정하지 않는다.

검색은 단지 **후보 수집 단계**다.

---

# 5. 후보별 라이선스 검증

각 후보 영상마다 반드시 다음 정보를 확보한다.

```text
youtube_video_id
youtube_url
video_title
channel_name
uploader
upload_date
license
description
```

가능하면 YouTube/yt-dlp가 제공하는 실제 `license` 메타데이터를 우선 사용한다.

예:

```python
info.get("license")
```

또는 실제 yt-dlp 반환 구조에서 확인 가능한 라이선스 필드를 사용한다.

---

# 6. 판정 규칙

## PASS

다음 조건을 만족하면:

```text
license == "Creative Commons Attribution"
```

또는 실제 메타데이터가 CC BY임을 명확하게 확인할 수 있는 경우:

```text
rights_status = "CC_BY_VERIFIED"
```

로 판정한다.

이 경우에만 사용자가 3~4초 구간을 잘라 DB에 등록할 수 있도록 한다.

---

## FAIL

다음 중 하나라도 해당하면 자동 CC 영상으로 등록하지 않는다.

```text
license == "Standard YouTube License"

license == None

license == ""

license == "Unknown"

license 확인 불가능

영상 설명에 CC라고만 적혀 있음

자막 CC만 존재

검색 결과가 CC 필터에서 나왔지만 실제 라이선스 확인 불가능
```

DB에는 필요하면 다음처럼 기록한다.

```text
rights_status = "UNVERIFIED"
```

하지만 `singer_cc_video` 재사용 라이브러리에는 넣지 않는다.

---

# 7. 중요한 추가 검증 — 업로더가 실제 권리자인지

Creative Commons 표시가 있다고 해서 무조건 영상 내용 전체의 권리가 안전하다고 자동 확정하지 않는다.

예를 들어:

```text
방송사 영상
콘서트 중계 영상
타인의 공연 영상
음원/방송 화면을 다른 사람이 재업로드한 영상
```

등을 제3자가 CC BY로 표시했을 가능성이 있다.

따라서 시스템에는 다음 필드를 추가한다.

```text
license_type
rights_status
rights_warning
manual_review_required
```

예:

```text
license_type = "CC BY"
rights_status = "CC_BY_VERIFIED"
rights_warning = "Uploader ownership not independently verified"
manual_review_required = True
```

즉,

**YouTube에서 CC BY라고 확인됨**

과

**해당 업로더가 영상 전체의 권리를 실제로 가지고 있음**

을 시스템에서 동일한 의미로 취급하지 않는다.

---

# 8. 가수 영상 특성에 따른 추가 위험 표시

다음 키워드가 제목/설명/채널명 등에 발견되면 자동 삭제하지 말고 `MANUAL_REVIEW` 대상으로 표시한다.

```text
MBC
KBS
SBS
TV조선
JTBC
채널A
MBN
엠넷
Mnet
방송
뉴스
콘서트 중계
직캠
공연
뮤직비디오
Music Video
Official
Live
```

이것은 "사용 불가"라는 뜻이 아니다.

**권리관계 확인이 더 필요한 영상이라는 경고 표시**다.

---

# 9. DB 저장 구조

기존 `media` 테이블의

```text
media_type = 'singer_cc_video'
```

구조는 유지한다.

다음 필드를 추가하거나 기존 필드를 활용한다.

```text
license_type
rights_status
rights_warning
manual_review_required

youtube_video_id
youtube_url
channel_name
video_title

original_start
original_end
clip_duration

width
height
fps

file_hash
use_count
created_at
```

추천 상태값:

```text
CC_BY_VERIFIED
MANUAL_REVIEW
UNVERIFIED
REJECTED
```

---

# 10. DB 등록 조건

실제 3~4초 클립을 최종 DB에 저장할 수 있는 조건:

```text
license_type == CC BY
AND
rights_status == CC_BY_VERIFIED
AND
manual_review_required == False
```

단, 사용자가 직접 검토 후 저장하도록 설계하는 경우에는:

```text
CC_BY_VERIFIED
```

상태의 후보를 UI에 보여주고 사용자가 최종 선택할 수 있도록 한다.

---

# 11. UI에 반드시 표시

기존 CC 영상 카드에 다음 정보를 보여준다.

```text
[CC BY 확인]

가수: 임영웅
제목: XXXXX
채널: XXXXX

라이선스:
Creative Commons Attribution

출처:
youtube.com/...

권리상태:
CC_BY_VERIFIED

[미리보기]

시작: 00:15
종료: 00:18

[3초 구간 저장]
```

검증되지 않은 영상은:

```text
[⚠ 라이선스 확인 필요]

라이선스:
확인되지 않음

권리상태:
UNVERIFIED

[저장 불가]
```

로 표시한다.

---

# 12. 검색 결과 수가 5개보다 적어도 억지로 채우지 않는다

이 부분은 매우 중요하다.

사용자가 `CC 영상 5개`를 요청하더라도:

```text
검증된 CC BY 영상 5개가 없으면
검증된 영상만 표시한다.
```

예:

```text
검색 후보 20개
↓
라이선스 검증
↓
CC BY 확인 2개
↓
UI에 2개만 표시
```

절대로:

```text
CC BY 2개 + 일반 YouTube 영상 3개
```

를 만들어서 "CC 영상 5개"라고 표시하지 않는다.

---

# 13. 기존 yt-dlp 검색 로직 점검

현재 `engine/cc_video_engine.py`를 우선 점검한다.

특히 다음을 확인한다.

### A

YouTube 검색 필터의 `CC`와 실제 `license` 필드를 혼동하고 있지 않은지 확인.

### B

`yt-dlp` 검색 결과가 반환되었다는 것만으로

```python
media_type = "singer_cc_video"
```

가 되지 않는지 확인.

### C

실제 영상의 메타데이터에서 라이선스 정보를 확인한 뒤 판정하도록 수정.

### D

라이선스 확인 실패 시:

```text
FAIL CLOSED
```

방식으로 처리한다.

즉,

```text
확인 안 됨 → 사용 가능
```

이 아니라

```text
확인 안 됨 → 검증 안 됨
```

으로 처리한다.

---

# 14. 기존 기능은 절대 깨지지 않도록 한다

다음 기능은 변경하지 않는다.

```text
기존 가수 사진 수집
기존 Media DB
기존 일반 B-roll
기존 Stage Clip
기존 영상 렌더러
기존 4개 제작 모드
기존 3~4초 CC 영상 트리밍 UI
기존 1080x1920 / 30fps 변환
기존 음소거
기존 DB FIRST 구조
```

CC 검증 기능 때문에 기존 사진 쇼츠 생성이 실패해서는 안 된다.

---

# 15. 렌더링 모드에서도 검증되지 않은 영상은 제외

기존:

```text
Mode 1 = 사진만
Mode 2 = 가수 CC 영상만
Mode 3 = 사진 + 가수 CC 영상
Mode 4 = 사진 + 가수 CC 영상 + 일반 B-roll
```

구조는 유지한다.

단,

```text
UNVERIFIED
MANUAL_REVIEW
REJECTED
```

상태의 영상은 자동 렌더링 대상에서 제외한다.

`CC_BY_VERIFIED` 영상만 자동 재사용 대상으로 한다.

---

# 16. 출처/크레딧 정보 자동 생성

CC BY 영상이 실제 쇼츠에 사용된 경우 프로젝트 metadata에 자동으로 기록한다.

예:

```text
CC BY Attribution

Title: [원본 영상 제목]
Creator: [채널명/저작자]
Source: [YouTube URL]
License: CC BY
```

YouTube 공식 안내에서도 CC BY 콘텐츠 사용 시 작품 제목, 저자, 원본 URL, 라이선스 정보를 출처 표시 정보로 제시하고 있다.

따라서 향후 YouTube 설명란 자동 생성 기능을 추가할 수 있도록 이 데이터를 프로젝트에 보존한다.

---

# 17. 반드시 테스트할 것

## Test 1 — 정상 CC BY

실제 CC BY 영상 1개를 대상으로:

```text
license 확인
→ CC_BY_VERIFIED
→ 3초 추출
→ DB 저장
```

성공 확인.

## Test 2 — 일반 YouTube 영상

```text
Standard YouTube License
→ UNVERIFIED 또는 REJECTED
→ DB 자동 저장 금지
```

확인.

## Test 3 — 자막 CC 영상

자막이 있지만 Creative Commons 라이선스가 아닌 영상:

```text
Subtitles/CC 있음
license != CC BY
```

→ CC 영상으로 판정하지 않는지 확인.

## Test 4 — 라이선스 정보 없음

```text
license = None
```

→ 자동 저장 금지.

## Test 5 — 검색 결과만 CC

검색 필터에서 CC 결과로 나왔지만 개별 영상의 라이선스 정보를 확인할 수 없는 경우:

```text
CC 검색 결과
+
license 미확인
```

→ `UNVERIFIED`

→ 자동 저장 금지.

## Test 6 — DB FIRST

이미 검증된 CC BY 클립은 다음 제작에서 외부 YouTube 검색보다 DB를 먼저 사용한다.

## Test 7 — 기존 기능 회귀 테스트

기존:

```text
사진만
사진 + 일반 B-roll
사진 + CC 영상
사진 + CC 영상 + 일반 B-roll
```

모두 정상 렌더링되는지 확인.

---

# 18. 최종 완료 조건

다음 질문에 모두 YES가 되어야 완료로 판단한다.

```text
[ ] 자막 CC와 Creative Commons CC BY를 구분한다.
[ ] 실제 license 메타데이터를 확인한다.
[ ] Standard YouTube License를 CC로 저장하지 않는다.
[ ] license 미확인 영상을 CC로 저장하지 않는다.
[ ] CC BY 확인 영상만 자동 재사용 DB에 등록한다.
[ ] 업로더 권리 확인 문제는 별도 경고한다.
[ ] 출처 URL과 채널명을 DB에 보존한다.
[ ] CC 영상이 5개 미만이어도 억지로 채우지 않는다.
[ ] 검증되지 않은 영상은 자동 렌더링에서 제외한다.
[ ] 기존 사진/B-roll/렌더링 기능에 영향을 주지 않는다.
[ ] 실제 YouTube 영상으로 통합 테스트를 완료한다.
```

## 최종 원칙

**"CC 검색 결과 = CC 영상"으로 처리하지 말 것.**

반드시:

```text
YouTube 검색
     ↓
후보 영상
     ↓
개별 영상 라이선스 확인
     ↓
Creative Commons Attribution(CC BY) 확인
     ↓
권리 경고/수동검토 여부 확인
     ↓
사용자에게 표시
     ↓
3~4초 구간 선택
     ↓
DB 저장
     ↓
향후 DB FIRST 재사용
```

구조로 구현한다.

그리고 **CC BY 영상이 충분하지 않으면 부족한 상태 그대로 보여준다. 일반 영상을 CC 영상으로 대체하지 않는다.**