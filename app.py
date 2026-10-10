"""The Study Agent screen (runs in your web browser).

Start it with run_app.bat (Windows) or:  streamlit run app.py
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from agent.errors import ToolError
from agent.factory import build_agent
from ui_settings import render_settings

st.set_page_config(page_title="Study Agent", page_icon="📚", layout="wide")

STATUS_ICON = {"ran": "✅", "error": "⚠️", "denied": "🚫"}


# ---------------------------------------------------------------- setup
def get_bundle():
    if "bundle" not in st.session_state:
        st.session_state.bundle = build_agent()   # works without a key; Settings explains
    return st.session_state.bundle


def init_state():
    defaults = {"chat": [], "pending": None, "page": 1, "seen_upload": None,
                "seen_path": "", "notice": "", "highlight": "", "include_prev": False,
                "view": None}
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


init_state()
bundle = get_bundle()
agent, pdf, memory, usage, settings = (bundle.agent, bundle.pdf, bundle.memory,
                                       bundle.usage, bundle.settings)
STUDY, SETTINGS = "💬 Study", "⚙️ Settings"
if st.session_state.view is None:  # first visit: go straight to Settings if there is no key yet
    st.session_state.view = STUDY if (settings.fake_llm or settings.all_keys()) else SETTINGS


# ---------------------------------------------------------------- helpers
def open_pdf(path: Path) -> None:
    try:
        pages = pdf.open(path)
    except ToolError as e:
        st.session_state.notice = f"⚠️ {e}"
        return
    st.session_state.page = 1
    st.session_state.notice = f"📖 Opened {pdf.name} ({pages} pages)."


def handle_result(res) -> None:
    st.session_state.chat.append({"role": "assistant", "text": res.text, "events": res.events,
                                  "status": res.status, "steps": res.steps, "tokens": res.tokens})
    st.session_state.pending = res if res.status == "needs_approval" else None


def go_page(delta: int = 0, to: int | None = None) -> None:
    target = to if to is not None else st.session_state.page + delta
    st.session_state.page = max(1, min(pdf.page_count or 1, int(target)))


def mermaid_view(code: str, key: str) -> None:
    safe = html.escape(code)
    components.html(f"""
    <div class="mermaid" style="background:white;padding:8px;border-radius:8px">{safe}</div>
    <script type="module">
      import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";
      mermaid.initialize({{ startOnLoad: true, securityLevel: "strict" }});
    </script>""", height=420, scrolling=True)


def show_events(events: list[dict], msg_index: int) -> None:
    for j, ev in enumerate(events):
        if ev["type"] == "note":
            st.caption(ev["text"])
            continue
        icon = STATUS_ICON.get(ev["status"], "•")
        with st.expander(f"{icon} Helper used: {ev['name']}"):
            st.code(json.dumps(ev["args"], indent=2, ensure_ascii=False)[:2000], language="json")
            st.text(ev["result"])
        if ev["name"] == "make_diagram" and ev["status"] == "ran":
            code = ev["args"].get("code", "")
            code = re.sub(r"^```(?:mermaid)?\s*|\s*```$", "", str(code).strip())
            mermaid_view(code, f"d{msg_index}_{j}")


def current_context() -> str:
    if not pdf.is_open:
        return ""
    return pdf.context_for(st.session_state.page, include_previous=st.session_state.include_prev,
                           highlight=st.session_state.highlight)


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("📚 Study Agent")
    st.radio("Page", [STUDY, SETTINGS], key="view", horizontal=True, label_visibility="collapsed")
    if settings.fake_llm:
        st.warning("DEMO MODE: no real AI. Try: 'draw a diagram', 'remember I study physics', "
                   "'write a file', 'publish to github'.")
    else:
        n = len(settings.all_keys())
        st.caption(f"AI: {settings.model} · {n} key{'s' if n != 1 else ''} saved")

    st.subheader("Open a PDF")
    up = st.file_uploader("Upload", type=["pdf"], label_visibility="collapsed")
    if up is not None and st.session_state.seen_upload != (up.name, up.size):
        st.session_state.seen_upload = (up.name, up.size)
        dest = settings.data_dir / "uploads"
        dest.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", up.name) or "book.pdf"
        (dest / safe_name).write_bytes(up.getvalue())
        open_pdf(dest / safe_name)

    typed = st.text_input("...or paste the path of a PDF on this computer",
                          placeholder=r"C:\Users\you\Documents\physics.pdf")
    if typed.strip() and typed.strip() != st.session_state.seen_path:
        st.session_state.seen_path = typed.strip()
        open_pdf(Path(typed.strip().strip('"')))

    if st.session_state.notice:
        st.info(st.session_state.notice)

    st.subheader("What I remember about you")
    if memory.facts:
        for f in memory.facts:
            st.write(f"• {f}")
        if st.button("Forget everything"):
            memory.clear()
            st.rerun()
    else:
        st.caption("Nothing yet. Say 'remember that I study physics'.")

    st.subheader("Usage today")
    used = usage.today_total()
    st.progress(min(1.0, used / max(1, settings.daily_token_limit)))
    st.caption(f"{used:,} of {settings.daily_token_limit:,} tokens (the daily limit you set).")

    if st.button("Start a new chat"):
        agent.reset()
        st.session_state.chat = []
        st.session_state.pending = None
        st.rerun()


# ---------------------------------------------------------------- main area
if st.session_state.view == SETTINGS:
    render_settings(bundle)
    st.stop()

if pdf.is_open:
    pdf_col, chat_col = st.columns([1, 1], gap="large")
else:
    pdf_col, chat_col = None, st.container()

if pdf_col is not None:
    with pdf_col:
        st.subheader(f"📖 {pdf.name}")
        a, b, c, d = st.columns([1, 1, 2, 2])
        a.button("◀", on_click=go_page, kwargs={"delta": -1}, disabled=st.session_state.page <= 1,
                 help="Previous page", width="stretch")
        b.button("▶", on_click=go_page, kwargs={"delta": 1}, help="Next page", width="stretch",
                 disabled=st.session_state.page >= pdf.page_count)
        c.number_input("Page", min_value=1, max_value=pdf.page_count, step=1, key="page",
                       label_visibility="collapsed")
        d.caption(f"of {pdf.page_count} pages")
        st.image(pdf.render_page(st.session_state.page, zoom=1.4), width="stretch")
        st.text_area("Highlighted text (optional) - copy a part of the page you want help with",
                     key="highlight", height=80)
        st.checkbox("Also show the agent the previous page", key="include_prev")
        if len(pdf.page_text(st.session_state.page)) < 20:
            st.warning("This page has almost no selectable text (maybe a scan or a picture). "
                       "The agent can't read it. Paste the part you mean into the box above.")
        st.caption("The agent reads the text of the page you see here whenever you ask something.")

with chat_col:
    if pdf.is_open:
        st.subheader("💬 Ask about this page")
    else:
        st.title("📚 Study Agent")
        st.caption("Ask anything, write code, or open a PDF from the left to study it together.")

    for i, m in enumerate(st.session_state.chat):
        with st.chat_message(m["role"]):
            if m["role"] == "assistant":
                show_events(m.get("events", []), i)
                if m.get("status") == "stopped":
                    st.warning(m["text"])
                elif m.get("status") == "error":
                    st.error(m["text"])
                elif m["text"]:
                    st.markdown(m["text"])
            else:
                st.markdown(m["text"])

    pending = st.session_state.pending
    if pending is not None:
        with st.container(border=True):
            st.markdown(f"**The agent wants to do this: `{pending.pending.name}`**")
            st.code(pending.preview, language="text", wrap_lines=True)
            yes, no = st.columns(2)
            decision = None
            if yes.button("✅ Approve", type="primary", width="stretch"):
                decision = True
            if no.button("🚫 Deny", width="stretch"):
                decision = False
            if decision is not None:
                with st.spinner("Working..."):
                    handle_result(agent.resolve(decision))
                st.rerun()

prompt = st.chat_input("Type your question...", disabled=st.session_state.pending is not None)
if prompt:
    st.session_state.chat.append({"role": "user", "text": prompt})
    with st.spinner("Thinking..."):
        handle_result(agent.send(prompt, context=current_context()))
    st.rerun()
