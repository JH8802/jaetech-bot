@echo off
rem 진짜 Python 을 찾아 PY 변수에 넣습니다(다른 bat 에서 call 로 부름).
rem 1) py 런처(python.org 설치 때 같이 설치됨) 2) python
rem Windows 의 Microsoft Store 바로가기("가짜 python", 실행하면 'Python' 만 찍고 끝남)는 import 시험에서 걸러집니다.
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo [오류] 설치된 Python 을 찾지 못했어요.
  echo   1^) 이 창을 닫고 새로 열어서 다시 실행해 보세요. 설치 직후에는 새 창이 필요해요.
  echo   2^) 그래도 안 되면 python.org 설치 파일을 다시 실행해 "Modify" 또는 재설치하면서
  echo      "Add python.exe to PATH" 를 체크하세요.
  echo   3^) Windows 설정 - 앱 - 고급 앱 설정 - 앱 실행 별칭 에서
  echo      "앱 설치 관리자 python.exe / python3.exe" 를 끄세요.
)
