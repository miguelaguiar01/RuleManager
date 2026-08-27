"""load_rules / save_rules."""
import json

import rule_manager as rm
from helpers import and_rule, leaf


def test_missing_file_starts_fresh(tmp_path):
    m = rm.RuleManager(str(tmp_path / "does_not_exist.json"))
    assert m.rules == {}


def test_load_existing_file(tmp_path):
    data = {"DVCA": and_rule(leaf("CP_STOCK_OPT", "not in", ["D", "S"]))}
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(data))
    m = rm.RuleManager(str(path))
    assert "DVCA" in m.rules
    assert m.rules["DVCA"]["filters"][0]["conditions"][0]["operator"] == "not in"


def test_save_roundtrip(tmp_path):
    path = tmp_path / "rules.json"
    m = rm.RuleManager(str(path))
    m.rules = {"DRIP": and_rule(leaf("CP_STOCK_OPT", "==", "D"))}
    m.save_rules()

    reloaded = json.loads(path.read_text())
    assert reloaded == m.rules
    # And a fresh manager loads the same thing back.
    assert rm.RuleManager(str(path)).rules == m.rules
