import base64
import json

import pytest

from agent.memory import Memory
from agent.tools import build_registry, email_tool, github, vercel
from agent.tools.pdf import PdfSession


class Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code, self._data, self.text = status, data if data is not None else {}, text

    def json(self):
        return self._data


@pytest.fixture
def reg(settings):
    return build_registry(settings, Memory(settings.data_dir / "m.json"), PdfSession())


# ---------- files
def test_file_write_read_list(reg, settings):
    assert "Saved" in reg.run("write_file", {"path": "notes/a.md", "content": "hi"})
    assert (settings.workspace / "notes" / "a.md").read_text() == "hi"
    assert reg.run("read_file", {"path": "notes/a.md"}) == "hi"
    assert "notes/a.md" in reg.run("list_files", {})


def test_file_tools_refuse_bad_things(reg):
    assert reg.run("write_file", {"path": "../evil.txt", "content": "x"}).startswith("Error")
    assert reg.run("write_file", {"path": ".env", "content": "x"}).startswith("Error")
    assert reg.run("write_file", {"path": "k.txt", "content": "xai-" + "a" * 30}).startswith("Error")
    assert reg.run("write_file", {"path": "big.txt", "content": "x" * 300_000}).startswith("Error")
    assert reg.run("read_file", {"path": "missing.txt"}).startswith("Error")
    assert reg.run("write_file", {"wrong": 1}).startswith("Error")
    assert reg.run("nope", {}).startswith("Error")


# ---------- pdf
def test_pdf_session(make_pdf):
    p = PdfSession()
    n = p.open(make_pdf())
    assert n == 2 and p.name == "book.pdf"
    assert "block slides" in p.page_text(1)
    assert p.render_page(1)[:4] == b"\x89PNG"
    assert p.search("solved example")[0][0] == 2
    ctx = p.context_for(2, include_previous=True, highlight="find the speed")
    assert "currently on page 2 of 2" in ctx and "Solved example 3.2" in ctx
    assert "block slides" in ctx and "find the speed" in ctx.split("--- ")[0]


def test_pdf_errors_and_scanned_page(make_pdf, tmp_path):
    from agent.errors import ToolError
    p = PdfSession()
    assert p.context_for(1) == ""
    with pytest.raises(ToolError):
        p.open(tmp_path / "nope.pdf")
    (tmp_path / "bad.pdf").write_text("not a pdf")
    with pytest.raises(ToolError):
        p.open(tmp_path / "bad.pdf")
    p.open(make_pdf(pages=("", "text here that is long enough to count"), name="s.pdf"))
    assert "almost no selectable text" in p.context_for(1)
    with pytest.raises(ToolError):
        p.page_text(9)


def test_pdf_tools(settings, make_pdf):
    pdf = PdfSession()
    reg = build_registry(settings, Memory(settings.data_dir / "m.json"), pdf)
    assert "No PDF is open" in reg.run("pdf_info", {})
    pdf.open(make_pdf())
    assert "2 pages" in reg.run("pdf_info", {})
    assert "Solved example" in reg.run("read_pdf_pages", {"start_page": 2})
    assert "Page 2" in reg.run("search_pdf", {"query": "solved"}) or "2" in reg.run("search_pdf", {"query": "solved"})
    assert reg.run("read_pdf_pages", {"start_page": 1, "end_page": 99}).startswith("Error")


# ---------- diagrams & memory
def test_diagram_tool(reg, settings):
    out = reg.run("make_diagram", {"code": "```mermaid\nflowchart TD\n A-->B\n```", "name": "My Flow!"})
    assert "my-flow" in out and "mermaid.ink" in out
    assert (settings.workspace / "diagrams" / "my-flow.mmd").read_text().startswith("flowchart TD")
    assert reg.run("make_diagram", {"code": "hello there"}).startswith("Error")


def test_memory_tools(reg):
    assert "Remembered" in reg.run("remember", {"fact": "likes physics"})
    assert "Forgot" in reg.run("forget", {"fact": "physics"})


