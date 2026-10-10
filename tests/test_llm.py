try:
    import httpx
except ImportError:  # some openai versions ship their own copy
    import httpx2 as httpx
import openai
import pytest

from agent.llm import GrokClient, LLMError, RETRY_DELAYS


def err(cls, status):
    req = httpx.Request("POST", "https://api.x.ai/v1/chat/completions")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


class Msg:
    def __init__(self, content="hi", tool_calls=None):
        self.content, self.tool_calls = content, tool_calls


class Obj:
    def __init__(self, **kw): self.__dict__.update(kw)


def fake_client(outcomes):
    calls = []

    def create(**kw):
        calls.append(kw)
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    return Obj(chat=Obj(completions=Obj(create=create))), calls


def good(content="hi", tokens=42, tool_calls=None):
    return Obj(choices=[Obj(message=Msg(content, tool_calls))], usage=Obj(total_tokens=tokens))


def test_success_and_tokens(settings):
    c, calls = fake_client([good("hello", 42)])
    r = GrokClient(settings, client=c).chat([{"role": "user", "content": "x"}], tools=[{"a": 1}])
    assert (r.content, r.tokens) == ("hello", 42)
    assert calls[0]["model"] == settings.model and calls[0]["tools"] == [{"a": 1}]


def test_tool_calls_parsed(settings):
    tc = Obj(id="t1", function=Obj(name="list_files", arguments='{"folder": "."}'))
    bad = Obj(id="t2", function=Obj(name="x", arguments="{nope"))
    c, _ = fake_client([good("", 5, [tc, bad])])
    r = GrokClient(settings, client=c).chat([])
    assert r.tool_calls[0].arguments == {"folder": "."} and r.tool_calls[1].parse_error


def test_estimates_tokens_without_usage(settings):
    resp = Obj(choices=[Obj(message=Msg("a" * 400))], usage=None)
    c, _ = fake_client([resp])
    assert GrokClient(settings, client=c).chat([{"role": "user", "content": "b" * 400}]).tokens == 200


def test_retries_then_succeeds(settings):
    slept = []
    c, calls = fake_client([err(openai.RateLimitError, 429), err(openai.InternalServerError, 500), good()])
    r = GrokClient(settings, client=c, sleep=slept.append).chat([])
    assert r.content == "hi" and slept == list(RETRY_DELAYS[:2]) and len(calls) == 3


def test_gives_up_after_retries(settings):
    c, calls = fake_client([err(openai.RateLimitError, 429) for _ in range(10)])
    with pytest.raises(LLMError, match="kept refusing"):
        GrokClient(settings, client=c, sleep=lambda s: None).chat([])
    assert len(calls) == len(RETRY_DELAYS) + 1


@pytest.mark.parametrize("exc,text", [
    (err(openai.AuthenticationError, 401), "rejected the API key"),
    (err(openai.NotFoundError, 404), "doesn't know the model"),
    (err(openai.BadRequestError, 400), "invalid"),
    (err(openai.PermissionDeniedError, 403), "isn't allowed"),
])
def test_no_retry_errors(settings, exc, text):
    c, calls = fake_client([exc, good()])
    with pytest.raises(LLMError, match=text):
        GrokClient(settings, client=c, sleep=lambda s: pytest.fail("no retry")).chat([])
    assert len(calls) == 1


def test_no_key(settings):
    settings.api_key = ""
    with pytest.raises(LLMError, match="No API key"):
        GrokClient(settings)
