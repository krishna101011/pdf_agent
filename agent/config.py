"""All settings live here. Values come from the .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent

# Safety ceiling: even if you type a bigger number in .env, one task never
# takes more than this many steps.
HARD_MAX_STEPS = 30


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


@dataclass
class Settings:
    # The AI service. Default: Groq running OpenAI's open "gpt-oss" model.
    # (Both can be changed on the app's Settings page.)
    api_key: str = ""                              # one key, e.g. from .env
    api_keys: list = field(default_factory=list)   # up to 5 (label, key) pairs from the Settings page
    base_url: str = "https://api.groq.com/openai/v1"
    model: str = "openai/gpt-oss-120b"

    max_steps: int = 8
    max_tokens_per_task: int = 60000
    daily_token_limit: int = 500000
    delay_seconds: float = 1.0
    max_history_messages: int = 30

    workspace: Path = ROOT / "workspace"
    data_dir: Path = ROOT / "data"

    github_token: str = ""
    vercel_token: str = ""
    vercel_team_id: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""

    fake_llm: bool = False  # demo mode: no internet, no key, scripted answers

    def secrets(self) -> list[str]:
        """Values that must never be written into files or sent anywhere."""
        own = [k for _, k in self.all_keys()]
        return [s for s in (*own, self.api_key, self.github_token, self.vercel_token,
                            self.smtp_password) if s and len(s) >= 8]

    def all_keys(self) -> list[tuple[str, str]]:
        """The (label, key) pairs the agent will use, in switching order."""
        keys = [(str(l or f"Key {i + 1}"), str(k).strip()) for i, (l, k) in enumerate(self.api_keys)
                if str(k).strip()]
        if not keys and self.api_key:
            keys = [("Key 1 (.env)", self.api_key)]
        return keys


def load_settings(env_file: Path | None = None) -> Settings:
    if load_dotenv is not None:
        load_dotenv(env_file or ROOT / ".env", override=False)

    s = Settings(
        api_key=(os.getenv("XAI_API_KEY") or os.getenv("GROQ_API_KEY")
                 or os.getenv("LLM_API_KEY") or "").strip(),
        base_url=os.getenv("GROK_BASE_URL", "").strip() or "https://api.groq.com/openai/v1",
        model=os.getenv("GROK_MODEL", "").strip() or "openai/gpt-oss-120b",
        max_steps=min(max(_int("MAX_STEPS", 8), 1), HARD_MAX_STEPS),
        max_tokens_per_task=max(_int("MAX_TOKENS_PER_TASK", 60000), 1000),
        daily_token_limit=max(_int("DAILY_TOKEN_LIMIT", 500000), 0),
        delay_seconds=max(_float("DELAY_SECONDS", 1.0), 0.0),
        github_token=os.getenv("GITHUB_TOKEN", "").strip(),
        vercel_token=os.getenv("VERCEL_TOKEN", "").strip(),
        vercel_team_id=os.getenv("VERCEL_TEAM_ID", "").strip(),
        smtp_host=os.getenv("SMTP_HOST", "").strip() or "smtp.gmail.com",
        smtp_port=_int("SMTP_PORT", 465),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
        fake_llm=os.getenv("STUDY_AGENT_FAKE", "").strip() in ("1", "true", "yes"),
    )
    # Optional: keep the agent's folders somewhere else (the tests use this).
    if os.getenv("STUDY_AGENT_WORKSPACE"):
        s.workspace = Path(os.environ["STUDY_AGENT_WORKSPACE"])
    if os.getenv("STUDY_AGENT_DATA"):
        s.data_dir = Path(os.environ["STUDY_AGENT_DATA"])
    # Whatever you saved on the Settings page wins over .env
    from .keystore import apply_saved
    apply_saved(s)
    s.workspace.mkdir(parents=True, exist_ok=True)
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
