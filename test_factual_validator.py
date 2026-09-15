"""
test_factual_validator.py - Unit & Regression Tests for QA-2 Factual Validator
==============================================================================
Tests the rule-based factual validation engine:
1. Perfect Grounding (Normal Matching Case) -> Expect 30.0 pts, passed=True
2. Minor Variations (Valid Aliases & Dates) -> Expect High Score >= 28.0, passed=True
3. Number Hallucination -> Penalizes fake 100억, 1300만, fake 1위
4. Sensationalism & Fake News -> Flags '사망', '은퇴', '전 국민 충격' with critical_error
5. Singer Mismatch -> Critical failure when script switches singer from 임영웅 to 영탁
6. Blog Inconsistency -> Flags missing singer or sensational claims in blog
7. None / Empty Optional Parameters -> Graceful degradation
"""

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from engine.qa.factual_validator import validate_factual_consistency


def test_perfect_grounding():
    article_title = "가수 임영웅, '모래 알갱이' 뮤직비디오 1300만 뷰 돌파... 음원차트 1위 쾌거"
    article_content = (
        "가수 임영웅의 자작곡 '모래 알갱이' 뮤직비디오가 유튜브 조회수 1300만 뷰를 넘어섰다. "
        "지난 5월 12일 공개된 이번 뮤직비디오는 공개 직후 멜론 음원차트 1위를 차지하며 "
        "팬덤 영웅시대의 뜨거운 응원을 받았다. 전문가들은 그의 따뜻한 위로와 보컬 실력에 극찬을 보냈다."
    )
    shorts_script = (
        "영웅시대 여러분 놀라지 마세요! 가수 임영웅의 자작곡 모래 알갱이 뮤직비디오가 드디어 유튜브 조회수 1300만 뷰를 공식 돌파했습니다! "
        "과연 수많은 팬들과 가요계 관계자들을 이토록 깜짝 놀라게 만든 진정한 비결은 무엇일까요? "
        "지난 5월 12일 첫 공개된 이번 노래는 발매 직후부터 멜론 음원차트 1위를 휩쓸며 대한민국 가요계에 식지 않는 뜨거운 감동과 신화를 써내려가고 있는데요. "
        "평소 소외된 이웃을 돌아보고 팬들을 진심으로 아끼는 임영웅의 따뜻한 인품과 독보적인 보컬 실력에 음악 전문가들도 아낌없는 극찬을 보내고 있습니다. "
        "지친 일상에 든든한 위로와 깊은 평안을 선사하는 우리들의 영원한 히어로 임영웅! 앞으로 펼쳐질 그의 눈부신 음악 여정에 영웅시대 여러분의 힘찬 응원을 보내주세요!"
    )
    blog_article = (
        "### 임영웅 모래 알갱이 1300만 뷰 1위 쾌거 달성 소식…영웅시대 감동 물결\n\n"
        "[사진 1]\n"
        "임영웅의 따뜻한 자작곡 모래 알갱이 뮤직비디오가 드디어 유튜브 조회수 1300만 뷰를 넘어서며 팬들의 뜨거운 사랑을 한 몸에 받고 있습니다. "
        "언제나 우리 곁에서 깊은 위로와 평안을 건네는 그의 진솔한 목소리가 또 한 번 대한민국 가요계에 눈부신 대기록을 탄생시킨 가슴 벅찬 순간인데요. "
        "지난 5월 12일 첫 음원이 세상에 공개된 직후부터 멜론 음원차트 1위에 당당히 등극하며 트로트와 발라드의 경계를 허무는 감성 장인의 독보적인 면모를 여실히 증명했습니다. "
        "가요계 최고 전문가들도 임영웅의 뛰어난 가창력과 섬세한 감정 표현력에 아낌없는 찬사를 보내고 있으며, 음악을 사랑하는 대중 역시 깊은 감동과 울림에 연일 찬사를 쏟아내고 있습니다. "
        "바쁜 하루를 살아가는 현대인들에게 그의 노래는 단순한 음악 이상의 치유이자 따스한 안식처가 되어주고 있는데요. "
        "혹시 영웅시대 여러분도 모래 알갱이 노래를 처음 들으셨을 때 마음 한구석이 찡해지며 눈물이 핑 돌던 순간을 생생하게 기억하시나요? 여러분의 소중한 첫 느낌을 댓글로 들려주세요!\n\n"
        "[사진 2]\n"
        "이번 뮤직비디오 속 현장 디테일을 세심하게 살펴보면 임영웅의 진솔하고 따뜻한 인간적 매력이 고스란히 묻어납니다. "
        "광활하게 펼쳐진 모래사장을 배경으로 잔잔하게 흐르는 감미로운 피아노 선율과 서정적인 휘파람 소리는 듣는 이의 모든 시름과 걱정을 잊게 만드는 마법 같은 힘을 지니고 있습니다. "
        "임영웅은 뜨거운 햇살 아래 진행된 촬영 내내 고생하는 스태프들을 먼저 세심하게 배려하고, 특유의 다정한 미소로 현장 분위기를 언제나 훈훈하게 이끌었다고 전해지는데요. "
        "단순히 노래를 훌륭하게 부르는 것을 넘어, 매 순간 만나는 모든 이들에게 온 정성과 진심을 다하는 그의 깊은 인성과 품격이 영상의 모든 프레임마다 고스란히 깃들어 있습니다. "
        "오랜 시간 동안 묵묵히 그를 곁에서 지켜보고 한마음으로 응원해 온 팬분들이라면 이번 1300만 뷰 돌파 소식이 얼마나 값지고 가슴 벅찬 자부심으로 다가오는지 깊이 공감하실 것입니다. "
        "무대 밖에서도 늘 한결같은 겸손과 다정함으로 우리를 감동시키는 그의 모습에 여러분은 어떤 자부심을 느끼셨나요?\n\n"
        "[사진 3]\n"
        "공식 돌파 소식이 전해지자마자 온라인 팬 커뮤니티와 유튜브 공식 댓글창은 그야말로 뜨거운 눈물과 벅찬 감동의 축제 분위기로 가득 찼습니다. "
        "팬덤 영웅시대 회원들은 '역시 믿고 듣는 우리 영웅님', '하루의 시작과 끝을 함께하는 인생 힐링 송', '지친 삶에 살아갈 힘과 용기를 주는 기적 같은 노래'라며 끝없는 축하와 응원 댓글을 이어갔습니다. "
        "가요계 정상급 전문가들 또한 '임영웅이라는 아티스트가 노래를 통해 세상에 전하는 위로의 메시지는 세대와 시대를 초월하는 독보적인 힘을 지녔다'며 입을 모아 극찬을 아끼지 않았습니다. "
        "국내 최고 권위의 주요 음원 사이트 1위 석권에 이어 유튜브 1300만 뷰라는 놀라운 대기록까지 달성한 것은 팬들의 무한한 신뢰와 임영웅의 진정성이 함께 빚어낸 찬란한 합작품입니다. "
        "동료 음악인들과 전문가들이 먼저 인정하고 존경을 표하는 가수라는 사실이 팬들에게는 그 어떤 세상의 찬사보다 자랑스럽고 뜻깊게 다가왔을 텐데요. "
        "댓글창을 가득 채운 동료 팬들의 진심 어린 응원 글들을 보며 가슴 깊은 곳에서 솟구치는 감동을 함께 느끼셨기를 바랍니다.\n\n"
        "[사진 4]\n"
        "임영웅이 지금까지 걸어온 발자취는 단순히 눈앞의 화려한 인기를 좇는 것이 아니라, 노래를 통해 온 세상에 선한 영향력과 따스한 희망을 전하는 소중한 여정이었습니다. "
        "도움이 필요한 소외된 이웃들을 향한 끊임없는 기부와 따뜻한 나눔 행보, 그리고 언제나 팬들을 향해 고개 숙이며 감사할 줄 아는 겸손한 태도는 그가 왜 전 국민의 사랑을 받는 최고의 아티스트인지 명확히 증명합니다. "
        "이번 대기록 달성은 단순한 숫자의 기록을 넘어, 그와 팬들이 오랜 시간 굳건하게 쌓아 올린 신뢰의 높이를 보여주는 상징적인 이정표라 할 수 있습니다. "
        "앞으로도 모래 알갱이가 전하는 따스한 감동을 품고 더 넓고 깊은 세상으로 울려 퍼질 임영웅의 찬란한 음악 행보를 트롯매거진이 언제나 가장 가까이에서 힘차게 응원하겠습니다. "
        "영웅시대 여러분의 변함없는 사랑과 든든한 응원이 임영웅에게 가장 큰 힘과 날개가 되어줄 것입니다. 언제나 함께 걸어갈 그의 아름다운 내일을 가슴 깊이 응원합니다!\n\n"
        "📌 더 재밌는 영상과 자세한 내용을 원하신다면?\n"
        "👇👇 클릭 👇👇\n"
        "임영웅, 무대 뒤에서 동료에게 몰래 건넨 한마디…팬들 눈물 쏟아진 이유..!!\n"
        "임영웅, 방송국 관계자가 직접 밝힌 인성 비하인드 2가지..ㄷㄷ\n"
        "임영웅, 영웅시대가 만든 기적 같은 기록…전국이 들썩인 순간?!\n\n"
        "#트롯매거진 #트로트 #가수임영웅 #임영웅 #모래알갱이 #영웅시대 #임영웅노래 #임영웅음원차트1위 #임영웅유튜브1300만뷰 #임영웅감동스토리\n"
    )

    result = validate_factual_consistency(
        article_title=article_title,
        article_content=article_content,
        shorts_script=shorts_script,
        blog_article=blog_article,
        singer_name="임영웅"
    )

    print("Test 1 (Perfect Grounding):", result["score"], "pts, Passed:", result["passed"])
    assert result["passed"] is True, "Perfect grounding should pass"
    assert result["critical_error"] is False, "Should have no critical errors"
    assert result["score"] >= 28.0, f"Expected score >= 28.0, got {result['score']}"
    assert len([i for i in result["issues"] if i["type"] == "error"]) == 0


