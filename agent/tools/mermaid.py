"""Mermaid diagrams: the AI writes a few lines of text, the app draws the picture."""
from __future__ import annotations

import base64
import re

from ..config import Settings
from ..errors import ToolError
from .base import Tool, params

VALID_STARTS = ("graph", "flowchart", "sequenceDiagram", "classDiagram", "stateDiagram",
                "erDiagram", "gantt", "pie", "journey", "mindmap", "timeline", "gitGraph",
                "quadrantChart", "xychart")


def clean_code(code: str) -> str:
    code = str(code).strip()
    code = re.sub(r"^```(?:mermaid)?\s*", "", code)
    code = re.sub(r"\s*```$", "", code)
    return code.strip()


def make_diagram_tools(settings: Settings) -> list[Tool]:
    folder = settings.workspace / "diagrams"

    def make_diagram(code: str, name: str = "diagram") -> str:
        code = clean_code(code)
        first = next((ln.strip() for ln in code.splitlines()
                      if ln.strip() and not ln.strip().startswith("%%")), "")
        if not first.startswith(VALID_STARTS):
            raise ToolError("That doesn't look like Mermaid. It must start with something like "
                            "'flowchart TD', 'sequenceDiagram', 'classDiagram' or 'mindmap'.")
        if len(code) > 20_000:
            raise ToolError("That diagram is too long.")
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(name)).strip("-").lower()[:40] or "diagram"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{slug}.mmd"
        path.write_text(code + "\n", encoding="utf-8")
        link = "https://mermaid.ink/img/" + base64.urlsafe_b64encode(code.encode()).decode()
        return (f"Diagram saved as workspace/diagrams/{slug}.mmd. The app shows it to the user. "
                f"Picture link (works in a browser): {link}")

    return [Tool(
        "make_diagram",
        "Draw a diagram (flowchart, sequence, class, mindmap, ...) from Mermaid text. "
        "The app displays the picture to the user and saves the .mmd file.",
        params({"code": {"type": "string", "description": "Mermaid text, e.g. 'flowchart TD\\n A-->B'"},
                "name": {"type": "string", "description": "Short file name, e.g. 'energy-flow'"}}, ["code"]),
        make_diagram)]
