"""_extract_or_paths and _flatten_and_block."""
from helpers import block, leaf


def _cols(path):
    return [c.get("column") or c.get("logic") for c in path]


def test_extract_no_conditions_key(manager):
    assert manager._extract_or_paths({"logic": "or"}) == [[]]


def test_extract_or_root_simple_conditions(manager):
    # OR of two leaves -> two single-condition paths.
    filters = block("or", leaf("a", "==", "1"), leaf("b", "==", "2"))
    paths = manager._extract_or_paths(filters)
    assert len(paths) == 2
    assert _cols(paths[0]) == ["a"]
    assert _cols(paths[1]) == ["b"]


def test_extract_or_with_nested_and(manager):
    # OR containing one AND block -> that AND block is a single path.
    filters = block("or", block("and", leaf("a", "==", "1"), leaf("b", "==", "2")))
    paths = manager._extract_or_paths(filters)
    assert len(paths) == 1
    assert _cols(paths[0]) == ["a", "b"]


def test_extract_or_with_nested_or_flattens(manager):
    # Nested OR inside OR -> its branches become sibling paths.
    inner = block("or", leaf("a", "==", "1"), leaf("b", "==", "2"))
    filters = block("or", inner, leaf("c", "==", "3"))
    paths = manager._extract_or_paths(filters)
    cols = sorted(_cols(p) for p in paths)
    assert cols == [["a"], ["b"], ["c"]]


def test_extract_and_root_single_path(manager):
    filters = block("and", leaf("a", "==", "1"), leaf("b", "==", "2"))
    paths = manager._extract_or_paths(filters)
    assert len(paths) == 1
    assert _cols(paths[0]) == ["a", "b"]


def test_flatten_and_recurses_nested_and(manager):
    b = block("and", leaf("a", "==", "1"), block("and", leaf("b", "==", "2"), leaf("c", "==", "3")))
    flat = manager._flatten_and_block(b)
    assert [c["column"] for c in flat] == ["a", "b", "c"]


def test_flatten_and_keeps_nested_or_as_is(manager):
    inner_or = block("or", leaf("b", "==", "2"))
    b = block("and", leaf("a", "==", "1"), inner_or)
    flat = manager._flatten_and_block(b)
    assert flat[0]["column"] == "a"
    assert flat[1] is inner_or  # OR block kept intact (conservative)


def test_extract_all_conditions_recurses_any_logic(manager):
    # Unlike _flatten_and_block, this drills through nested OR/AND to leaves.
    b = block(
        "or",
        leaf("a", "==", "1"),
        block("and", leaf("b", "==", "2"), block("or", leaf("c", "==", "3"))),
    )
    flat = manager._extract_all_conditions(b)
    assert [c["column"] for c in flat] == ["a", "b", "c"]


def test_extract_all_conditions_empty_block(manager):
    assert manager._extract_all_conditions({"logic": "or"}) == []
