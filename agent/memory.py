"""Long-term memory: a few facts about you, saved in data/memory.json."""
from __future__ import annotations

import json
from pathlib import Path

from .safety import find_secrets

MAX_FACTS = 100
MAX_FACT_CHARS = 200


class Memory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.facts: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.facts = [str(f) for f in data.get("facts", [])][:MAX_FACTS]
        except (OSError, ValueError, AttributeError):
            self.facts = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"facts": self.facts}, indent=2, ensure_ascii=False),
                             encoding="utf-8")

    def add(self, fact: str) -> str:
        fact = " ".join(str(fact).split())[:MAX_FACT_CHARS]
        if not fact:
            return "Nothing to remember."
        if find_secrets(fact):
            return "I won't store that because it looks like a password or key."
        if any(fact.lower() == f.lower() for f in self.facts):
            return "Already remembered."
        if len(self.facts) >= MAX_FACTS:
            return "Memory is full. Ask me to forget something first."
        self.facts.append(fact)
        self._save()
        return f"Remembered: {fact}"

    def remove(self, text: str) -> str:
        """Remove the fact that matches `text` (exact, or the only one containing it)."""
        needle = " ".join(str(text).split()).lower()
        exact = [f for f in self.facts if f.lower() == needle]
        loose = [f for f in self.facts if needle and needle in f.lower()]
        hit = exact or (loose if len(loose) == 1 else [])
        if not hit:
            return "I couldn't find exactly one matching memory." if loose else "No matching memory."
        self.facts.remove(hit[0])
        self._save()
        return f"Forgot: {hit[0]}"

    def clear(self) -> None:
        self.facts = []
        self._save()

    def prompt_block(self) -> str:
        if not self.facts:
            return "Nothing saved about the user yet."
        return "\n".join(f"- {f}" for f in self.facts)