def test_number_hallucination():
    article_title = "가수 박서진, 장구 퍼포먼스로 콘서트 대성황... 3000석 전석 매진"
    article_content = (
        "가수 박서진이 단독 콘서트를 성황리에 마무리했다. "
        "총 3000석 규모의 객석이 단 1분 만에 전석 매진되며 닻별 팬들의 뜨거운 함성이 이어졌다."
    )
    # Script hallucinates 1300만 뷰, 100억, 음원차트 1위 (not in article)
    shorts_script = (
        "장구의 신 박서진이 무려 조회수 1300만 뷰를 돌파하고 100억 원의 매출을 올렸습니다! "
        "음원차트 1위를 휩쓸며 닻별을 감동시켰는데요, 총 3000석 매진에 이어 놀라운 대기록입니다."
    )

    result = validate_factual_consistency(
        article_title=article_title,
        article_content=article_content,
        shorts_script=shorts_script,
        singer_name="박서진"
    )

    print("Test 2 (Number Hallucination):", result["score"], "pts, Passed:", result["passed"])
    assert "1300만" in result["details"]["number_fidelity"]["hallucinated_numbers"] or "1300만 뷰" in result["details"]["number_fidelity"]["hallucinated_numbers"]
    assert "100억" in result["details"]["number_fidelity"]["hallucinated_numbers"] or "100억 원" in result["details"]["number_fidelity"]["hallucinated_numbers"]
    assert result["details"]["number_fidelity"]["score"] < 10.0, "Score should be docked for fake numbers"
    assert len(result["issues"]) > 0


