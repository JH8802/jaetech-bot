@echo off
chcp 65001 >nul
title Blog Writer update
cd /d "%~dp0.."

where git >nul 2>nul
if errorlevel 1 (
  echo [오류] git 을 찾을 수 없어요.
  pause
  exit /b 1
)

echo  최신 코드를 받는 중...
git pull origin claude/amazing-albattani-nyk4ho
if errorlevel 1 (
  echo.
  echo [오류] 업데이트에 실패했어요. 위쪽 메시지를 캡처해서 알려 주세요.
  pause
  exit /b 1
)

echo.
echo  필요한 패키지를 확인하는 중...
call "%~dp0find_python.bat"
if not defined PY (
  pause
  exit /b 1
)
%PY% -m pip install -r blogdex\requirements.txt --quiet --disable-pip-version-check

echo.
echo  업데이트가 끝났어요. 서버가 켜져 있었다면 끄고(run_blogdex.bat 창 닫기) 다시 실행하세요.
pause
