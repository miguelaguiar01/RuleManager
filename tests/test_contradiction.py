"""_are_contradictory, _values_equal/_value_in_list, _paths_can_overlap,
_check_potential_overlap — including the reported `not in` false positives."""
import pytest

from helpers import and_rule, comp, leaf


# ---------------------------------------------------------------------------
# Type-tolerant value helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("S", "S"),
    (7, "07"),        # int vs zero-padded string -> numeric match
    ("7", 7),
    (1.0, 1),
    (12, "12"),
])
def test_values_equal_true(manager, a, b):
    assert manager._values_equal(a, b) is True


@pytest.mark.parametrize("a,b", [
    ("S", "D"),
    (7, "AM"),
    ("07", "8"),      # different numbers
    ("AM", "AG"),     # non-numeric, unequal
])
def test_values_equal_false(manager, a, b):
    assert manager._values_equal(a, b) is False


def test_value_in_list(manager):
    assert manager._value_in_list(7, ["07", "AM"]) is True
    assert manager._value_in_list("S", ["D", "S"]) is True
    assert manager._value_in_list("X", ["D", "S"]) is False
    assert manager._value_in_list("X", "not-a-list") is False


# ---------------------------------------------------------------------------
# _are_contradictory: leaf operator combinations
# ---------------------------------------------------------------------------

def C(op, val):
    return leaf("COL", op, val)


def contra(manager, op1, v1, op2, v2):
    return manager._are_contradictory(C(op1, v1), C(op2, v2))


def test_equal_equal(manager):
    assert contra(manager, "==", "A", "==", "B") is True
    assert contra(manager, "==", "A", "==", "A") is False


def test_equal_not_equal(manager):
    assert contra(manager, "==", "A", "!=", "A") is True
    assert contra(manager, "==", "A", "!=", "B") is False
    assert contra(manager, "!=", "A", "==", "A") is True


def test_equal_in(manager):
    assert contra(manager, "==", "X", "in", ["A", "B"]) is True   # X not allowed
    assert contra(manager, "==", "A", "in", ["A", "B"]) is False  # A allowed
    assert contra(manager, "in", ["A", "B"], "==", "A") is False


def test_equal_in_type_tolerant(manager):
    # coerced int 7 vs string list containing "07" -> allowed, not contradictory
    assert contra(manager, "==", 7, "in", ["07", "05"]) is False
    assert contra(manager, "==", 9, "in", ["07", "05"]) is True


def test_in_in(manager):
    assert contra(manager, "in", ["A", "B"], "in", ["C", "D"]) is True   # disjoint
    assert contra(manager, "in", ["A", "B"], "in", ["B", "C"]) is False  # share B


def test_equal_not_in(manager):
    assert contra(manager, "==", "S", "not in", ["D", "S"]) is True   # excluded
    assert contra(manager, "==", "X", "not in", ["D", "S"]) is False  # allowed
    assert contra(manager, "not in", ["D", "S"], "==", "D") is True


def test_equal_not_in_type_tolerant(manager):
    assert contra(manager, "==", 7, "not in", ["07", "AM"]) is True   # 7 == "07"
    assert contra(manager, "==", 9, "not in", ["07", "AM"]) is False


def test_in_not_in(manager):
    # in-set fully excluded -> contradictory
    assert contra(manager, "in", ["D", "S"], "not in", ["D", "S", "X"]) is True
    # in-set has an allowed value -> not contradictory
    assert contra(manager, "in", ["D", "S", "Z"], "not in", ["D", "S"]) is False
    assert contra(manager, "not in", ["D", "S"], "in", ["D", "S"]) is True


def test_not_in_not_in_never_contradictory(manager):
    assert contra(manager, "not in", ["A"], "not in", ["B"]) is False


