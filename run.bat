@echo off
chcp 65001 > nul
echo ===================================================
echo   🎙️ AI 트로트 쇼츠 & 블로그 자동 생성 스튜디오
echo ===================================================
echo 잠시만 기다려 주세요. 웹 브라우저가 실행됩니다...
echo.

set PYTHONPATH=.
streamlit run app.py --server.port 8501

pause
