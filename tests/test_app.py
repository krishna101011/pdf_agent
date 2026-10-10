"""Opens the real Streamlit screen (in demo mode) and clicks through it."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDY_AGENT_FAKE", "1")
    monkeypatch.setenv("STUDY_AGENT_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("STUDY_AGENT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("DELAY_SECONDS", "0")
    monkeypatch.setenv("XAI_API_KEY", "")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def texts(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)


def test_chat_works(app):
    app.chat_input[0].set_value("hello there").run()
    assert not app.exception
    assert "demo" in texts(app).lower() and "hello there" in texts(app)


def test_remember_and_memory_shows_in_sidebar(app):
    app.chat_input[0].set_value("remember I study physics").run()
    assert not app.exception
    assert "I study physics" in texts(app)


def test_approval_box_and_deny(app):
    app.chat_input[0].set_value("publish to github").run()
    labels = [b.label for b in app.button]
    assert "✅ Approve" in labels and "🚫 Deny" in labels
    assert app.chat_input[0].disabled
    next(b for b in app.button if b.label == "🚫 Deny").click().run()
    assert not app.exception
    assert "✅ Approve" not in [b.label for b in app.button]
    assert not app.chat_input[0].disabled


def test_diagram_event_renders(app):
    app.chat_input[0].set_value("draw a diagram").run()
    assert not app.exception
    assert any("make_diagram" in e.label for e in app.expander)


def test_open_pdf_by_path_and_page_context(app, make_pdf):
    pdf = make_pdf()
    app.sidebar.text_input[0].set_value(str(pdf)).run()
    assert not app.exception, app.exception
    assert "Opened book.pdf" in " ".join(i.value for i in app.sidebar.info)
    assert app.number_input[0].value == 1
    next(b for b in app.button if b.label == "▶").click().run()
    assert app.number_input[0].value == 2
    app.chat_input[0].set_value("explain this").run()
    assert not app.exception
    assert "page 2" in texts(app).lower()


def test_bad_pdf_path_shows_message(app, tmp_path):
    app.sidebar.text_input[0].set_value(str(tmp_path / "missing.pdf")).run()
    assert not app.exception
    assert "can't find" in " ".join(i.value for i in app.sidebar.info)


def test_missing_key_opens_settings_page(tmp_path, monkeypatch):
    monkeypatch.delenv("STUDY_AGENT_FAKE", raising=False)
    for name in ("XAI_API_KEY", "GROQ_API_KEY", "LLM_API_KEY"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("STUDY_AGENT_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("STUDY_AGENT_DATA", str(tmp_path / "data"))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)  # ignore a real .env
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception, at.exception
    assert any("Settings" in t.value for t in at.title)
    assert any("No API key yet" in i.value for i in at.info)
    assert len(at.sidebar.radio) == 1 and len(at.text_input) >= 2 + 5 * 2   # provider fields + 5 name/key rows


def _fresh_app(tmp_path, monkeypatch):
    monkeypatch.delenv("STUDY_AGENT_FAKE", raising=False)
    for name in ("XAI_API_KEY", "GROQ_API_KEY", "LLM_API_KEY"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("STUDY_AGENT_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("STUDY_AGENT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("DELAY_SECONDS", "0")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    return AppTest.from_file(APP, default_timeout=30).run()


def test_settings_save_and_test_keys(tmp_path, monkeypatch):
    import json
    from agent import keycheck
    monkeypatch.setattr(keycheck, "check_key", lambda s, key, base_url=None, model=None, client=None:
                        ("ok", "Works.") if key.startswith("gsk_good") else ("bad", "rejected"))
    at = _fresh_app(tmp_path, monkeypatch)
    keys = [t for t in at.text_input if (t.key or "").startswith("key_")]
    assert len(keys) == 5
    keys[0].set_value("gsk_good_one_1234567890")
    keys[1].set_value("gsk_bad_two_1234567890")
    at.run()
    next(b for b in at.button if b.label == "🔍 Test" and b.key.startswith("test_0")).click().run()
    assert any("Works." in s.value for s in at.success)
    next(b for b in at.button if b.label == "🔍 Test" and b.key.startswith("test_1")).click().run()
    assert any("rejected" in e.value for e in at.error)
    next(b for b in at.button if b.label == "💾 Save settings").click().run()
    assert not at.exception, at.exception
    saved = json.loads((tmp_path / "data" / "settings.json").read_text())
    assert [k["key"] for k in saved["keys"]][:2] == ["gsk_good_one_1234567890", "gsk_bad_two_1234567890"]
    assert saved["base_url"] == "https://api.groq.com/openai/v1" and saved["model"] == "openai/gpt-oss-120b"
    assert any("Saved" in s.value for s in at.success)
    assert any("Key 1" in m.value and "in use" in m.value for m in at.markdown)   # live status shows
    llm = at.session_state.bundle.agent.llm
    assert [l for l, _ in llm.slots] == ["Key 1", "Key 2"]
    # the stored key is masked, and remove works
    assert all("gsk_good_one_1234567890" not in str(t.value) for t in at.text_input)
    next(b for b in at.button if b.label == "🗑 Remove" and b.key.startswith("rm_1")).click().run()
    assert [l for l, _ in at.session_state.bundle.agent.llm.slots] == ["Key 1"]


def test_switch_provider_preset_fills_address_and_model(tmp_path, monkeypatch):
    at = _fresh_app(tmp_path, monkeypatch)
    at.selectbox[0].select("xAI Grok").run()
    vals = [t.value for t in at.text_input]
    assert "https://api.x.ai/v1" in vals and "grok-4" in vals
