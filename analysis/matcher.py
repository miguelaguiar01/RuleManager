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


# --- explaining WHY a record fails a rule ----------------------------------

def explain_nonmatch(record: Dict[str, Any], filters: Dict) -> list:
    """Return the leaf/comparison conditions a record violates in `filters`.

    Empty list means the record actually matches. For OR blocks it returns the
    nearest-miss branch (fewest violated conditions); for AND blocks it returns
    every unmet condition. Each reason is a JSON-friendly dict.
    """
    ok, reasons = _explain_block(record, filters)
    return [] if ok else reasons


def _explain_block(record, block):
    logic = block.get("logic", "or")
    conditions = block.get("conditions", [])
    if logic == "and":
        reasons = []
        for node in conditions:
            ok, sub = _explain_node(record, node)
            if not ok:
                reasons.extend(sub)
        return (not reasons), reasons
    # OR (and the default): matches if any branch matches; else nearest miss.
    if not conditions:
        return False, []
    best = None
    for node in conditions:
        ok, sub = _explain_node(record, node)
        if ok:
            return True, []
        if best is None or len(sub) < len(best):
            best = sub
    return False, (best or [])


def _explain_node(record, node):
    if "logic" in node:
        return _explain_block(record, node)
    if "comparison" in node:
        left = record.get(node.get("column1"), MISSING)
        right = record.get(node.get("column2"), MISSING)
        if sem.evaluate_comparison(left, node.get("operator"), right):
            return True, []
        return False, [{
            "kind": "comparison",
            "column": node.get("column1"),
            "operator": node.get("operator"),
            "column2": node.get("column2"),
            "actual": None if left is MISSING else left,
            "missing": left is MISSING,
            "actual2": None if right is MISSING else right,
            "missing2": right is MISSING,
        }]
    actual = record.get(node.get("column"), MISSING)
    if sem.evaluate_leaf(actual, node.get("operator"), node.get("value")):
        return True, []
    return False, [{
        "kind": "leaf",
        "column": node.get("column"),
        "operator": node.get("operator"),
        "expected": node.get("value"),
        "actual": None if actual is MISSING else actual,
        "missing": actual is MISSING,
    }]


def _fmt_value(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


def condition_label(reason: Dict) -> str:
    """Human label for a violated condition, WITHOUT the actual value (used to
    group failures by cause)."""
    if reason["kind"] == "comparison":
        return f'{reason["column"]} {reason["operator"]} {reason["column2"]}'
    return f'{reason["column"]} {reason["operator"]} {_fmt_value(reason["expected"])}'


def condition_key(reason: Dict):
    """Stable grouping key for a violated condition (order-insensitive lists)."""
    if reason["kind"] == "comparison":
        return (reason["column"], reason["operator"], reason["column2"])
    expected = reason["expected"]
    exp_repr = repr(sorted(map(str, expected))) if isinstance(expected, list) else repr(expected)
    return (reason["column"], reason["operator"], exp_repr)


def reason_actual(reason: Dict) -> str:
    """The record's actual value(s) for a reason, as a display string."""
    left = "<missing>" if reason["missing"] else _fmt_value(reason["actual"])
    if reason["kind"] == "comparison":
        right = "<missing>" if reason.get("missing2") else _fmt_value(reason.get("actual2"))
        return f"{left} vs {right}"
    return left


def format_reason(reason: Dict) -> str:
    """Full one-line reason: condition + actual value(s)."""
    return f"{condition_label(reason)}  (actual: {reason_actual(reason)})"


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
