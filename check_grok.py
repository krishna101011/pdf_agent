"""Checks that your API keys work and shows which model names they can use.

Run:  python check_grok.py     (or double-click check_grok.bat on Windows)
It sends ONE tiny message per key (a few tokens each).
Keys come from the app's Settings page (up to 5) or from XAI_API_KEY in .env.
"""
from __future__ import annotations

import sys

from agent.config import load_settings
from agent.keycheck import check_key, list_models


def main() -> int:
    s = load_settings()
    keys = s.all_keys()
    if not keys:
        print("No key found. Open the app's ⚙️ Settings page and add one, or fill XAI_API_KEY in .env")
        return 1
    print(f"Address: {s.base_url}\nModel:   {s.model}\n")
    worst = 0
    for label, key in keys:
        status, msg = check_key(s, key)
        print(f"[{status.upper():7}] {label} (ends ...{key[-4:]}): {msg}")
        if status != "ok":
            worst = 1
    models = list_models(s, keys[0][1])
    if models:
        print("\nModels the first key can use:")
        for m in models:
            print("  -", m)
        if s.model not in models:
            print(f"\n!! '{s.model}' is not in that list. Pick a name above and put it in Settings > Model name.")
    return worst


if __name__ == "__main__":
    sys.exit(main())
