#!/usr/bin/env bash
# One-time setup for Linux / macOS
cd "$(dirname "$0")" || exit 1
python3 -m venv .venv || { echo "Install venv first:  sudo apt install python3-venv"; exit 1; }
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo
echo "Done. Start the app with:  ./run_app.sh   then open the Settings page and add your key."
