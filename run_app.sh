#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
python -m streamlit run app.py
