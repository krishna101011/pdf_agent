"""Pretend AIs that need no internet and no key.

- ScriptedLLM: plays back answers you give it. Used by the tests.
- DemoLLM: a tiny rule-based "AI" so you can click around the app before
  you have a Grok key (start the app with run_demo.bat).
"""
from __future__ import annotations

import re

from .llm import LLMReply, ToolCall


def text_reply(text: str, tokens: int = 50) -> LLMReply:
    return LLMReply(content=text, tool_calls=[], tokens=tokens)


def call_reply(name: str, args: dict, call_id: str = "c1", text: str = "", tokens: int = 50) -> LLMReply:
    import json
    raw = json.dumps(args)
    return LLMReply(content=text, tool_calls=[ToolCall(call_id, name, args, raw)], tokens=tokens)


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools=None):
        self.calls.append(list(messages))
        if self.replies:
            return self.replies.pop(0)
        return text_reply("(script finished)", tokens=1)


class DemoLLM:
    """Offline stand-in. Understands a few trigger words so every feature can be tried."""

    def chat(self, messages, tools=None):
        system = messages[0]["content"]
        last = messages[-1]
        if last["role"] == "tool":
            return text_reply(f"(demo) The helper finished. It said: {str(last['content'])[:300]}")

        user = str(last.get("content", ""))
        low = user.lower()
        if "diagram" in low or "flowchart" in low:
            return call_reply("make_diagram", {
                "name": "demo_flow",
                "code": "flowchart TD\n  A[You ask] --> B[Agent thinks]\n  B --> C{Needs a helper?}\n"
                        "  C -- yes --> D[Runs the helper]\n  D --> B\n  C -- no --> E[Answers you]",
            }, text="I'll draw that for you.")
        if low.startswith("remember"):
            return call_reply("remember", {"fact": user[len("remember"):].strip(" :,.")})
        if "publish" in low and "github" in low:
            return call_reply("publish_to_github", {"repo_name": "study-agent-demo", "folder": "."},
                              text="I'd like to publish your workspace to GitHub.")
        if "write a file" in low or "save a file" in low:
            return call_reply("write_file", {"path": "demo/hello.txt",
                                             "content": "Hello from the demo agent!\n"})

        page = re.search(r"currently on page (\d+) of (\d+)", system)
        if page:
            snippet = system.split("Page text", 1)[-1].strip()[:200].replace("\n", " ")
            return text_reply(f"(demo) I can see you're on page {page.group(1)} of {page.group(2)}. "
                              f"The page starts: \"{snippet}\". A real Grok key would explain it.")
        return text_reply(f"(demo) You said: {user[:200]}. No PDF is open, and this is demo mode "
                          "(no real AI). Try: 'draw a diagram', 'remember I like physics', "
                          "'publish to github', or open a PDF.")
