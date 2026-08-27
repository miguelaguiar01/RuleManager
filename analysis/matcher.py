"""Score a single corporate-action record against a ruleset filter tree.

Uses the same operator/value semantics as the validator (rule_semantics), so a
record matches a Swift code here exactly when its data satisfies that code's
rule in the TUI.
"""
from typing import Any, Dict, Set

import rule_semantics as sem

MISSING = sem.MISSING


def record_matches(record: Dict[str, Any], filters: Dict) -> bool:
    """True if `record` satisfies the filter block (`filters` is rule["filters"][0])."""
    return _eval_block(record, filters)


def _eval_block(record: Dict[str, Any], block: Dict) -> bool:
    logic = block.get("logic", "or")
    conditions = block.get("conditions", [])
    results = (_eval_node(record, node) for node in conditions)
    # AND of zero conditions is vacuously True; OR of zero is False.
    return all(results) if logic == "and" else any(results)


def _eval_node(record: Dict[str, Any], node: Dict) -> bool:
    if "logic" in node:
        return _eval_block(record, node)
    if "comparison" in node:
        left = record.get(node.get("column1"), MISSING)
        right = record.get(node.get("column2"), MISSING)
        return sem.evaluate_comparison(left, node.get("operator"), right)
    actual = record.get(node.get("column"), MISSING)
    return sem.evaluate_leaf(actual, node.get("operator"), node.get("value"))


def matching_codes(record: Dict[str, Any], rules: Dict[str, Dict]) -> list:
    """All Swift codes whose rule this record satisfies (sorted, stable)."""
    matched = []
    for code, rule in rules.items():
        filters = rule.get("filters")
        if isinstance(filters, list) and filters and record_matches(record, filters[0]):
            matched.append(code)
    return sorted(matched)


def referenced_columns(filters: Dict) -> Set[str]:
    """Every column a filter tree reads — used to know which EAV attributes to
    pull and which MV columns to select."""
    cols: Set[str] = set()
    _collect_columns(filters, cols)
    return cols


def _collect_columns(node: Dict, cols: Set[str]) -> None:
    if "conditions" in node:
        for child in node["conditions"]:
            _collect_columns(child, cols)
        return
    if "comparison" in node:
        for key in ("column1", "column2"):
            if node.get(key):
                cols.add(node[key])
    elif node.get("column"):
        cols.add(node["column"])


def ruleset_columns(rules: Dict[str, Dict]) -> Set[str]:
    """Union of columns referenced across every rule in a ruleset."""
    cols: Set[str] = set()
    for rule in rules.values():
        filters = rule.get("filters")
        if isinstance(filters, list) and filters:
            cols |= referenced_columns(filters[0])
    return cols
