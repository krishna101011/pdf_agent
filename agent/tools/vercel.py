"""Put a simple website (HTML/CSS/JS files) online with Vercel. Needs your approval."""
from __future__ import annotations

import base64
import re

from ..config import Settings
from ..errors import ToolError
from .base import Tool, params
from .files import collect_files, scan_files

API = "https://api.vercel.com/v13/deployments"
SITE_EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".png", ".jpg", ".jpeg",
                   ".gif", ".webp", ".ico", ".txt", ".md", ".woff", ".woff2", ".mp3", ".mp4"}


def _post(url: str, token: str, payload: dict, params_: dict | None = None):
    """One place that talks to the internet (so tests can replace it)."""
    import requests

    return requests.post(url, params=params_, json=payload, timeout=60,
                         headers={"Authorization": f"Bearer {token}"})


def make_vercel_tools(settings: Settings) -> list[Tool]:
    root = settings.workspace

    def site_files(folder: str):
        files = [(r, p) for r, p in collect_files(root, folder, max_total=4_000_000)
                 if p.suffix.lower() in SITE_EXTENSIONS]
        if not any(r == "index.html" for r, _ in files):
            raise ToolError("The folder needs an 'index.html' file at its top level.")
        return files

    def preview(args: dict) -> str:
        try:
            files = site_files(args.get("folder", "."))
        except ToolError as e:
            return f"(can't list files: {e})"
        names = "\n".join(f"  - {r}" for r, _ in files[:30])
        return (f"Deploy {len(files)} file(s) from workspace/{args.get('folder', '.')} "
                f"as a PUBLIC website named '{args.get('project_name')}' on Vercel.\n{names}")

    def deploy_to_vercel(folder: str, project_name: str) -> str:
        if not settings.vercel_token:
            raise ToolError("No Vercel token. Put VERCEL_TOKEN=... in the .env file "
                            "(create one at https://vercel.com/account/tokens).")
        name = re.sub(r"[^a-z0-9-]+", "-", str(project_name).lower()).strip("-")[:50]
        if not name:
            raise ToolError("Give the project a name using letters and numbers.")
        files = site_files(folder)
        problems = scan_files(files, settings.secrets())
        if problems:
            raise ToolError("Not deploying, because these files look like they hold secrets: "
                            + "; ".join(problems))
        payload = {
            "name": name,
            "files": [{"file": rel, "data": base64.b64encode(p.read_bytes()).decode(),
                       "encoding": "base64"} for rel, p in files],
            "projectSettings": {"framework": None},
            "target": "production",
        }
        query = {"teamId": settings.vercel_team_id} if settings.vercel_team_id else None
        r = _post(API, settings.vercel_token, payload, query)
        if r.status_code in (401, 403):
            raise ToolError("Vercel rejected the token. Check VERCEL_TOKEN in .env.")
        if r.status_code not in (200, 201):
            raise ToolError(f"Vercel couldn't deploy (HTTP {r.status_code}): {r.text[:300]}")
        data = r.json()
        url = data.get("url", "")
        return (f"Deployed {len(files)} file(s). Your site: https://{url}"
                if url else "Vercel accepted the deployment but sent no address. Check your Vercel dashboard.")

    return [Tool(
        "deploy_to_vercel",
        "Deploy a simple static website (index.html + css/js/images) from a workspace folder to Vercel. "
        "The user must approve first.",
        params({"folder": {"type": "string", "description": "Workspace folder that contains index.html"},
                "project_name": {"type": "string"}}, ["folder", "project_name"]),
        deploy_to_vercel, needs_approval=True, preview=preview)]
