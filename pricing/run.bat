@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist pricing\.venv ( python -m venv pricing\.venv && pricing\.venv\Scripts\python -m pip install -r pricing\requirements.txt )
echo ===== 납품가 산출 프로그램 (내 PC에서만 접속) =====
pricing\.venv\Scripts\python -m streamlit run pricing\app.py --server.address 127.0.0.1 --server.port 8501 --server.headless false --browser.gatherUsageStats false
pause
