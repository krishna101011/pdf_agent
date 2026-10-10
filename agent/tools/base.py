"""A "tool" is a normal Python function plus a description the AI can read."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from ..errors import ToolError


def params(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., str]
    needs_approval: bool = False                 # True = the app asks you before running it
    preview: Callable[[dict], str] | None = None  # what to show you when asking

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.parameters}}

    def describe_call(self, args: dict) -> str:
        if self.preview:
            return self.preview(args)
        return json.dumps(args, indent=2, ensure_ascii=False)[:1500]


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, *tools: Tool) -> None:
        for t in tools:
            self._tools[t.name] = t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def run(self, name: str, args: dict) -> str:
        """Run a tool. Never raises: problems come back as text starting with 'Error:'."""
        tool = self.get(name)
        if tool is None:
            return f"Error: no tool called '{name}'."
        try:
            return str(tool.func(**args))
        except ToolError as e:
            return f"Error: {e}"
        except TypeError as e:
            return f"Error: wrong arguments for {name} ({e})."
        except Exception as e:  # any surprise becomes a message, not a crash
            return f"Error: {type(e).__name__}: {e}"
