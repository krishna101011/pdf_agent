@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Run setup.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
set STUDY_AGENT_FAKE=1
echo DEMO MODE: no real AI, no key needed. Opening http://localhost:8501
python -m streamlit run app.py
pause
