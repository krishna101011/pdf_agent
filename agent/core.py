"""The agent loop: think -> (maybe) use a helper -> think again -> answer.

Anything that publishes or sends something out into the world (GitHub, Vercel,
email) pauses the loop and waits for your OK before it runs.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .budget import Budget, BudgetExceeded, UsageLog
from .config import HARD_MAX_STEPS, Settings
from .llm import LLMError, ToolCall
from .memory import Memory
from .tools.base import Registry

MAX_TOOL_RESULT_CHARS = 8000

SYSTEM_PROMPT = """You are Study Agent, a friendly helper that sits beside the user while they study and build things.

How to talk:
- Use simple, plain words. Avoid jargon; if you must use a technical word, explain it in one short phrase.
- Be concise unless the user asks for detail. When asked to explain, go step by step.

What you can do:
- Answer questions, write code, essays and emails, and explain ideas.
- Help the user read a PDF (see "Reader context" below when it is present).
- Save files in the workspace, draw diagrams (Mermaid), publish a folder to GitHub,
  deploy a simple website to Vercel, and draft or send email.

Rules:
- If a "Reader context" block is present, it is the page the user is looking at right now.
  Words like "this question", "this example" or "this page" mean that page.
- If you need other pages, use read_pdf_pages or search_pdf. Never guess what a page says.
- Do not use tools for plain questions. Use them only when they help.
- GitHub, Vercel and email actions need the user's approval. The app asks for it automatically.
  Never say something was published or sent until the tool result says so.
- If the user says "remember ..." or shares a lasting fact about themselves, use the remember tool.
- Never write passwords, tokens or API keys into files or emails.
- If a tool returns an error, explain it simply and try at most one fix. Don't repeat the same failing call.

