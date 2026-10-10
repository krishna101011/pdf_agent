"""File tools. The agent can only touch the 'workspace' folder, nothing else on your computer."""
from __future__ import annotations

import fnmatch
from pathlib import Path

from ..config import Settings
from ..errors import ToolError
from ..safety import find_secrets, safe_path
from .base import Tool, params

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}
IGNORED_FILES = [".gitkeep", ".env", ".env.*", "*.pyc", ".DS_Store", "Thumbs.db", "*.pem", "*.key"]
MAX_READ_BYTES = 100_000
MAX_WRITE_BYTES = 200_000


def _ignored_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in IGNORED_FILES)


def collect_files(root: Path, rel: str, max_files: int = 50, max_each: int = 500_000,
                  max_total: int = 3_000_000) -> list[tuple[str, Path]]:
    """Find the files inside workspace/<rel>. Returns (path-inside-the-folder, real path).
    Skips junk, secrets files and hidden tool folders."""
    base = safe_path(root, rel)
    if not base.exists():
        raise ToolError(f"'{rel}' doesn't exist in the workspace.")
    if base.is_file():
        candidates = [(base.name, base)]
    else:
        candidates = []
        for p in sorted(base.rglob("*")):
            parts = p.relative_to(base).parts
            if any(part in IGNORED_DIRS for part in parts[:-1]) or not p.is_file():
                continue
            candidates.append(("/".join(parts), p))
    files = [(r, p) for r, p in candidates if not _ignored_file(p.name)]
    if len(files) > max_files:
        raise ToolError(f"Too many files ({len(files)}). The limit is {max_files}. Pick a smaller folder.")
    total = 0
    for r, p in files:
        size = p.stat().st_size
        if size > max_each:
            raise ToolError(f"'{r}' is too big ({size:,} bytes). The per-file limit is {max_each:,}.")
        total += size
    if total > max_total:
        raise ToolError(f"These files add up to {total:,} bytes. The limit is {max_total:,}.")
    return files


def scan_files(files: list[tuple[str, Path]], known: list[str]) -> list[str]:
    """Plain-words warnings for any text file that looks like it contains a secret."""
    problems = []
    for rel, path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # pictures and other binary files
        found = find_secrets(text, known)
        if found:
            problems.append(f"{rel} (looks like it contains {', '.join(found)})")
    return problems


def make_file_tools(settings: Settings) -> list[Tool]:
    root = settings.workspace

    def list_files(folder: str = ".") -> str:
        base = safe_path(root, folder)
        if not base.exists():
            raise ToolError(f"Folder '{folder}' doesn't exist.")
        rows = []
        for p in sorted(base.rglob("*")):
            rel_parts = p.relative_to(root).parts
            if p.is_file() and not any(part in IGNORED_DIRS for part in rel_parts) and p.name != ".gitkeep":
                rows.append(f"{'/'.join(rel_parts)}  ({p.stat().st_size:,} bytes)")
            if len(rows) >= 200:
                rows.append("...(list cut at 200 files)")
                break
        return "\n".join(rows) or "(the workspace is empty)"

    def read_file(path: str) -> str:
        p = safe_path(root, path)
        if not p.is_file():
            raise ToolError(f"File '{path}' doesn't exist.")
        data = p.read_bytes()[:MAX_READ_BYTES]
        return data.decode("utf-8", errors="replace")

    def write_file(path: str, content: str) -> str:
        p = safe_path(root, path)
        if _ignored_file(p.name):
            raise ToolError(f"I won't write a file named '{p.name}'.")
        data = str(content).encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise ToolError(f"That file is too big ({len(data):,} bytes). Limit: {MAX_WRITE_BYTES:,}.")
        if find_secrets(str(content), settings.secrets()):
            raise ToolError("That content looks like it contains a password or API key, "
                            "so I didn't save it. Remove the secret and try again.")
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        p.write_bytes(data)
        return f"{'Updated' if existed else 'Saved'} workspace/{p.relative_to(Path(root).resolve()).as_posix()} ({len(data):,} bytes)."

    return [
        Tool("list_files", "List the files in the workspace folder (or a sub-folder).",
             params({"folder": {"type": "string", "description": "Sub-folder, default '.'"}}),
             list_files),
        Tool("read_file", "Read a text file from the workspace.",
             params({"path": {"type": "string", "description": "Path inside the workspace"}}, ["path"]),
             read_file),
        Tool("write_file", "Create or overwrite a text file in the workspace (code, essays, notes).",
             params({"path": {"type": "string", "description": "e.g. 'my-project/main.py'"},
                     "content": {"type": "string"}}, ["path", "content"]),
             write_file),
    ]
