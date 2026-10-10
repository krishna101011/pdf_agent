import json

import openai
import pytest

from agent.core import Agent
from agent.keycheck import check_key, list_models
from agent.keystore import MAX_KEYS, apply_saved, load_saved, mask, save
from agent.llm import FailoverLLM, GrokClient, LLMError
from agent.memory import Memory
from agent.tools import build_registry
from agent.tools.pdf import PdfSession
from tests.test_llm import Obj, err, good


class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def make(settings, behaviors, clock=None, sleep=None):
    """behaviors: {key: [outcome, ...]}; each call pops the next outcome for that key."""
    settings.api_keys = [(f"Key {i + 1}", k) for i, k in enumerate(behaviors)]
    log = []

    def factory(key):
        def create(**kw):
            log.append(key)
            o = behaviors[key].pop(0) if len(behaviors[key]) > 1 else behaviors[key][0]
            if isinstance(o, Exception):
                raise o
            return o
        return Obj(chat=Obj(completions=Obj(create=create)))

    clock = clock or Clock()
    llm = FailoverLLM(settings, client_factory=factory, clock=clock, sleep=sleep or (lambda s: clock.__setattr__("t", clock.t + s)))
    return llm, log, clock


def rate(retry_after=None):
    e = err(openai.RateLimitError, 429)
    if retry_after is not None:
        e.response.headers["retry-after"] = str(retry_after)
    return e


def test_switches_when_key_hits_limit_and_remembers(settings):
    llm, log, _ = make(settings, {"k1" * 6: [rate(60)], "k2" * 6: [good("from two")]})
    r = llm.chat([])
    assert r.content == "from two" and log == ["k1" * 6, "k2" * 6]
    assert llm.current == 1 and "switched to Key 2" in llm.pop_notes()[0]
    llm.chat([])
    assert log[-1] == "k2" * 6 and log.count("k1" * 6) == 1      # key 1 is resting: not asked again
    st = {s["label"]: s["state"] for s in llm.statuses()}
    assert st == {"Key 1": "resting", "Key 2": "in use"}


def test_resting_key_comes_back_after_cooldown(settings):
    llm, log, clock = make(settings, {"k1" * 6: [rate(30), good("one again")], "k2" * 6: [rate(5), good("two")]})
    assert llm.chat([]).content == "two"        # key1 rate-limited -> key2
    clock.t += 31                               # key 1 recovered; key 2 is current
    llm.until[1] = clock.t + 100                # key 2 now resting
    assert llm.chat([]).content == "one again"
    assert llm.current == 0


def test_rejected_key_is_skipped_for_good(settings):
    llm, log, clock = make(settings, {"k1" * 6: [err(openai.AuthenticationError, 401)], "k2" * 6: [good("ok")]})
    llm.chat([]); clock.t += 100000; llm.chat([])
    assert log.count("k1" * 6) == 1
    assert llm.statuses()[0]["state"] == "rejected"


def test_out_of_credits_switches(settings):
    llm, _, _ = make(settings, {"k1" * 6: [err(openai.APIStatusError, 402)], "k2" * 6: [good("ok")]})
    assert llm.chat([]).content == "ok" and "out of credits" in llm.pop_notes()[0]


def test_all_keys_down_gives_clear_message(settings):
    llm, _, _ = make(settings, {"k1" * 6: [rate(3600)], "k2" * 6: [err(openai.AuthenticationError, 401)]})
    with pytest.raises(LLMError) as e:
        llm.chat([])
    msg = str(e.value)
    assert "None of your API keys" in msg and "Key 1" in msg and "Key 2" in msg and "rejected" in msg


def test_waits_briefly_when_a_key_is_back_soon(settings):
    waits = []
    clock = Clock()
    llm, log, _ = make(settings, {"k1" * 6: [rate(4), good("back")], "k2" * 6: [rate(9)]}, clock=clock,
                       sleep=lambda s: (waits.append(s), setattr(clock, "t", clock.t + s)))
    assert llm.chat([]).content == "back"
    assert waits and waits[0] < 10 and any("Waiting" in n for n in llm.pop_notes())
    assert llm.current == 0


