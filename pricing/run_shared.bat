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
rem 같은 사내망의 다른 PC(최대 5명)가 http://[이 PC의 IP]:8501 로 접속합니다.
set /p PRICING_APP_PASSWORD=접속 비밀번호를 정하세요 (팀원에게 공유): 
set /p PRICING_ADMIN_PASSWORD=관리자 비밀번호를 정하세요 (이력 삭제 허용 변경용, 파트장만 알기, 비우면 없음): 
echo ===== 납품가 산출 프로그램 (사내망 공유 모드) =====
ipconfig | findstr /i "IPv4"
pricing\.venv\Scripts\python -m streamlit run pricing\app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false
pause
