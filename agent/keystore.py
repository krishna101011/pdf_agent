"""Saves the AI provider, model and up to 5 API keys (data/settings.json, on your computer only).

The file is listed in .gitignore, so it is never uploaded to GitHub.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

MAX_KEYS = 5

PRESETS: dict[str, dict[str, str]] = {
    "Groq (OpenAI gpt-oss)": {"base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b"},
    "xAI Grok": {"base_url": "https://api.x.ai/v1", "model": "grok-4"},
    "Custom (any OpenAI-style service)": {},
}
DEFAULT_PRESET = "Groq (OpenAI gpt-oss)"


def settings_file(data_dir: Path) -> Path:
    return Path(data_dir) / "settings.json"


def mask(key: str) -> str:
    key = str(key or "")
    if not key:
        return ""
    return key[:4] + "..." + key[-4:] if len(key) > 10 else "****"


def blank_slots() -> list[dict]:
    return [{"label": f"Key {i + 1}", "key": ""} for i in range(MAX_KEYS)]


def load_saved(data_dir: Path) -> dict:
    """What is saved on disk, always with exactly MAX_KEYS slots."""
    try:
        data = json.loads(settings_file(data_dir).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    slots = blank_slots()
    for i, item in enumerate((data.get("keys") or [])[:MAX_KEYS]):
        if isinstance(item, dict):
            slots[i] = {"label": str(item.get("label") or f"Key {i + 1}")[:30],
                        "key": str(item.get("key") or "").strip()}
    return {"preset": data.get("preset") or "", "base_url": str(data.get("base_url") or "").strip(),
            "model": str(data.get("model") or "").strip(), "keys": slots}


def save(data_dir: Path, preset: str, base_url: str, model: str, keys: list[dict]) -> None:
    slots = blank_slots()
    for i, item in enumerate(keys[:MAX_KEYS]):
        slots[i] = {"label": str(item.get("label") or f"Key {i + 1}").strip()[:30] or f"Key {i + 1}",
                    "key": str(item.get("key") or "").strip()}
    path = settings_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"preset": preset, "base_url": base_url.strip(), "model": model.strip(),
                                "keys": slots}, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # only you can read it (ignored on Windows)
    except OSError:
        pass


def apply_saved(settings) -> None:
    """Copy the saved provider/model/keys onto a Settings object."""
    saved = load_saved(settings.data_dir)
    if saved["base_url"]:
        settings.base_url = saved["base_url"]
    if saved["model"]:
        settings.model = saved["model"]
    settings.api_keys = [(s["label"], s["key"]) for s in saved["keys"] if s["key"]]


def preset_for(base_url: str) -> str:
    for name, p in PRESETS.items():
        if p.get("base_url") == base_url:
            return name
    return "Custom (any OpenAI-style service)"
