"""Pure operator/value semantics shared by the rule validator (rule_manager)
and the data analyzer (analysis/).

Keeping this in one place guarantees a database record is scored *exactly* the
way the validator reasons about rules — the same type-tolerant comparison, the
same operator set.

Why the tolerance matters: WM values reach the store as strings (a converter
asserts their type on insert) while BB values arrive already typed, so the same
logical value can appear as "07" or 7 depending on provider. `values_equal`
treats those as equal so a comparison never fails purely on representation.
"""
from typing import Any

# The only operators the validator and matcher understand.
CANONICAL_OPERATORS = {"==", "!=", ">", "<", ">=", "<=", "in", "not in"}

# Sentinel for "this record has no value for the referenced attribute".
# Semantics mirror SQL NULL: any comparison against a missing value is
# non-matching, which is also how the engine's own WHERE clauses behave.
MISSING = object()


def values_equal(a: Any, b: Any) -> bool:
    """Type-tolerant equality: exact, then numeric, then string.

    Recovers cross-representation matches such as 7 == "07" (float path) and
    12 == "12" (string path) without treating "AM" == "AG" as equal.
    """
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except (ValueError, TypeError):
        pass
    return str(a) == str(b)


def value_in_list(value: Any, values: Any) -> bool:
    """True if `value` type-tolerantly equals any element of the list."""
    return isinstance(values, list) and any(values_equal(value, item) for item in values)


def _as_floats(a: Any, b: Any):
    """Return (float(a), float(b)) or None if either is non-numeric."""
    try:
        return float(a), float(b)
    except (ValueError, TypeError):
        return None


def evaluate_leaf(actual: Any, operator: str, expected: Any) -> bool:
    """Does a concrete record value satisfy ``actual <operator> expected``?

    A MISSING attribute never satisfies a condition (SQL-NULL semantics).
    An unknown operator returns False (the validator flags it separately).
    """
    if actual is MISSING:
        return False

    if operator == "==":
        return values_equal(actual, expected)
    if operator == "!=":
        return not values_equal(actual, expected)
    if operator == "in":
        return value_in_list(actual, expected)
    if operator == "not in":
        return isinstance(expected, list) and not value_in_list(actual, expected)

    if operator in (">", "<", ">=", "<="):
        pair = _as_floats(actual, expected)
        if pair is None:
            return False
        a, e = pair
        if operator == ">":
            return a > e
        if operator == "<":
            return a < e
        if operator == ">=":
            return a >= e
        if operator == "<=":
            return a <= e

    return False


def evaluate_comparison(left: Any, operator: str, right: Any) -> bool:
    """Evaluate a column-vs-column comparison against two concrete values."""
    if left is MISSING or right is MISSING:
        return False

    if operator == "==":
        return values_equal(left, right)
    if operator == "!=":
        return not values_equal(left, right)

    if operator in (">", "<", ">=", "<="):
        pair = _as_floats(left, right)
        if pair is None:
            return False
        l, r = pair
        if operator == ">":
            return l > r
        if operator == "<":
            return l < r
        if operator == ">=":
            return l >= r
        if operator == "<=":
            return l <= r

    return False
