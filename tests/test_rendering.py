"""Rendering / formatting helpers — smoke tests that they run and return the
right types, plus a documented pre-existing bug."""
import rule_manager as rm
from helpers import block, comp, leaf


def test_build_tree_view_no_selection(manager):
    panel = manager.build_tree_view()
    assert isinstance(panel, rm.Panel)


def test_build_tree_view_full(manager):
    manager.add_swift_code("TEND")
    manager.add_dependency("DVCA")
    # nested block + comparison + list-valued leaf -> exercises every branch
    manager.add_nested_block("and")
    manager.navigate_into(0)
    manager.add_condition("CP_DVD_TYP", "in", ["1027", "1017"])
    manager.add_column_comparison("A", ">", "B")
    manager.navigate_root()
    panel = manager.build_tree_view()
    assert isinstance(panel, rm.Panel)


def test_format_condition_leaf_and_comparison(manager):
    assert "CP_DVD_TYP" in manager._format_condition(leaf("CP_DVD_TYP", "in", ["1", "2"]))
    assert "A" in manager._format_condition(comp("A", ">", "B"))


def test_format_path_description(manager):
    assert manager._format_path_description([]) == "[dim]No conditions[/dim]"
    desc = manager._format_path_description([leaf("a", "==", "1"), comp("A", ">", "B")])
    assert "a" in desc and "A" in desc


def test_build_comparison_tree_happy_path(manager):
    filters = block("or", block("and", leaf("a", "==", "1"), leaf("b", "==", "2")), leaf("c", "==", "3"))
    text = manager._build_comparison_tree("TEND", filters)
    assert "ROOT" in text and "Path 1" in text


def test_build_comparison_tree_with_or_block(manager):
    # A top-level path that is an OR block routes through _extract_all_conditions.
    filters = block("or", block("or", leaf("a", "==", "1"), leaf("b", "==", "2")))
    text = manager._build_comparison_tree("TEND", filters)
    assert "a" in text and "b" in text
