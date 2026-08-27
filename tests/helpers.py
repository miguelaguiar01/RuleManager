"""Small builders for constructing rule structures in tests."""


def leaf(column, operator, value):
    return {"column": column, "operator": operator, "value": value}


def comp(column1, operator, column2):
    return {
        "comparison": "column_vs_column",
        "column1": column1,
        "operator": operator,
        "column2": column2,
    }


def block(logic, *conditions):
    return {"logic": logic, "conditions": list(conditions)}


def rule(filters_block, deps=None):
    return {"DEPENDENCIES": list(deps or []), "filters": [filters_block]}


def and_rule(*conditions, deps=None):
    """A rule whose single path is one AND block."""
    return rule(block("and", *conditions), deps=deps)


def or_rule(*conditions, deps=None):
    """A rule whose top-level filter is an OR block."""
    return rule(block("or", *conditions), deps=deps)
