import pytest

from agent.core import Agent
from agent.factory import build_agent
from agent.fake import ScriptedLLM, call_reply, text_reply
from agent.llm import LLMError, LLMReply, ToolCall
from agent.memory import Memory
from agent.budget import UsageLog
from agent.tools import build_registry, github
from agent.tools.pdf import PdfSession


def make(settings, replies, pdf=None):
    mem = Memory(settings.data_dir / "m.json")
    reg = build_registry(settings, mem, pdf or PdfSession())
    llm = ScriptedLLM(replies)
    return Agent(llm, reg, mem, settings, UsageLog(settings.data_dir / "u.json"), sleep=lambda s: None), llm


def test_plain_answer(settings):
    a, llm = make(settings, [text_reply("Hi!")])
    r = a.send("hello")
    assert (r.status, r.text, r.steps) == ("done", "Hi!", 1)
    assert llm.calls[0][0]["role"] == "system" and llm.calls[0][-1]["content"] == "hello"


def test_tool_loop_then_answer(settings):
    a, llm = make(settings, [call_reply("write_file", {"path": "a.txt", "content": "x"}), text_reply("Saved it.")])
    r = a.send("save a file")
    assert r.status == "done" and r.steps == 2
    assert r.events[0]["name"] == "write_file" and r.events[0]["status"] == "ran"
    assert (settings.workspace / "a.txt").exists()
    roles = [m["role"] for m in a.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]


def test_unknown_tool_and_bad_json_are_handled(settings):
    bad = LLMReply("", [ToolCall("c1", "write_file", {}, "{oops", parse_error="bad json")], 10)
    a, _ = make(settings, [call_reply("does_not_exist", {}), bad, text_reply("ok")])
    r = a.send("go")
    assert r.status == "done"
    tool_msgs = [m["content"] for m in a.messages if m["role"] == "tool"]
    assert "no tool called" in tool_msgs[0] and "not valid JSON" in tool_msgs[1]
    assert a.messages[3]["tool_calls"][0]["function"]["arguments"] == "{}"


def test_approval_approve(settings, monkeypatch):
    (settings.workspace / "f.txt").write_text("hi")
    monkeypatch.setattr(github, "_request", lambda m, u, t, **k: type("R", (), {
        "status_code": 200 if u.endswith("/user") else (200 if "/contents/" not in u and "user/repos" not in u else 201),
        "json": lambda s: {"login": "me", "sha": "s"}, "text": ""})())
    a, _ = make(settings, [call_reply("publish_to_github", {"repo_name": "r", "folder": "f.txt"}), text_reply("Published.")])
    r = a.send("publish")
    assert r.status == "needs_approval" and r.pending.name == "publish_to_github" and "f.txt" in r.preview
    assert a.waiting_for_approval
    with pytest.raises(RuntimeError):
        a.send("another")
    r2 = a.resolve(True)
    assert r2.status == "done" and r2.events[0]["status"] == "ran"
    assert "Published" in r2.text and not a.waiting_for_approval


def test_approval_deny_runs_nothing(settings, monkeypatch):
    monkeypatch.setattr(github, "_request", lambda *a, **k: pytest.fail("must not run"))
    (settings.workspace / "f.txt").write_text("hi")
    a, llm = make(settings, [call_reply("publish_to_github", {"repo_name": "r", "folder": "f.txt"}), text_reply("Okay, not doing it.")])
    a.send("publish")
    r = a.resolve(False)
    assert r.status == "done" and r.events[0]["status"] == "denied"
    assert "said NO" in llm.calls[-1][-1]["content"]
    with pytest.raises(RuntimeError):
        a.resolve(True)


def test_step_limit_stops_runaway_loop(settings):
    loop = [call_reply("list_files", {}, call_id=f"c{i}") for i in range(20)]
    a, llm = make(settings, loop)
    r = a.send("loop forever")
    assert r.status == "stopped" and "5 steps" in r.text and len(llm.calls) == 5


def test_token_limit_and_daily_limit(settings):
    settings.max_tokens_per_task = 1000
    a, _ = make(settings, [call_reply("list_files", {}, tokens=2000), text_reply("never")])
    assert "tokens" in a.send("x").text
    settings.max_tokens_per_task = 60000
    settings.daily_token_limit = 100
    (settings.data_dir / "u.json").unlink()  # fresh day
    a2, _ = make(settings, [text_reply("hi", tokens=500)])
    assert a2.send("x").status == "done"
    r = a2.send("again")
    assert r.status == "stopped" and "Daily limit" in r.text


def test_llm_error_becomes_result(settings):
    class Boom:
        def chat(self, m, t=None): raise LLMError("no internet")
    a, _ = make(settings, [])
    a.llm = Boom()
    r = a.send("x")
    assert r.status == "error" and "no internet" in r.text


def test_reader_context_only_for_this_message(settings, make_pdf):
    pdf = PdfSession(); pdf.open(make_pdf())
    a, llm = make(settings, [text_reply("a"), text_reply("b")], pdf)
    a.send("explain this", context=pdf.context_for(2))
    a.send("thanks", context="")
    assert "Solved example 3.2" in llm.calls[0][0]["content"]
    assert "Solved example 3.2" not in llm.calls[1][0]["content"]
    assert not any("Solved example" in str(m.get("content")) for m in a.messages)


def test_memory_goes_into_prompt(settings):
    a, llm = make(settings, [text_reply("ok")])
    a.memory.add("Studies physics")
    a.send("hi")
    assert "Studies physics" in llm.calls[0][0]["content"]


def test_history_trim_keeps_tool_pairs(settings):
    settings.max_history_messages = 6
    replies = []
    for i in range(8):
        replies += [call_reply("list_files", {}, call_id=f"c{i}"), text_reply(f"done {i}")]
    a, _ = make(settings, replies)
    for i in range(8):
        a.send(f"q{i}")
        assert a.messages[0]["role"] == "user"
        for j, m in enumerate(a.messages):
            if m["role"] == "tool":
                assert a.messages[j - 1]["role"] in ("assistant", "tool")
    assert len(a.messages) <= 12


def test_reset(settings):
    a, _ = make(settings, [text_reply("x")])
    a.send("hi"); a.reset()
    assert a.messages == [] and not a.waiting_for_approval


def test_factory_demo_and_missing_key(settings):
    settings.fake_llm = True
    b = build_agent(settings)
    assert b.agent.send("draw a diagram").status == "done"
    settings.fake_llm, settings.api_key, settings.api_keys = False, "", []
    r = build_agent(settings).agent.send("hello")      # no key: a clear message, not a crash
    assert r.status == "error" and "Settings" in r.text
