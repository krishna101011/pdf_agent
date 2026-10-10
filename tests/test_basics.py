import json
from datetime import date

import pytest

from agent.budget import Budget, BudgetExceeded, UsageLog
from agent.memory import Memory
from agent.safety import UnsafePath, find_secrets, safe_path


def test_safe_path_ok_and_blocked(tmp_path):
    assert safe_path(tmp_path, "a/b.txt") == tmp_path.resolve() / "a" / "b.txt"
    for bad in ("../x", "a/../../x", "/etc/passwd", "C:\\Windows", "C:/x"):
        with pytest.raises(UnsafePath):
            safe_path(tmp_path, bad)


def test_find_secrets():
    assert find_secrets("hello world") == []
    assert find_secrets("key = xai-" + "a" * 30)
    assert find_secrets("token ghp_" + "b" * 30)
    assert find_secrets('password = "hunter2hunter2"')
    assert find_secrets("my value is supersecretvalue", known=["supersecretvalue"])
    assert find_secrets("short", known=["abc"]) == []


def test_budget_steps_tokens_daily(tmp_path):
    b = Budget(2, 1000)
    b.begin_step(); b.begin_step()
    with pytest.raises(BudgetExceeded):
        b.begin_step()
    b = Budget(5, 100)
    b.begin_step(); b.add_tokens(150)
    with pytest.raises(BudgetExceeded):
        b.begin_step()
    log = UsageLog(tmp_path / "u.json")
    log.add(500)
    b = Budget(5, 1000, usage_log=log, daily_limit=500)
    with pytest.raises(BudgetExceeded):
        b.begin_step()


def test_budget_delay_between_steps():
    slept = []
    b = Budget(3, 100, delay=1.5, sleep=slept.append)
    b.begin_step(); b.begin_step(); b.begin_step()
    assert slept == [1.5, 1.5]


def test_usage_log_days_and_persistence(tmp_path):
    day = {"d": date(2026, 1, 1)}
    log = UsageLog(tmp_path / "u.json", today=lambda: day["d"])
    log.add(10); log.add(5)
    assert log.today_total() == 15
    day["d"] = date(2026, 1, 2)
    assert log.today_total() == 0
    assert UsageLog(tmp_path / "u.json", today=lambda: date(2026, 1, 1)).today_total() == 15
    (tmp_path / "u.json").write_text("garbage")
    assert log.today_total() == 0


def test_memory(tmp_path):
    m = Memory(tmp_path / "m.json")
    assert "Nothing" in m.prompt_block()
    assert m.add("Studies physics").startswith("Remembered")
    assert m.add("studies physics") == "Already remembered."
    assert "password" in m.add("my key is xai-" + "z" * 30)
    assert Memory(tmp_path / "m.json").facts == ["Studies physics"]
    assert m.remove("physics").startswith("Forgot")
    assert m.facts == []
    m.add("a"); m.clear()
    assert json.loads((tmp_path / "m.json").read_text())["facts"] == []
