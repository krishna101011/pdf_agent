"""Safety checks: keep files inside the workspace and keep secrets out of uploads."""
from __future__ import annotations

import re
from pathlib import Path

from .errors import ToolError


class UnsafePath(ToolError):
    pass


def safe_path(root: Path, rel: str | None) -> Path:
    """Turn a relative path into a real path that is guaranteed to be inside `root`."""
    rel = str(rel or ".").strip().replace("\\", "/") or "."
    if re.match(r"^[A-Za-z]:", rel) or rel.startswith("/"):
        raise UnsafePath("Use a path inside the workspace (like 'notes/idea.md'), not a full path.")
    root_r = Path(root).resolve()
    target = (root_r / rel).resolve()
    if target != root_r and root_r not in target.parents:
        raise UnsafePath("That path is outside the workspace folder, so I can't use it.")
    return target


_SECRET_PATTERNS = [
    ("an API key (xAI/OpenAI style)", re.compile(r"\b(?:xai|sk)-[A-Za-z0-9_\-]{20,}")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("an AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a hard-coded password/key",
     re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']")),
]


def find_secrets(text: str, known: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Return plain-words descriptions of anything in `text` that looks like a secret."""
    found: list[str] = []
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            found.append(label)
    for value in known:
        if value and len(value) >= 8 and value in text:
            found.append("one of your own saved keys/passwords")
            break
    return found