def test_non_key_errors_do_not_switch(settings):
    llm, log, _ = make(settings, {"k1" * 6: [err(openai.BadRequestError, 400)], "k2" * 6: [good("x")]})
    with pytest.raises(LLMError, match="invalid"):
        llm.chat([])
    assert log == ["k1" * 6]


def test_single_key_still_retries_rate_limits(settings):
    slept = []
    settings.api_keys = [("Key 1", "k1" * 6)]
    calls = {"n": 0}

    def create(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise rate()
        return good("finally")

    llm = FailoverLLM(settings, client_factory=lambda k: Obj(chat=Obj(completions=Obj(create=create))),
                      sleep=slept.append)
    assert llm.chat([]).content == "finally" and len(slept) == 2


def test_no_keys(settings):
    settings.api_keys, settings.api_key = [], ""
    llm = FailoverLLM(settings)
    assert not llm.has_keys
    with pytest.raises(LLMError, match="Settings"):
        llm.chat([])


def test_agent_shows_switch_note(settings):
    llm, _, _ = make(settings, {"k1" * 6: [rate(60)], "k2" * 6: [good("hello")]})
    mem = Memory(settings.data_dir / "m.json")
    a = Agent(llm, build_registry(settings, mem, PdfSession()), mem, settings, sleep=lambda s: None)
    r = a.send("hi")
    assert r.status == "done" and any("switched to Key 2" in e["text"] for e in r.events if e["type"] == "note")


def test_413_message_is_plain(settings):
    c = Obj(chat=Obj(completions=Obj(create=lambda **k: (_ for _ in ()).throw(err(openai.APIStatusError, 413)))))
    with pytest.raises(LLMError, match="too big"):
        GrokClient(settings, client=c).chat([])


# ---------- saving ----------
def test_keystore_roundtrip_and_apply(settings):
    assert load_saved(settings.data_dir)["keys"][0]["key"] == "" and len(load_saved(settings.data_dir)["keys"]) == MAX_KEYS
    save(settings.data_dir, "xAI Grok", "https://api.x.ai/v1", "grok-4",
         [{"label": "Main", "key": "abc12345678"}, {"label": "", "key": ""}, {"label": "Spare", "key": "def12345678"}])
    apply_saved(settings)
    assert settings.base_url == "https://api.x.ai/v1" and settings.model == "grok-4"
    assert settings.api_keys == [("Main", "abc12345678"), ("Spare", "def12345678")]   # empty slots skipped
    assert settings.all_keys()[1][0] == "Spare" and "abc12345678" in settings.secrets()
    assert (settings.data_dir / "settings.json").stat().st_mode & 0o077 == 0
    (settings.data_dir / "settings.json").write_text("garbage")
    assert load_saved(settings.data_dir)["keys"][0]["key"] == ""


def test_env_key_is_fallback_only(settings):
    settings.api_key, settings.api_keys = "envkey12345678", []
    assert settings.all_keys() == [("Key 1 (.env)", "envkey12345678")]
    settings.api_keys = [("A", "saved1234567")]
    assert settings.all_keys() == [("A", "saved1234567")]


def test_mask():
    assert mask("gsk_abcdefghijklmnop") == "gsk_...mnop" and mask("") == "" and mask("short") == "****"


def test_check_key_results(settings):
    def client(outcome):
        def create(**kw):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return Obj(chat=Obj(completions=Obj(create=create)))
    assert check_key(settings, "gsk_x1234567", client=client(good("ready", 9)))[0] == "ok"
    assert check_key(settings, "gsk_x1234567", client=client(err(openai.AuthenticationError, 401)))[0] == "bad"
    assert check_key(settings, "gsk_x1234567", client=client(rate(10)))[0] == "limited"
    status, msg = check_key(settings, "gsk_x1234567", client=client(err(openai.NotFoundError, 404)))
    assert status == "bad" and "model" in msg
    assert check_key(settings, "  ")[0] == "bad"


def test_list_models(settings):
    c = Obj(models=Obj(list=lambda: Obj(data=[Obj(id="b"), Obj(id="a")])))
    assert list_models(settings, "k", client=c) == ["a", "b"]
    bad = Obj(models=Obj(list=lambda: (_ for _ in ()).throw(RuntimeError("no"))))
    assert list_models(settings, "k", client=bad) == []
