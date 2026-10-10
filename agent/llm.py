"""Talks to the AI service (Groq, xAI Grok, or any OpenAI-style service).

They all speak the same "language" as OpenAI's API, so we use the `openai`
library and just point it at the right address. FailoverLLM holds up to 5 keys
and moves to the next one when a key hits its limit or stops working.
"""
from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Settings


class LLMError(Exception):
    """Something went wrong talking to the AI. The message is meant for you to read."""


class KeyProblem(LLMError):
    """The problem belongs to ONE key (so trying another key may help).

    kind: "auth"  = the key is wrong, revoked or not allowed
          "rate"  = the key hit a limit (per minute / per day)
          "quota" = the key is out of credits
    cooldown: seconds before the key is worth trying again (0 = never, until you fix it)
    """

    def __init__(self, message: str, kind: str = "rate", cooldown: float = 60.0):
        super().__init__(message)
        self.kind, self.cooldown = kind, cooldown


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    raw_arguments: str = ""
    parse_error: str = ""


@dataclass
class LLMReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens: int = 0


# Seconds to wait before each retry when the service says "slow down" or has a hiccup.
RETRY_DELAYS = (2, 5, 12, 30)
MAX_COOLDOWN = 6 * 3600


def parse_tool_call(call_id: str, name: str, raw: str) -> ToolCall:
    raw = raw or "{}"
    try:
        args = json.loads(raw)
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
        return ToolCall(call_id, name, args, raw)
    except ValueError as e:
        return ToolCall(call_id, name, {}, raw, parse_error=str(e))


def _cooldown_for(exc: Exception) -> float:
    """How long a rate-limited key should rest."""
    try:
        headers = exc.response.headers  # type: ignore[attr-defined]
        wait = float(headers.get("retry-after", ""))
        return min(max(wait, 1.0), MAX_COOLDOWN)
    except Exception:
        pass
    text = str(exc).lower()
    if "per day" in text or "daily" in text or "tpd" in text or "rpd" in text:
        return 3600.0
    return 60.0


class GrokClient:
    """One key. (The name is historical: it works with any OpenAI-style service.)"""

    def __init__(self, settings: Settings, client: Any = None,
                 sleep: Callable[[float], None] = time.sleep, retry_rate_limits: bool = True):
        if client is None:
            if not settings.api_key:
                raise LLMError("No API key found. Open ⚙️ Settings in the app and paste one "
                               "(or put it in the .env file as XAI_API_KEY=...).")
            from openai import OpenAI
            client = OpenAI(api_key=settings.api_key, base_url=settings.base_url,
                            timeout=90, max_retries=0)
        self.client = client
        self.model = settings.model
        self.sleep = sleep
        self.retry_rate_limits = retry_rate_limits

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        import openai

        kwargs: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.3}
        if tools:
            kwargs["tools"] = tools

        last_error = ""
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except openai.AuthenticationError:
                raise KeyProblem("The AI service rejected the API key. Check it in ⚙️ Settings.",
                                 "auth", 0)
            except openai.PermissionDeniedError as e:
                raise KeyProblem(f"This key isn't allowed to do that: {e}", "auth", 0)
            except openai.NotFoundError:
                raise LLMError(f"The AI service doesn't know the model '{self.model}'. "
                               "Open ⚙️ Settings and press 'Show models my key can use', "
                               "then copy one of the names.")
            except openai.BadRequestError as e:
                raise LLMError(f"The AI service said the request was invalid: {e}")
            except (openai.RateLimitError, openai.APIConnectionError,
                    openai.APITimeoutError, openai.InternalServerError) as e:
                last_error = f"{type(e).__name__}: {e}"
                is_rate = isinstance(e, openai.RateLimitError)
                if is_rate and not self.retry_rate_limits:
                    raise KeyProblem(f"hit its usage limit ({e})", "rate", _cooldown_for(e))
                if attempt == len(RETRY_DELAYS):
                    msg = ("The AI service kept refusing or timing out after several tries "
                           f"({last_error}). This can mean you're going too fast, you're out of "
                           "credits, or the internet dropped. Try again in a minute.")
                    if is_rate:
                        raise KeyProblem(msg, "rate", _cooldown_for(e))
                    raise LLMError(msg)
                self.sleep(RETRY_DELAYS[attempt])
            except openai.APIStatusError as e:
                code = getattr(e, "status_code", 0)
                if code == 402:
                    raise KeyProblem("is out of credits", "quota", 3600.0)
                if code == 413:
                    raise LLMError("That request was too big for your plan's per-minute limit. "
                                   "Try a shorter page or question, or use a bigger model/plan.")
                raise LLMError(f"The AI service returned an error (HTTP {code}): {e}")
        msg = resp.choices[0].message
        calls = []
        for i, tc in enumerate(getattr(msg, "tool_calls", None) or []):
            calls.append(parse_tool_call(tc.id or f"call_{i}", tc.function.name,
                                         tc.function.arguments))
        usage = getattr(resp, "usage", None)
        tokens = getattr(usage, "total_tokens", None)
        if not tokens:
            sent = sum(len(str(m.get("content", ""))) for m in messages)
            tokens = (sent + len(msg.content or "")) // 4  # rough guess if no count is sent
        return LLMReply(content=msg.content or "", tool_calls=calls, tokens=int(tokens))


