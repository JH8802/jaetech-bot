@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist pricing\.venv ( python -m venv pricing\.venv && pricing\.venv\Scripts\python -m pip install -r pricing\requirements.txt )
rem 같은 사내망의 다른 PC(최대 5명)가 http://[이 PC의 IP]:8501 로 접속합니다.
set /p PRICING_APP_PASSWORD=접속 비밀번호를 정하세요 (팀원에게 공유): 
set /p PRICING_ADMIN_PASSWORD=관리자 비밀번호를 정하세요 (이력 삭제 허용 변경용, 파트장만 알기, 비우면 없음): 
echo ===== 납품가 산출 프로그램 (사내망 공유 모드) =====
ipconfig | findstr /i "IPv4"
pricing\.venv\Scripts\python -m streamlit run pricing\app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false
pause