What you remember about the user:
{memory}
{context}"""


@dataclass
class RunResult:
    status: str                      # done | needs_approval | stopped | error
    text: str = ""
    pending: ToolCall | None = None  # the action waiting for your OK
    preview: str = ""                # human-readable description of that action
    events: list[dict] = field(default_factory=list)
    steps: int = 0
    tokens: int = 0


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n...[cut: {len(text) - limit} more characters]"


class Agent:
    def __init__(self, llm: Any, registry: Registry, memory: Memory, settings: Settings,
                 usage_log: UsageLog | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.llm = llm
        self.registry = registry
        self.memory = memory
        self.settings = settings
        self.usage_log = usage_log
        self.sleep = sleep
        self.messages: list[dict] = []
        self.budget: Budget = self._new_budget()
        self._queue: list[ToolCall] = []   # tool calls the AI asked for, not yet answered
        self._events: list[dict] = []
        self._context = ""

    # ---------- public API ----------
    def reset(self) -> None:
        self.messages = []
        self._queue = []
        self._events = []

    @property
    def waiting_for_approval(self) -> bool:
        return bool(self._queue)

    def send(self, user_text: str, context: str = "") -> RunResult:
        """Give the agent a new message. `context` is extra text for THIS message only
        (for example the PDF page you're reading)."""
        if self._queue:
            raise RuntimeError("Approve or deny the pending action first.")
        self._context = context
        self._trim_history()
        self.messages.append({"role": "user", "content": user_text})
        self.budget = self._new_budget()
        self._events = []
        return self._loop()

    def resolve(self, approved: bool) -> RunResult:
        """Answer the pending approval question."""
        if not self._queue:
            raise RuntimeError("Nothing is waiting for approval.")
        call = self._queue.pop(0)
        if approved:
            self._execute(call)
        else:
            self._events.append({"type": "tool", "name": call.name, "args": call.arguments,
                                 "result": "Denied by user.", "status": "denied"})
            self._add_tool_result(call, "The user said NO. Do not do this action. "
                                        "Ask what they would like instead.")
        return self._loop()

    # ---------- the loop ----------
    def _loop(self) -> RunResult:
        while True:
            pending = self._drain_queue()
            if pending is not None:
                return pending
            try:
                self.budget.begin_step()
            except BudgetExceeded as e:
                return self._result("stopped", str(e))
            try:
                reply = self.llm.chat(self._api_messages(), self.registry.schemas())
            except LLMError as e:
                self._collect_llm_notes()
                return self._result("error", str(e))
            self.budget.add_tokens(reply.tokens)
            self._collect_llm_notes()

            calls = list(reply.tool_calls)
            for i, c in enumerate(calls):
                if not c.id:
                    c.id = f"call_{self.budget.steps}_{i}"
            msg: dict = {"role": "assistant", "content": reply.content or ""}
            if calls:
                msg["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name,
                                  "arguments": "{}" if c.parse_error else (c.raw_arguments or json.dumps(c.arguments))}}
                    for c in calls]
            self.messages.append(msg)

            if not calls:
                return self._result("done", reply.content or "(The AI sent an empty answer.)")
            if reply.content:
                self._events.append({"type": "note", "text": reply.content})
            self._queue = calls

    def _drain_queue(self) -> RunResult | None:
        """Run queued tool calls. Stop and ask if one needs approval."""
        while self._queue:
            call = self._queue[0]
            tool = self.registry.get(call.name)
            if call.parse_error:
                self._queue.pop(0)
                self._add_tool_result(call, f"Error: your arguments were not valid JSON ({call.parse_error}).")
            elif tool is None:
                self._queue.pop(0)
                self._add_tool_result(call, f"Error: there is no tool called '{call.name}'. "
                                            f"Available: {', '.join(self.registry.names())}.")
            elif tool.needs_approval:
                try:
                    preview = tool.describe_call(call.arguments)
                except Exception as e:  # a broken preview must not crash the app
                    preview = f"(could not build a preview: {e})\n{json.dumps(call.arguments)[:800]}"
                res = self._result("needs_approval", "")
                res.pending, res.preview = call, preview
                return res
            else:
                self._queue.pop(0)
                self._execute(call)
        return None

    def _execute(self, call: ToolCall) -> None:
        result = self.registry.run(call.name, call.arguments)
        status = "error" if result.startswith("Error:") else "ran"
        self._events.append({"type": "tool", "name": call.name, "args": call.arguments,
                             "result": _truncate(result, 2000), "status": status})
        self._add_tool_result(call, result)

    def _add_tool_result(self, call: ToolCall, content: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": call.id,
                              "content": _truncate(content)})

    # ---------- helpers ----------
    def _collect_llm_notes(self) -> None:
        """Pick up messages like "Key 1 hit its limit, so I switched to Key 2"."""
        pop_notes = getattr(self.llm, "pop_notes", None)
        if pop_notes:
            for text in pop_notes():
                self._events.append({"type": "note", "text": f"🔁 {text}"})

    def _result(self, status: str, text: str) -> RunResult:
        events, self._events = self._events, []
        return RunResult(status=status, text=text, events=events,
                         steps=self.budget.steps, tokens=self.budget.tokens)

    def _new_budget(self) -> Budget:
        return Budget(min(self.settings.max_steps, HARD_MAX_STEPS),
                      self.settings.max_tokens_per_task, self.settings.delay_seconds,
                      self.usage_log, self.settings.daily_token_limit, self.sleep)

    def _system_prompt(self) -> str:
        context = f"\n{self._context}\n" if self._context else ""
        return SYSTEM_PROMPT.format(memory=self.memory.prompt_block(), context=context)

    def _api_messages(self) -> list[dict]:
        return [{"role": "system", "content": self._system_prompt()}] + self.messages

    def _trim_history(self) -> None:
        """Keep the chat short so every request stays cheap. Always cut at a user message
        so a tool answer is never separated from the question that caused it."""
        limit = self.settings.max_history_messages
        if len(self.messages) <= limit:
            return
        cut = len(self.messages) - limit
        while cut < len(self.messages) and self.messages[cut]["role"] != "user":
            cut += 1
        self.messages = self.messages[cut:]
