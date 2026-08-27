"""Condition CRUD, nested blocks, navigation, and edit_condition."""
import rule_manager as rm


def test_add_condition_without_current_block(manager):
    # No Swift code selected -> no block -> cannot add.
    assert manager.add_condition("CP_STOCK_OPT", "==", "S") is False


def test_add_condition_to_root(manager):
    manager.add_swift_code("DVCA")
    assert manager.add_condition("CP_STOCK_OPT", "not in", ["D", "S"]) is True
    conds = manager.rules["DVCA"]["filters"][0]["conditions"]
    assert conds == [{"column": "CP_STOCK_OPT", "operator": "not in", "value": ["D", "S"]}]


def test_add_column_comparison(manager):
    manager.add_swift_code("SPLR")
    assert manager.add_column_comparison("CP_RATIO_OLD", ">", "CP_RATIO_NEW") is True
    cond = manager.rules["SPLR"]["filters"][0]["conditions"][0]
    assert cond["comparison"] == "column_vs_column"
    assert cond["column1"] == "CP_RATIO_OLD"
    assert cond["column2"] == "CP_RATIO_NEW"


def test_add_nested_block_and_navigate(manager):
    manager.add_swift_code("TEND")
    assert manager.add_nested_block("AND") is True  # logic lower-cased
    nested = manager.rules["TEND"]["filters"][0]["conditions"][0]
    assert nested == {"logic": "and", "conditions": []}

    # Navigate into the nested block, add a condition there.
    assert manager.navigate_into(0) is True
    assert manager.current_path == [0]
    manager.add_condition("mnemonic", "==", "DVD_CASH")
    assert nested["conditions"][0]["column"] == "mnemonic"


def test_navigate_into_non_block_fails(manager):
    manager.add_swift_code("TEND")
    manager.add_condition("mnemonic", "==", "DVD_CASH")  # a leaf, not a block
    assert manager.navigate_into(0) is False
    assert manager.current_path == []


def test_navigate_up_and_root(manager):
    manager.add_swift_code("TEND")
    manager.add_nested_block("and")
    manager.navigate_into(0)
    manager.add_nested_block("or")
    manager.navigate_into(0)
    assert manager.current_path == [0, 0]
    assert manager.navigate_up() is True
    assert manager.current_path == [0]
    manager.navigate_root()
    assert manager.current_path == []
    assert manager.navigate_up() is False  # already at root


def test_get_current_condition_block_bad_path_returns_none(manager):
    manager.add_swift_code("TEND")
    manager.current_path = [5]  # out of range
    assert manager.get_current_condition_block() is None


def test_delete_condition(manager):
    manager.add_swift_code("DVCA")
    manager.add_condition("a", "==", "1")
    manager.add_condition("b", "==", "2")
    assert manager.delete_condition(0) is True
    conds = manager.rules["DVCA"]["filters"][0]["conditions"]
    assert [c["column"] for c in conds] == ["b"]
    assert manager.delete_condition(9) is False  # out of range


def test_change_logic(manager):
    manager.add_swift_code("DVCA")
    assert manager.rules["DVCA"]["filters"][0]["logic"] == "or"
    assert manager.change_logic("AND") is True
    assert manager.rules["DVCA"]["filters"][0]["logic"] == "and"


def _scripted_prompt(answers):
    """Return a fake Prompt.ask that pops answers in order, ignoring default."""
    it = iter(answers)

    def _ask(*args, **kwargs):
        return next(it)

    return _ask


def test_edit_condition_leaf(manager, monkeypatch):
    manager.add_swift_code("DVCA")
    manager.add_condition("CP_STOCK_OPT", "==", "S")
    # New column / operator / value; comma -> list.
    monkeypatch.setattr(rm.Prompt, "ask", _scripted_prompt(["CP_STOCK_OPT", "not in", "D,S"]))
    assert manager.edit_condition(0) is True
    cond = manager.rules["DVCA"]["filters"][0]["conditions"][0]
    assert cond == {"column": "CP_STOCK_OPT", "operator": "not in", "value": ["D", "S"]}


def test_edit_condition_numeric_coercion(manager, monkeypatch):
    manager.add_swift_code("SPLR")
    manager.add_condition("CP_RATIO", "==", "x")
    monkeypatch.setattr(rm.Prompt, "ask", _scripted_prompt(["CP_RATIO", "<", "1"]))
    manager.edit_condition(0)
    cond = manager.rules["SPLR"]["filters"][0]["conditions"][0]
    assert cond["value"] == 1 and isinstance(cond["value"], int)


def test_edit_condition_comparison(manager, monkeypatch):
    manager.add_swift_code("SPLR")
    manager.add_column_comparison("A", ">", "B")
    monkeypatch.setattr(rm.Prompt, "ask", _scripted_prompt(["A", "<", "B"]))
    assert manager.edit_condition(0) is True
    cond = manager.rules["SPLR"]["filters"][0]["conditions"][0]
    assert cond["operator"] == "<"


def test_edit_nested_block_rejected(manager):
    manager.add_swift_code("TEND")
    manager.add_nested_block("and")
    assert manager.edit_condition(0) is False  # can't edit a block this way
