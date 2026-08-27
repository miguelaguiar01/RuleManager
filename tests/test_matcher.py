"""analysis.matcher: scoring records against filter trees."""
from analysis import matcher
from helpers import and_rule, block, comp, leaf, or_rule


def test_and_block_all_must_hold():
    filters = block("and", leaf("mnemonic", "==", "DVD_CASH"), leaf("CP_STOCK_OPT", "not in", ["D", "S"]))
    assert matcher.record_matches({"mnemonic": "DVD_CASH", "CP_STOCK_OPT": "X"}, filters) is True
    assert matcher.record_matches({"mnemonic": "DVD_CASH", "CP_STOCK_OPT": "S"}, filters) is False


def test_or_block_any_holds():
    filters = block("or", leaf("a", "==", "1"), leaf("b", "==", "2"))
    assert matcher.record_matches({"a": "9", "b": "2"}, filters) is True
    assert matcher.record_matches({"a": "9", "b": "9"}, filters) is False


def test_nested_blocks():
    filters = block("and", leaf("mnemonic", "==", "TEND"), block("or", leaf("x", "==", "1"), leaf("y", "==", "2")))
    assert matcher.record_matches({"mnemonic": "TEND", "x": "9", "y": "2"}, filters) is True
    assert matcher.record_matches({"mnemonic": "TEND", "x": "9", "y": "9"}, filters) is False


def test_empty_blocks():
    assert matcher.record_matches({}, block("and")) is True    # vacuous AND
    assert matcher.record_matches({}, block("or")) is False    # vacuous OR


def test_comparison_node():
    filters = block("and", comp("CP_RATIO_A", ">", "CP_RATIO_B"))
    assert matcher.record_matches({"CP_RATIO_A": 3, "CP_RATIO_B": 1}, filters) is True
    assert matcher.record_matches({"CP_RATIO_A": 1, "CP_RATIO_B": 3}, filters) is False


def test_missing_attribute_is_non_matching():
    filters = block("and", leaf("CP_STOCK_OPT", "not in", ["D", "S"]))
    # record has no CP_STOCK_OPT -> SQL-NULL semantics -> does not match
    assert matcher.record_matches({"mnemonic": "X"}, filters) is False


def test_type_tolerance_in_records():
    filters = block("and", leaf("UD006A", "==", "07"))
    assert matcher.record_matches({"UD006A": 7}, filters) is True   # int record vs "07" rule


def test_matching_codes():
    rules = {
        "DVCA": and_rule(leaf("mnemonic", "==", "DVD_CASH")),
        "TEND": and_rule(leaf("mnemonic", "==", "DVD_CASH")),
        "SPLR": and_rule(leaf("mnemonic", "==", "STOCK_SPLT")),
    }
    assert matcher.matching_codes({"mnemonic": "DVD_CASH"}, rules) == ["DVCA", "TEND"]
    assert matcher.matching_codes({"mnemonic": "NONE"}, rules) == []


def test_referenced_and_ruleset_columns():
    filters = block("and", leaf("mnemonic", "==", "X"), comp("A", ">", "B"),
                    block("or", leaf("C", "==", "1")))
    assert matcher.referenced_columns(filters) == {"mnemonic", "A", "B", "C"}

    rules = {"R1": and_rule(leaf("a", "==", "1")), "R2": or_rule(leaf("b", "==", "2"))}
    assert matcher.ruleset_columns(rules) == {"a", "b"}
