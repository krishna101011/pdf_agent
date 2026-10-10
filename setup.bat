@echo off
cd /d "%~dp0"
echo === Study Agent setup (do this once) ===
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during install. Then run this again.
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating a private Python space...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing the parts the agent needs (a few minutes)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist .env (
  copy .env.example .env >nul
  echo.
  echo Created the .env file. Open it in VS Code and paste your Grok key after XAI_API_KEY=
)
echo.
echo Setup finished. Next: edit .env, then double-click check_grok.bat
pause
