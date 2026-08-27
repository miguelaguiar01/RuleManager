"""validate_rules and _validate_filter_structure."""
from helpers import and_rule, block, comp, leaf, or_rule


# ---------------------------------------------------------------------------
# _validate_filter_structure
# ---------------------------------------------------------------------------

def test_valid_structure_no_errors(manager):
    filters = block("and", leaf("CP_STOCK_OPT", "not in", ["D", "S"]), leaf("m", "==", "X"))
    assert manager._validate_filter_structure(filters, "DVCA") == []


def test_invalid_logic_flagged(manager):
    filters = {"logic": "xor", "conditions": []}
    errors = manager._validate_filter_structure(filters, "DVCA")
    assert any("Invalid logic" in e for e in errors)


def test_missing_leaf_keys_flagged(manager):
    filters = {"logic": "and", "conditions": [{"column": "a"}]}  # no operator/value
    errors = manager._validate_filter_structure(filters, "DVCA")
    assert any("Missing 'operator'" in e for e in errors)
    assert any("Missing 'value'" in e for e in errors)


def test_missing_comparison_keys_flagged(manager):
    filters = {"logic": "and", "conditions": [{"comparison": "column_vs_column", "column1": "a"}]}
    errors = manager._validate_filter_structure(filters, "SPLR")
    assert any("Missing 'operator'" in e for e in errors)
    assert any("Missing 'column2'" in e for e in errors)


def test_invalid_operator_flagged_raw(manager):
    filters = block("and", leaf("a", "not_in", ["D"]))  # not_in is not canonical
    errors = manager._validate_filter_structure(filters, "DVCA")
    assert any("Invalid operator" in e and "not_in" in e for e in errors)


def test_canonical_operators_accepted(manager):
    filters = block(
        "and",
        leaf("a", "not in", ["D"]),
        leaf("b", "==", "1"),
        comp("c", ">=", "d"),
    )
    errors = manager._validate_filter_structure(filters, "DVCA")
    assert not any("Invalid operator" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_rules (whole file)
# ---------------------------------------------------------------------------

def test_validate_clean_ruleset(make_manager):
    # Two rules that contradict on a shared column -> no overlap, no errors.
    m = make_manager({
        "DVCA": and_rule(leaf("CP_STOCK_OPT", "not in", ["D", "S"])),
        "DVSC": and_rule(leaf("CP_STOCK_OPT", "==", "S")),
    })
    result = m.validate_rules()
    assert result.errors == []
    assert result.overlaps == []
    assert result.is_valid is True


def test_validate_missing_filters_error(make_manager):
    m = make_manager({"DVCA": {"DEPENDENCIES": []}})
    result = m.validate_rules()
    assert any("Missing 'filters'" in e for e in result.errors)
    assert result.is_valid is False


def test_validate_empty_filters_error(make_manager):
    m = make_manager({"DVCA": {"DEPENDENCIES": [], "filters": []}})
    result = m.validate_rules()
    assert any("'filters' array is empty" in e for e in result.errors)


def test_validate_missing_dependencies_warning(make_manager):
    m = make_manager({"DVCA": {"filters": [block("or")]}})
    result = m.validate_rules()
    assert any("Missing 'DEPENDENCIES'" in w for w in result.warnings)


def test_validate_detects_overlap(make_manager):
    m = make_manager({
        "A": and_rule(leaf("mnemonic", "==", "DVD_CASH")),
        "B": and_rule(leaf("mnemonic", "==", "DVD_CASH")),
    })
    result = m.validate_rules()
    assert ("A", "B") in result.overlaps
    assert result.is_valid is False


def test_validate_skips_exdate(make_manager):
    m = make_manager({
        "EXDATE": {"not": "a real rule"},
        "DVCA": and_rule(leaf("a", "==", "1")),
    })
    result = m.validate_rules()
    # EXDATE must not appear in any error/overlap.
    assert not any("EXDATE" in e for e in result.errors)
    assert all("EXDATE" not in c for pair in result.overlaps for c in pair)
