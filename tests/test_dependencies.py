"""add / remove dependency."""


def test_add_dependency(manager):
    manager.add_swift_code("DVCA")
    assert manager.add_dependency("DVSC") is True
    assert manager.rules["DVCA"]["DEPENDENCIES"] == ["DVSC"]


def test_add_duplicate_dependency_rejected(manager):
    manager.add_swift_code("DVCA")
    manager.add_dependency("DVSC")
    assert manager.add_dependency("DVSC") is False
    assert manager.rules["DVCA"]["DEPENDENCIES"] == ["DVSC"]


def test_add_dependency_without_current_rule(manager):
    assert manager.add_dependency("DVSC") is False


def test_remove_dependency(manager):
    manager.add_swift_code("DVCA")
    manager.add_dependency("DVSC")
    assert manager.remove_dependency("DVSC") is True
    assert manager.rules["DVCA"]["DEPENDENCIES"] == []


def test_remove_missing_dependency(manager):
    manager.add_swift_code("DVCA")
    assert manager.remove_dependency("DVSC") is False
