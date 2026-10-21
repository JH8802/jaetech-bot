@echo off
chcp 65001 >nul
title Blog Writer (blogdex)
cd /d "%~dp0.."

call "%~dp0find_python.bat"
if not defined PY (
  pause
  exit /b 1
)

if not exist ".env" (
  echo [안내] 저장소 폴더에 .env 파일이 없어요. 샘플 모드로 실행하려면 이 창에서 아무 키나 누르세요.
  echo        실제로 쓰려면 .env.example 을 .env 로 복사한 뒤 ANTHROPIC_API_KEY 를 넣으세요.
  pause
  set BLOGDEX_MOCK=1
)

echo.
echo  블로그 라이터를 시작합니다. 잠시 뒤 브라우저가 열려요.
echo  이 검은 창을 닫으면 서버가 꺼져요. (끌 때는 이 창에서 Ctrl+C 또는 창 닫기)
echo.
set BLOGDEX_OPEN_BROWSER=1
%PY% blogdex\app.py

echo.
echo  서버가 멈췄어요. 위쪽 오류 메시지를 확인하세요.
pause