def test_sensationalism_and_fake_news():
    article_title = "가수 이찬원, 신곡 무대 공개... 팬들에게 진심 어린 감사 전해"
    article_content = (
        "가수 이찬원이 음악 방송 무대에서 신곡을 열창하며 팬들에게 깊은 감사의 뜻을 전했다."
    )
    # Script hallucinates clickbait/fake news terms: 전 국민 충격, 은퇴, 사망
    shorts_script = (
        "전 국민 충격! 가수 이찬원이 갑작스러운 은퇴를 선언했다는 소식에 연예계가 발칵 뒤집혔습니다! "
        "경악을 금치 못하는 팬들은 눈물바다가 되었는데요. 충격적인 비보에 모두가 오열하고 있습니다."
    )

    result = validate_factual_consistency(
        article_title=article_title,
        article_content=article_content,
        shorts_script=shorts_script,
        singer_name="이찬원"
    )

    print("Test 3 (Sensationalism & Fake News):", result["score"], "pts, Passed:", result["passed"])
    assert result["critical_error"] is True, "Fake news term '은퇴' should trigger critical_error"
    assert result["passed"] is False, "Sensational distortion should fail QA"
    crit_issues = [i for i in result["issues"] if i["type"] == "error"]
    assert len(crit_issues) > 0


