"""add / delete / select Swift codes and current-selection bookkeeping."""


def test_add_swift_code_creates_skeleton(manager):
    assert manager.add_swift_code("DVCA") is True
    rule = manager.rules["DVCA"]
    assert rule["DEPENDENCIES"] == []
    assert rule["filters"] == [{"logic": "or", "conditions": []}]
    assert manager.current_swift_code == "DVCA"
    assert manager.current_path == []


def test_add_duplicate_swift_code_rejected(manager):
    manager.add_swift_code("DVCA")
    assert manager.add_swift_code("DVCA") is False


def test_delete_swift_code(manager):
    manager.add_swift_code("DVCA")
    assert manager.delete_swift_code("DVCA") is True
    assert "DVCA" not in manager.rules
    # current selection cleared because it pointed at the deleted code
    assert manager.current_swift_code is None
    assert manager.current_path == []


def test_delete_missing_swift_code(manager):
    assert manager.delete_swift_code("NOPE") is False


def test_delete_other_code_keeps_selection(manager):
    manager.add_swift_code("DVCA")
    manager.add_swift_code("DRIP")  # selection now DRIP
    assert manager.delete_swift_code("DVCA") is True
    assert manager.current_swift_code == "DRIP"


def test_select_swift_code(manager):
    manager.add_swift_code("DVCA")
    manager.add_swift_code("DRIP")
    assert manager.select_swift_code("DVCA") is True
    assert manager.current_swift_code == "DVCA"
    assert manager.select_swift_code("MISSING") is False


def test_get_current_rule(manager):
    assert manager.get_current_rule() is None
    manager.add_swift_code("DVCA")
    assert manager.get_current_rule() is manager.rules["DVCA"]
