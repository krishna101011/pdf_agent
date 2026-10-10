"""Chat with the agent in the terminal (no browser needed).

Commands while chatting:
  /pdf <path>     open a PDF
  /page <number>  go to a page (the agent reads that page with your next question)
  /new            start a new chat
  /quit           leave
"""
from __future__ import annotations

import sys
from pathlib import Path

from agent.errors import ToolError
from agent.factory import build_agent


def show(res) -> None:
    for ev in res.events:
        if ev["type"] == "note":
            print(f"  ({ev['text']})")
        else:
            mark = {"ran": "ok", "error": "problem", "denied": "denied"}.get(ev["status"], "")
            print(f"  [helper: {ev['name']} - {mark}] {ev['result'][:200]}")
    if res.status == "stopped":
        print(f"\n!! {res.text}\n")
    elif res.status == "error":
        print(f"\n!! {res.text}\n")
    elif res.text:
        print(f"\nAgent: {res.text}\n")


def main() -> int:
    bundle = build_agent()
    if not bundle.settings.fake_llm and not bundle.agent.llm.has_keys:
        print("No API key yet. Start the web app and open the ⚙️ Settings page to add one "
              "(or put XAI_API_KEY=... in the .env file). Or try demo mode: STUDY_AGENT_FAKE=1")
        return 1
    agent, pdf = bundle.agent, bundle.pdf
    page = 1
    print(__doc__)
    if bundle.settings.fake_llm:
        print("*** DEMO MODE: no real AI ***\n")

    while True:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/quit", "/exit"):
            return 0
        if line == "/new":
            agent.reset()
            print("New chat started.")
            continue
        if line.startswith("/pdf"):
            try:
                n = pdf.open(Path(line[4:].strip().strip('"')))
                page = 1
                print(f"Opened {pdf.name} ({n} pages). You are on page 1.")
            except ToolError as e:
                print(f"!! {e}")
            continue
        if line.startswith("/page"):
            try:
                page = max(1, min(pdf.page_count, int(line[5:].strip())))
                print(f"You are on page {page}.")
            except ValueError:
                print("Use it like:  /page 12")
            continue

        res = agent.send(line, context=pdf.context_for(page) if pdf.is_open else "")
        show(res)
        while res.status == "needs_approval":
            print("The agent wants to do this:\n")
            print(res.preview + "\n")
            answer = input("Allow it? (yes / no): ").strip().lower()
            res = agent.resolve(answer in ("y", "yes"))
            show(res)


if __name__ == "__main__":
    sys.exit(main())
