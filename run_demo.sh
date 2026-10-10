#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
STUDY_AGENT_FAKE=1 python -m streamlit run app.py
