"""rule_semantics: shared operator/value logic, and parity with the validator."""
import pytest

import rule_semantics as sem
import rule_manager as rm


# --- values_equal / value_in_list -----------------------------------------

@pytest.mark.parametrize("a,b", [("S", "S"), (7, "07"), ("7", 7), (1.0, 1), (12, "12")])
def test_values_equal_true(a, b):
    assert sem.values_equal(a, b) is True


@pytest.mark.parametrize("a,b", [("S", "D"), (7, "AM"), ("AM", "AG")])
def test_values_equal_false(a, b):
    assert sem.values_equal(a, b) is False


def test_value_in_list():
    assert sem.value_in_list(7, ["07", "AM"]) is True
    assert sem.value_in_list("X", ["D", "S"]) is False
    assert sem.value_in_list("X", "not-a-list") is False


# --- evaluate_leaf ----------------------------------------------------------

@pytest.mark.parametrize("actual,op,expected,result", [
    ("S", "==", "S", True),
    ("S", "==", "D", False),
    ("S", "!=", "D", True),
    ("S", "in", ["D", "S"], True),
    ("X", "in", ["D", "S"], False),
    ("S", "not in", ["D", "S"], False),
    ("X", "not in", ["D", "S"], True),
    (7, "not in", ["07", "AM"], False),   # 7 == "07" -> excluded
    (5, ">", 3, True),
    (5, "<", 3, False),
    (5, ">=", 5, True),
    (5, "<=", 4, False),
    ("abc", ">", "def", False),            # non-numeric range -> safe False
    ("S", "not in", "not-a-list", False),  # malformed expected -> False
    ("S", "??", "S", False),               # unknown operator -> False
])
def test_evaluate_leaf(actual, op, expected, result):
    assert sem.evaluate_leaf(actual, op, expected) is result


def test_missing_attribute_never_matches():
    for op, expected in [("==", "S"), ("!=", "S"), ("in", ["S"]), ("not in", ["S"]), (">", 1)]:
        assert sem.evaluate_leaf(sem.MISSING, op, expected) is False


# --- evaluate_comparison ----------------------------------------------------

def test_evaluate_comparison():
    assert sem.evaluate_comparison(5, ">", 3) is True
    assert sem.evaluate_comparison(3, ">", 5) is False
    assert sem.evaluate_comparison("A", "==", "A") is True
    assert sem.evaluate_comparison("A", "!=", "B") is True
    assert sem.evaluate_comparison(sem.MISSING, "==", "A") is False
    assert sem.evaluate_comparison("A", "==", sem.MISSING) is False


# --- parity with the validator ---------------------------------------------

def test_validator_delegates_to_shared_semantics():
    m = rm.RuleManager("/nonexistent.json")
    for a, b in [(7, "07"), ("S", "D"), (1.0, 1), ("AM", "AG")]:
        assert m._values_equal(a, b) == sem.values_equal(a, b)
    assert m._value_in_list(7, ["07"]) == sem.value_in_list(7, ["07"])
    assert m.CANONICAL_OPERATORS is sem.CANONICAL_OPERATORS
