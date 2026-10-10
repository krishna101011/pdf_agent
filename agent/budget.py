"""The spending guard.

An agent works in a loop: think -> use a helper -> think again.
If it gets confused, that loop can run over and over and use up your credits.
This file makes sure it always stops.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Callable


class BudgetExceeded(Exception):
    """Raised when a task has used up its allowance."""


class UsageLog:
    """Remembers how many tokens were used today (saved in data/usage.json)."""

    def __init__(self, path: Path, today: Callable[[], date] = date.today):
        self.path = Path(path)
        self._today = today

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def today_total(self) -> int:
        return int(self._load().get(self._today().isoformat(), 0))

    def add(self, tokens: int) -> None:
        data = self._load()
        key = self._today().isoformat()
        data[key] = int(data.get(key, 0)) + int(tokens)
        # keep only the last 30 days so the file stays tiny
        for old in sorted(data)[:-30]:
            data.pop(old, None)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass  # not being able to save the counter must never crash the agent


class Budget:
    """Limits for ONE task (one message you send)."""

    def __init__(self, max_steps: int, max_tokens: int, delay: float = 0.0,
                 usage_log: UsageLog | None = None, daily_limit: int = 0,
                 sleep: Callable[[float], None] = time.sleep):
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.delay = delay
        self.usage_log = usage_log
        self.daily_limit = daily_limit
        self.sleep = sleep
        self.steps = 0
        self.tokens = 0

    def begin_step(self) -> None:
        """Call before every request to the AI. Raises if we should stop."""
        if self.steps >= self.max_steps:
            raise BudgetExceeded(
                f"I stopped after {self.max_steps} steps to protect your credits. "
                "Ask me to continue if you want more, or raise MAX_STEPS in .env.")
        if self.tokens >= self.max_tokens:
            raise BudgetExceeded(
                f"I stopped because this task used about {self.tokens:,} tokens "
                f"(limit {self.max_tokens:,}). Raise MAX_TOKENS_PER_TASK in .env if needed.")
        if self.usage_log and self.daily_limit and self.usage_log.today_total() >= self.daily_limit:
            raise BudgetExceeded(
                f"Daily limit reached ({self.daily_limit:,} tokens). "
                "It resets tomorrow, or raise DAILY_TOKEN_LIMIT in .env.")
        if self.steps > 0 and self.delay > 0:
            self.sleep(self.delay)  # small pause between requests
        self.steps += 1

    def add_tokens(self, n: int) -> None:
        self.tokens += max(int(n), 0)
        if self.usage_log:
            self.usage_log.add(n)