@pytest.mark.parametrize("op1,v1,op2,v2,expected", [
    (">", 5, "<", 3, True),
    (">", 3, "<", 5, False),
    (">=", 5, "<", 5, True),
    ("<", 3, ">", 5, True),
    ("<=", 3, ">", 5, True),
    ("==", 5, ">", 5, True),
    ("==", 6, ">", 5, False),
    ("==", 5, "<", 5, True),
    (">", 5, "==", 5, True),
])
def test_numeric_contradictions(manager, op1, v1, op2, v2, expected):
    assert contra(manager, op1, v1, op2, v2) is expected


def test_non_numeric_range_is_safe(manager):
    # float() fails -> no contradiction claimed, no crash
    assert contra(manager, ">", "abc", "<", "def") is False


# ---------------------------------------------------------------------------
# column_vs_column comparisons
# ---------------------------------------------------------------------------

def test_comparison_vs_comparison(manager):
    assert manager._are_contradictory(comp("A", ">", "B"), comp("A", "<", "B")) is True
    assert manager._are_contradictory(comp("A", "==", "B"), comp("A", "!=", "B")) is True
    assert manager._are_contradictory(comp("A", ">", "B"), comp("A", ">", "B")) is False
    # different column pair -> not comparable
    assert manager._are_contradictory(comp("A", ">", "B"), comp("A", "<", "C")) is False


def test_comparison_vs_leaf_is_skipped(manager):
    assert manager._are_contradictory(comp("A", ">", "B"), C("==", "1")) is False


# ---------------------------------------------------------------------------
# _paths_can_overlap
# ---------------------------------------------------------------------------

def test_paths_overlap_no_common_column(manager):
    p1 = [leaf("a", "==", "1")]
    p2 = [leaf("b", "==", "2")]
    assert manager._paths_can_overlap(p1, p2) is True  # conservative


def test_paths_no_overlap_on_contradiction(manager):
    p1 = [leaf("CP_STOCK_OPT", "not in", ["D", "S"])]
    p2 = [leaf("CP_STOCK_OPT", "==", "S")]
    assert manager._paths_can_overlap(p1, p2) is False


# ---------------------------------------------------------------------------
# _check_potential_overlap — the reported false positives + genuine overlaps
# ---------------------------------------------------------------------------

def overlaps(make_manager, rule_a, rule_b):
    m = make_manager({"A": rule_a, "B": rule_b})
    return m._check_potential_overlap("A", "B")


def test_dvca_vs_dvsc_not_overlapping(make_manager):
    a = and_rule(leaf("CP_STOCK_OPT", "not in", ["D", "S"]))
    b = and_rule(leaf("CP_STOCK_OPT", "==", "S"))
    assert overlaps(make_manager, a, b) is False


def test_drip_vs_d_not_overlapping(make_manager):
    a = and_rule(leaf("CP_STOCK_OPT", "not in", ["D", "S"]))
    b = and_rule(leaf("CP_STOCK_OPT", "==", "D"))
    assert overlaps(make_manager, a, b) is False


def test_ud006a_int_coercion_not_overlapping(make_manager):
    a = and_rule(leaf("UD006A", "==", 7))  # coerced int, as add_condition stores it
    b = and_rule(leaf("UD006A", "not in", ["07", "AM", "AG", "05"]))
    assert overlaps(make_manager, a, b) is False


def test_same_equality_overlaps(make_manager):
    a = and_rule(leaf("mnemonic", "==", "DVD_CASH"))
    b = and_rule(leaf("mnemonic", "==", "DVD_CASH"))
    assert overlaps(make_manager, a, b) is True


def test_not_in_allows_value_overlaps(make_manager):
    a = and_rule(leaf("CP_STOCK_OPT", "not in", ["D", "S"]))
    b = and_rule(leaf("CP_STOCK_OPT", "==", "X"))
    assert overlaps(make_manager, a, b) is True


def test_missing_filters_no_overlap(make_manager):
    m = make_manager({"A": {"DEPENDENCIES": []}, "B": and_rule(leaf("a", "==", "1"))})
    assert m._check_potential_overlap("A", "B") is False
