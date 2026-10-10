from __future__ import annotations

from ..memory import Memory
from .base import Tool, params


def make_memory_tools(memory: Memory) -> list[Tool]:
    return [
        Tool("remember", "Save one lasting fact about the user (name, goals, preferences, what they study). "
                         "Never save passwords or keys.",
             params({"fact": {"type": "string"}}, ["fact"]), lambda fact: memory.add(fact)),
        Tool("forget", "Delete a saved fact about the user.",
             params({"fact": {"type": "string", "description": "The fact (or a unique part of it)"}}, ["fact"]),
             lambda fact: memory.remove(fact)),
    ]