# ---------- github
def test_github_flow(reg, settings, monkeypatch):
    (settings.workspace / "proj").mkdir()
    (settings.workspace / "proj" / "a.py").write_text("print(1)")
    calls = []

    def fake(method, url, token, **kw):
        calls.append((method, url, kw))
        if url.endswith("/user"):
            return Resp(200, {"login": "oryx"})
        if url.endswith("/repos/oryx/demo"):
            return Resp(404)
        if method == "POST":
            return Resp(201, {})
        if method == "GET":
            return Resp(404)
        return Resp(201, {})

    monkeypatch.setattr(github, "_request", fake)
    out = reg.run("publish_to_github", {"repo_name": "demo", "folder": "proj"})
    assert "github.com/oryx/demo" in out and "private" in out
    post = next(c for c in calls if c[0] == "POST")
    assert post[2]["json"]["private"] is True
    put = next(c for c in calls if c[0] == "PUT")
    assert base64.b64decode(put[2]["json"]["content"]) == b"print(1)"
    assert reg.get("publish_to_github").needs_approval
    assert "proj" in reg.get("publish_to_github").describe_call({"repo_name": "demo", "folder": "proj"})


def test_github_blocks_secrets_and_bad_input(reg, settings, monkeypatch):
    monkeypatch.setattr(github, "_request", lambda *a, **k: pytest.fail("must not call the internet"))
    (settings.workspace / "leak").mkdir()
    (settings.workspace / "leak" / "c.py").write_text('API_KEY = "abcdefgh12345678"')
    assert "secrets" in reg.run("publish_to_github", {"repo_name": "x", "folder": "leak"})
    assert reg.run("publish_to_github", {"repo_name": "bad name!", "folder": "leak"}).startswith("Error")
    settings.github_token = ""
    assert "No GitHub token" in reg.run("publish_to_github", {"repo_name": "x"})


def test_github_bad_token(reg, settings, monkeypatch):
    (settings.workspace / "f.txt").write_text("hello")
    monkeypatch.setattr(github, "_request", lambda *a, **k: Resp(401))
    assert "rejected the token" in reg.run("publish_to_github", {"repo_name": "x", "folder": "f.txt"})


# ---------- vercel
def test_vercel(reg, settings, monkeypatch):
    site = settings.workspace / "site"
    site.mkdir()
    assert "index.html" in reg.run("deploy_to_vercel", {"folder": "site", "project_name": "x"})
    (site / "index.html").write_text("<h1>hi</h1>")
    seen = {}

    def fake_post(url, token, payload, params_=None):
        seen.update(payload=payload, token=token)
        return Resp(200, {"url": "x-abc.vercel.app"})

    monkeypatch.setattr(vercel, "_post", fake_post)
    out = reg.run("deploy_to_vercel", {"folder": "site", "project_name": "My Site"})
    assert "https://x-abc.vercel.app" in out
    assert seen["payload"]["name"] == "my-site"
    assert seen["payload"]["files"][0]["file"] == "index.html"
    (site / "app.js").write_text('const token = "abcdefgh12345678";')
    assert "secrets" in reg.run("deploy_to_vercel", {"folder": "site", "project_name": "x"})


# ---------- email
def test_email_draft_and_send(reg, settings, monkeypatch):
    out = reg.run("draft_email", {"to": "a@b.com", "subject": "Hi", "body": "Hello"})
    assert "Nothing was sent" in out
    assert len(list((settings.workspace / "emails").glob("*.txt"))) == 1
    for bad in ({"to": "nope", "subject": "s", "body": "b"},
                {"to": "a@b.com", "subject": "s\nBcc: x@y.com", "body": "b"},
                {"to": "a@b.com", "subject": "s", "body": "xai-" + "q" * 30},
                {"to": "a@b.com,b@b.com,c@b.com,d@b.com,e@b.com,f@b.com", "subject": "s", "body": "b"}):
        assert reg.run("send_email", bad).startswith("Error")

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, context=None, timeout=None):
            sent["host"] = host

        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, u, p): sent["login"] = u
        def send_message(self, msg): sent["to"] = msg["To"]

    monkeypatch.setattr(email_tool.smtplib, "SMTP_SSL", FakeSMTP)
    assert "Email sent" in reg.run("send_email", {"to": "a@b.com", "subject": "Hi", "body": "Hello"})
    assert sent["to"] == "a@b.com" and sent["login"] == "me@example.com"
    assert reg.get("send_email").needs_approval
    settings.smtp_password = ""
    assert "isn't set up" in reg.run("send_email", {"to": "a@b.com", "subject": "Hi", "body": "Hello"})
