@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Run setup.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo Starting Study Agent... your browser will open at http://localhost:8501
echo (Close this window to stop it.)
python -m streamlit run app.py
pause
