@echo off
chcp 65001 >nul
cd /d "%~dp0.."
rem ---- 파이썬 찾기 (python 또는 py -3) ----
set "PYCMD="
python --version >nul 2>&1 && set "PYCMD=python"
if not defined PYCMD ( py -3 --version >nul 2>&1 && set "PYCMD=py -3" )
if not defined PYCMD (
  echo [오류] 파이썬이 설치되어 있지 않습니다. python.org 에서 Python 3.11 이상을 설치하세요.
  echo        설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
  pause
  exit /b 1
)
rem ---- 필요한 부품 설치 (처음 한 번 + requirements.txt 가 바뀌었을 때만) ----
fc /b pricing\requirements.txt pricing\.venv\requirements.installed.txt >nul 2>&1
if errorlevel 1 (
  echo 필요한 부품을 설치합니다. 처음에는 3~5분 걸립니다. 인터넷 연결이 필요합니다...
  if not exist pricing\.venv\Scripts\python.exe %PYCMD% -m venv pricing\.venv
  pricing\.venv\Scripts\python -m pip install --disable-pip-version-check -r pricing\requirements.txt
  if errorlevel 1 (
    echo [오류] 부품 설치에 실패했습니다. 인터넷 연결 또는 회사 보안 설정을 확인하세요.
    echo        pypi.org 와 files.pythonhosted.org 접속이 막혀 있으면 IT팀에 허용을 요청하세요.
    pause
    exit /b 1
  )
  copy /y pricing\requirements.txt pricing\.venv\requirements.installed.txt >nul
)
rem ---- 스트림릿 첫 실행 이메일 질문 건너뛰기 ----
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)
echo ===== 납품가 산출 프로그램 - 내 PC에서만 접속됩니다 =====
echo 잠시 후 브라우저가 열립니다. 열리지 않으면 주소창에 http://localhost:8501 을 입력하세요.
echo 이 검은 창을 닫으면 프로그램이 종료됩니다.
pricing\.venv\Scripts\python -m streamlit run pricing\app.py --server.address 127.0.0.1 --server.port 8501 --server.headless false --browser.gatherUsageStats false
pause
