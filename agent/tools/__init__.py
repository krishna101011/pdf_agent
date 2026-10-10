from __future__ import annotations

from ..config import Settings
from ..memory import Memory
from .base import Registry
from .email_tool import make_email_tools
from .files import make_file_tools
from .github import make_github_tools
from .memory_tools import make_memory_tools
from .mermaid import make_diagram_tools
from .pdf import PdfSession, make_pdf_tools
from .vercel import make_vercel_tools


def build_registry(settings: Settings, memory: Memory, pdf: PdfSession) -> Registry:
    registry = Registry()
    registry.add(*make_file_tools(settings))
    registry.add(*make_pdf_tools(pdf))
    registry.add(*make_diagram_tools(settings))
    registry.add(*make_memory_tools(memory))
    registry.add(*make_github_tools(settings))
    registry.add(*make_vercel_tools(settings))
    registry.add(*make_email_tools(settings))
    return registry
