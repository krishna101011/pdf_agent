#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
python -m pip install -q -r requirements-dev.txt
python -m pytest -q
