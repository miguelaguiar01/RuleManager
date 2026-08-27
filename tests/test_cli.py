"""main() argument handling. The interactive menu is stubbed out."""
import json

import pytest

import rule_manager as rm


def test_main_without_file_exits(monkeypatch):
    monkeypatch.setattr(rm.sys, "argv", ["rule_manager.py"])
    with pytest.raises(SystemExit) as exc:
        rm.main()
    assert exc.value.code == 1


def test_main_loads_file_and_enters_menu(monkeypatch, tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"DVCA": {"DEPENDENCIES": [], "filters": [{"logic": "or", "conditions": []}]}}))

    seen = {}
    monkeypatch.setattr(rm, "main_menu", lambda manager: seen.setdefault("manager", manager))
    monkeypatch.setattr(rm.sys, "argv", ["rule_manager.py", str(path)])

    rm.main()
    assert isinstance(seen["manager"], rm.RuleManager)
    assert "DVCA" in seen["manager"].rules


def test_main_keyboardinterrupt_exits_zero(monkeypatch, tmp_path):
    path = tmp_path / "rules.json"
    path.write_text("{}")

    def _boom(manager):
        raise KeyboardInterrupt

    monkeypatch.setattr(rm, "main_menu", _boom)
    monkeypatch.setattr(rm.sys, "argv", ["rule_manager.py", str(path)])
    with pytest.raises(SystemExit) as exc:
        rm.main()
    assert exc.value.code == 0
