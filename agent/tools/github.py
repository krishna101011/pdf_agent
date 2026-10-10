"""Publish a workspace folder to GitHub (needs your approval each time)."""
from __future__ import annotations

import base64
import re
from urllib.parse import quote

from ..config import Settings
from ..errors import ToolError
from .base import Tool, params
from .files import collect_files, scan_files

API = "https://api.github.com"


def _request(method: str, url: str, token: str, **kwargs):
    """One place that talks to the internet (so tests can replace it)."""
    import requests

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    return requests.request(method, url, headers=headers, timeout=30, **kwargs)


def _as_bool(value, default=True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in ("false", "0", "no", "off")


def make_github_tools(settings: Settings) -> list[Tool]:
    root = settings.workspace

    def gather(folder: str):
        files = collect_files(root, folder)
        if not files:
            raise ToolError("There are no files to upload in that folder.")
        problems = scan_files(files, settings.secrets())
        if problems:
            raise ToolError("Not uploading, because these files look like they hold secrets: "
                            + "; ".join(problems) + ". Remove the secrets first.")
        return files

    def preview(args: dict) -> str:
        try:
            files = collect_files(root, args.get("folder", "."))
        except ToolError as e:
            return f"(can't list files: {e})"
        names = "\n".join(f"  - {r}" for r, _ in files[:30]) + ("\n  ..." if len(files) > 30 else "")
        vis = "PRIVATE" if _as_bool(args.get("private"), True) else "PUBLIC (anyone can see it)"
        return (f"Publish {len(files)} file(s) from workspace/{args.get('folder', '.')}\n"
                f"to GitHub repo: {args.get('repo_name')}  [{vis}]\n"
                f"(created if it doesn't exist; files with the same name are overwritten)\n{names}")

    def publish_to_github(repo_name: str, folder: str = ".", description: str = "",
                          private=True, commit_message: str = "Add files from Study Agent") -> str:
        token = settings.github_token
        if not token:
            raise ToolError("No GitHub token. Put GITHUB_TOKEN=... in the .env file "
                            "(create one at https://github.com/settings/tokens).")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", str(repo_name)):
            raise ToolError("Repo names can only use letters, numbers, dots, dashes and underscores.")
        private = _as_bool(private, True)
        files = gather(folder)

        me = _request("GET", f"{API}/user", token)
        if me.status_code == 401:
            raise ToolError("GitHub rejected the token. Make a new one and update GITHUB_TOKEN in .env.")
        if me.status_code != 200:
            raise ToolError(f"GitHub error while checking the token (HTTP {me.status_code}).")
        owner = me.json()["login"]

        repo_url = f"{API}/repos/{owner}/{repo_name}"
        exists = _request("GET", repo_url, token).status_code == 200
        if not exists:
            created = _request("POST", f"{API}/user/repos", token, json={
                "name": repo_name, "description": description[:300], "private": private,
                "auto_init": True})
            if created.status_code == 403 or created.status_code == 404:
                raise ToolError("GitHub says this token can't create repositories. "
                                "Use a classic token with the 'repo' box ticked.")
            if created.status_code not in (200, 201, 422):
                raise ToolError(f"GitHub couldn't create the repo (HTTP {created.status_code}): "
                                f"{created.text[:200]}")

        done = 0
        for rel, path in files:
            api_path = quote(rel, safe="/")
            body = {"message": commit_message[:200] or "Update from Study Agent",
                    "content": base64.b64encode(path.read_bytes()).decode()}
            existing = _request("GET", f"{repo_url}/contents/{api_path}", token)
            if existing.status_code == 200 and isinstance(existing.json(), dict):
                body["sha"] = existing.json().get("sha")
            put = _request("PUT", f"{repo_url}/contents/{api_path}", token, json=body)
            if put.status_code not in (200, 201):
                raise ToolError(f"Uploaded {done} file(s), then GitHub refused '{rel}' "
                                f"(HTTP {put.status_code}): {put.text[:200]}")
            done += 1
        kind = "private" if private else "public"
        return f"Published {done} file(s) to https://github.com/{owner}/{repo_name} ({kind})."

    return [Tool(
        "publish_to_github",
        "Upload a workspace folder (or one file) to a GitHub repository. Creates the repo if needed. "
        "The user must approve first. Defaults to a PRIVATE repo.",
        params({"repo_name": {"type": "string"},
                "folder": {"type": "string", "description": "Workspace sub-folder or file, default '.'"},
                "description": {"type": "string"},
                "private": {"type": "boolean", "description": "default true"},
                "commit_message": {"type": "string"}}, ["repo_name"]),
        publish_to_github, needs_approval=True, preview=preview)]