class FailoverLLM:
    """Up to 5 keys. Uses one until it hits a limit or breaks, then switches to the next.

    A key that hit a limit rests for a while (the service tells us how long) and
    comes back by itself. A key that was rejected stays off until you fix it in Settings.
    """

    MAX_WAIT = 30.0  # if every key is resting but one is back within this many seconds, wait for it

    def __init__(self, settings: Settings, client_factory: Callable[[str], Any] | None = None,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep):
        self.slots = settings.all_keys()
        self.clock, self.sleep = clock, sleep
        n = len(self.slots)
        self.clients = [
            GrokClient(dataclasses.replace(settings, api_key=key),
                       client=client_factory(key) if client_factory else None,
                       sleep=sleep, retry_rate_limits=(n == 1))
            for _, key in self.slots]
        self.current = 0
        self.until = [0.0] * n        # resting until this time
        self.dead = [False] * n       # rejected: needs fixing in Settings
        self.reasons = [""] * n
        self.tokens = [0] * n         # tokens used per key (this session)
        self._notes: list[str] = []

    # ----- info for the screen -----
    @property
    def has_keys(self) -> bool:
        return bool(self.slots)

    def pop_notes(self) -> list[str]:
        notes, self._notes = self._notes, []
        return notes

    def statuses(self) -> list[dict]:
        now, rows = self.clock(), []
        for i, (label, key) in enumerate(self.slots):
            if self.dead[i]:
                state, detail = "rejected", self.reasons[i]
            elif self.until[i] > now:
                state, detail = "resting", f"{self.reasons[i]} (back in ~{int(self.until[i] - now) + 1}s)"
            elif i == self.current:
                state, detail = "in use", ""
            else:
                state, detail = "ready", ""
            rows.append({"index": i, "label": label, "state": state, "detail": detail,
                         "tokens": self.tokens[i]})
        return rows

    # ----- the call -----
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        if not self.slots:
            raise LLMError("No API key saved yet. Open ⚙️ Settings in the left bar, "
                           "paste a key and press Save.")
        waited = False
        while True:
            now, n = self.clock(), len(self.slots)
            for k in range(n):
                idx = (self.current + k) % n
                if self.dead[idx] or self.until[idx] > now:
                    continue
                try:
                    reply = self.clients[idx].chat(messages, tools)
                except KeyProblem as e:
                    self._mark(idx, e, now)
                    continue
                if idx != self.current:
                    old = self.current
                    self._notes.append(f"{self.slots[old][0]} {self.reasons[old] or 'was not available'}, "
                                       f"so I switched to {self.slots[idx][0]}.")
                    self.current = idx
                self.tokens[idx] += reply.tokens
                return reply
            # every key is unavailable right now
            soonest = min((self.until[i] - now for i in range(n) if not self.dead[i]), default=None)
            if soonest is not None and soonest <= self.MAX_WAIT and not waited:
                waited = True
                self._notes.append(f"All keys are at their limit. Waiting {int(soonest) + 1}s for one to come back.")
                self.sleep(soonest + 0.5)
                continue
            raise LLMError(self._all_down_message(now))

    def _mark(self, idx: int, e: KeyProblem, now: float) -> None:
        if e.kind == "auth" or e.cooldown <= 0:
            self.dead[idx] = True
            self.reasons[idx] = "was rejected (check it in ⚙️ Settings)"
        else:
            self.until[idx] = now + e.cooldown
            self.reasons[idx] = {"quota": "is out of credits"}.get(e.kind, "hit its usage limit")

    def _all_down_message(self, now: float) -> str:
        lines = []
        for i, (label, _) in enumerate(self.slots):
            if self.dead[i]:
                lines.append(f"{label}: rejected, fix it in ⚙️ Settings")
            else:
                lines.append(f"{label}: {self.reasons[i] or 'resting'}, "
                             f"try again in ~{max(1, int(self.until[i] - now))}s")
        return ("None of your API keys can be used right now.\n" + "\n".join(lines) +
                "\nAdd another key in ⚙️ Settings, or wait a little and try again.")