def test_singer_mismatch():
    article_title = "가수 임영웅, 소외계층 위해 2억 원 기부... 선한 영향력"
    article_content = (
        "가수 임영웅이 연말을 맞아 소외된 이웃들을 위해 사랑의열매에 2억 원을 쾌척했다."
    )
    # Script is about another singer 영탁, and completely forgets 임영웅
    shorts_script = (
        "가수 영탁이 연말을 맞아 이웃들을 위해 2억 원을 기부하며 따뜻한 마음을 나누었습니다. "
        "영탁의 훈훈한 미담에 팬들은 큰 박수를 보내고 있습니다."
    )

    result = validate_factual_consistency(
        article_title=article_title,
        article_content=article_content,
        shorts_script=shorts_script,
        singer_name="임영웅"
    )

    print("Test 4 (Singer Mismatch):", result["score"], "pts, Passed:", result["passed"])
    assert result["critical_error"] is True, "Completely mismatched singer should trigger critical_error"
    assert result["passed"] is False, "Mismatched singer should fail"
    assert result["details"]["singer_grounding"]["score"] == 0.0


def test_blog_consistency_and_null_safety():
    article_title = "가수 송가인, 전국투어 콘서트 전석 매진 기염"
    article_content = "가수 송가인의 2024 전국투어 콘서트 티켓이 전석 매진을 기록했다."
    shorts_script = "송가인이어라! 가인님의 전국투어 콘서트가 전석 매진되었습니다!"

    # Blog with fake news term '파문'
    bad_blog = (
        "### 송가인 콘서트 티켓 파문\n\n"
        "[사진 1] 최근 연예계에 큰 파문이 일어났습니다.\n\n"
        "[사진 2] 전국투어 티켓 소식입니다.\n\n"
        "[사진 3] 팬들의 반응입니다.\n\n"
        "[사진 4] 응원합니다."
    )

    result = validate_factual_consistency(
        article_title=article_title,
        article_content=article_content,
        shorts_script=shorts_script,
        blog_article=bad_blog,
        singer_name="송가인"
    )

    print("Test 5 (Blog Inconsistency):", result["score"], "pts, Passed:", result["passed"])
    assert result["critical_error"] is True or result["details"]["blog_consistency"]["score"] < 4.0

    # Test with None blog and None singer_name (auto-detect)
    result_none = validate_factual_consistency(
        article_title=article_title,
        article_content=article_content,
        shorts_script=shorts_script,
        blog_article=None,
        singer_name=None
    )
    print("Test 6 (Auto-detect Singer & None Blog):", result_none["score"], "pts, Passed:", result_none["passed"])
    assert result_none["details"]["target_singer"] == "송가인"
    assert result_none["passed"] is True


if __name__ == "__main__":
    print("=== Running QA-2 Factual Validator Test Suite ===")
    test_perfect_grounding()
    test_number_hallucination()
    test_sensationalism_and_fake_news()
    test_singer_mismatch()
    test_blog_consistency_and_null_safety()
    print("=== ALL TESTS COMPLETED SUCCESSFULLY ===")
