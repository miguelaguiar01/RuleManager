"""Shared fixtures. rule_manager is importable via pyproject `pythonpath = ["."]`."""
import pytest

import rule_manager as rm

RuleManager = rm.RuleManager


@pytest.fixture
def manager(tmp_path):
    """A RuleManager backed by a (non-existent) temp file -> starts with empty rules."""
    return RuleManager(str(tmp_path / "rules.json"))


@pytest.fixture
def make_manager(tmp_path):
    """Factory: build a manager and optionally inject a rules dict."""
    def _make(rules=None):
        m = RuleManager(str(tmp_path / "rules.json"))
        if rules is not None:
            m.rules = rules
        return m
    return _make
