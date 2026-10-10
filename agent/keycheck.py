"""Tests one API key with a tiny message, and lists the models a key can use."""
from __future__ import annotations

import dataclasses
from typing import Any

from .config import Settings
from .llm import GrokClient, KeyProblem, LLMError


def check_key(settings: Settings, key: str, base_url: str | None = None, model: str | None = None,
              client: Any = None) -> tuple[str, str]:
    """Returns (status, plain-words message). status: ok | limited | bad."""
    if not key.strip():
        return "bad", "No key to test. Paste one first."
    s = dataclasses.replace(settings, api_key=key.strip(), api_keys=[],
                            base_url=base_url or settings.base_url, model=model or settings.model)
    try:
        reply = GrokClient(s, client=client, retry_rate_limits=False).chat(
            [{"role": "user", "content": "Reply with the single word: ready"}])
    except KeyProblem as e:
        if e.kind == "auth":
            return "bad", "The service rejected this key. Check you copied all of it, and that it matches the provider you chose."
        if e.kind == "quota":
            return "limited", "The key is valid but out of credits."
        return "limited", "The key is valid but is at its usage limit right now. It will work again later."
    except LLMError as e:
        return "bad", str(e)
    except Exception as e:  # never crash the settings page
        return "bad", f"Couldn't reach the service ({type(e).__name__}: {e})."
    return "ok", f"Works. The AI answered {reply.content.strip()[:40]!r} (about {reply.tokens} tokens used)."


def list_models(settings: Settings, key: str, base_url: str | None = None,
                client: Any = None) -> list[str]:
    try:
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=key.strip(), base_url=base_url or settings.base_url,
                            timeout=30, max_retries=0)
        return sorted(m.id for m in client.models.list().data)
    except Exception:
        return []
