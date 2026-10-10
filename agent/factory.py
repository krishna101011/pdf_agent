"""Puts all the pieces together."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .budget import UsageLog
from .config import Settings, load_settings
from .core import Agent
from .fake import DemoLLM
from .llm import FailoverLLM
from .memory import Memory
from .tools import build_registry
from .tools.base import Registry
from .tools.pdf import PdfSession


@dataclass
class AgentBundle:
    agent: Agent
    pdf: PdfSession
    memory: Memory
    usage: UsageLog
    settings: Settings
    registry: Registry


def build_agent(settings: Settings | None = None, llm: Any = None) -> AgentBundle:
    settings = settings or load_settings()
    memory = Memory(settings.data_dir / "memory.json")
    usage = UsageLog(settings.data_dir / "usage.json")
    pdf = PdfSession()
    registry = build_registry(settings, memory, pdf)
    if llm is None:
        llm = DemoLLM() if settings.fake_llm else FailoverLLM(settings)  # works with 0 keys: says so when you chat
    agent = Agent(llm, registry, memory, settings, usage)
    return AgentBundle(agent, pdf, memory, usage, settings, registry)
