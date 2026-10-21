@echo off
chcp 65001 >nul
title Blog Writer install
cd /d "%~dp0.."

call "%~dp0find_python.bat"
if not defined PY (
  pause
  exit /b 1
)

echo  필요한 패키지를 설치하는 중... (처음 한 번만, 1~2분)
%PY% -m pip install -r blogdex\requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo [오류] 설치에 실패했어요. 위쪽 메시지를 캡처해서 알려 주세요.
  pause
  exit /b 1
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo  .env 파일을 만들었어요. 메모장으로 열어 ANTHROPIC_API_KEY= 뒤에 API 키를 넣고 저장하세요.
)

echo.
echo  설치가 끝났어요. 이제 run_blogdex.bat 을 실행하세요.
pause
