"""Explaining WHY a record fails its assigned rule + aggregation by cause."""
import csv

from analysis import analyses, matcher, report, report_html
from analysis.records import CARecord
from helpers import and_rule, block, comp, leaf, or_rule


def test_explain_leaf_failure_records_actual():
    filters = block("and", leaf("mnemonic", "==", "DVD_CASH"), leaf("CP_STOCK_OPT", "not in", ["D", "S"]))
    reasons = matcher.explain_nonmatch({"mnemonic": "DVD_CASH", "CP_STOCK_OPT": "D"}, filters)
    assert len(reasons) == 1
    r = reasons[0]
    assert r["column"] == "CP_STOCK_OPT" and r["operator"] == "not in"
    assert r["actual"] == "D" and r["missing"] is False
    assert matcher.format_reason(r) == 'CP_STOCK_OPT not in [D, S]  (actual: D)'


def test_explain_and_reports_all_failures():
    filters = block("and", leaf("mnemonic", "==", "DVD_CASH"), leaf("CP_STOCK_OPT", "==", "S"))
    reasons = matcher.explain_nonmatch({"mnemonic": "X", "CP_STOCK_OPT": "Y"}, filters)
    cols = sorted(r["column"] for r in reasons)
    assert cols == ["CP_STOCK_OPT", "mnemonic"]


def test_explain_matching_record_has_no_reasons():
    filters = block("and", leaf("mnemonic", "==", "DVD_CASH"))
    assert matcher.explain_nonmatch({"mnemonic": "DVD_CASH"}, filters) == []


def test_explain_missing_attribute():
    filters = block("and", leaf("UD006A", "==", "07"))
    reasons = matcher.explain_nonmatch({"mnemonic": "X"}, filters)
    assert reasons[0]["missing"] is True
    assert matcher.reason_actual(reasons[0]) == "<missing>"


def test_explain_or_returns_nearest_miss():
    # two paths; record fails path A on 2 conditions, path B on 1 -> report B's 1.
    path_a = block("and", leaf("a", "==", "1"), leaf("b", "==", "2"))
    path_b = block("and", leaf("c", "==", "3"))
    filters = block("or", path_a, path_b)
    reasons = matcher.explain_nonmatch({"a": "9", "b": "9", "c": "9"}, filters)
    assert [r["column"] for r in reasons] == ["c"]   # nearest miss = the 1-condition branch


def test_explain_comparison():
    filters = block("and", comp("CP_RATIO_A", ">", "CP_RATIO_B"))
    reasons = matcher.explain_nonmatch({"CP_RATIO_A": 1, "CP_RATIO_B": 5}, filters)
    r = reasons[0]
    assert r["kind"] == "comparison" and r["column2"] == "CP_RATIO_B"
    assert matcher.reason_actual(r) == "1 vs 5"


# --- aggregation ------------------------------------------------------------

RULES = {
    "DVCA": and_rule(leaf("mnemonic", "==", "DVD_CASH"), leaf("CP_STOCK_OPT", "not in", ["D", "S"])),
    "TEND": and_rule(leaf("mnemonic", "==", "DVD_CASH")),
}


def _rec(ca_id, assigned, **fields):
    return CARecord(ca_id=ca_id, assigned_code=assigned, fields=fields)


def test_conformance_by_cause_groups_and_ranks():
    records = [
        _rec(1, "DVCA", mnemonic="DVD_CASH", CP_STOCK_OPT="D"),   # violates not in [D,S] (D)
        _rec(2, "DVCA", mnemonic="DVD_CASH", CP_STOCK_OPT="S"),   # same condition (S)
        _rec(3, "DVCA", mnemonic="DVD_CASH", CP_STOCK_OPT="D"),   # same condition (D)
        _rec(4, "TEND", mnemonic="STOCK_SPLT"),                   # violates mnemonic == DVD_CASH
        _rec(5, "DVCA", mnemonic="DVD_CASH", CP_STOCK_OPT="X"),   # conformant -> not counted
    ]
    report_dict = analyses.conformance_by_cause(records, RULES)
    assert report_dict["total"] == 4                             # record 5 excluded
    top = report_dict["causes"][0]
    assert top["assigned"] == "DVCA"
    assert top["conditions"] == ["CP_STOCK_OPT not in [D, S]"]
    assert top["count"] == 3
    # sample actuals rolled up: D×2, S×1
    actuals = {s["value"]: s["count"] for s in top["sample_actuals"]}
    assert actuals == {"D": 2, "S": 1}
    # counts sum to total (each record once)
    assert sum(c["count"] for c in report_dict["causes"]) == 4


def test_iter_conformance_reasons_rows():
    records = [_rec(1, "DVCA", mnemonic="DVD_CASH", CP_STOCK_OPT="D")]
    rows = list(analyses.iter_conformance_reasons(records, RULES))
    assert rows == [{
        "ca_id": 1, "assigned_code": "DVCA", "column": "CP_STOCK_OPT",
        "operator": "not in", "expected": "[D, S]", "actual": "D",
    }]


def test_write_conformance_reasons_csv(tmp_path):
    records = [_rec(1, "DVCA", mnemonic="DVD_CASH", CP_STOCK_OPT="D")]
    path = report.write_conformance_reasons_csv(tmp_path, "bb_eav", records, RULES)
    rows = list(csv.reader(open(path)))
    assert rows[0] == ["ca_id", "assigned_code", "column", "operator", "expected", "actual"]
    assert rows[1] == ["1", "DVCA", "CP_STOCK_OPT", "not in", "[D, S]", "D"]


def test_html_includes_causes_section():
    records = [_rec(1, "DVCA", mnemonic="DVD_CASH", CP_STOCK_OPT="D")]
    causes = {"eav": analyses.conformance_by_cause(records, RULES)}
    summary = analyses.summarize("eav", analyses.evaluate(RULES, records), RULES)
    meta = {"provider": "bb", "rules_path": "x", "generated_at": "t", "sources": ["eav"],
            "rule_count": 2, "overlap_count": 0}
    html = report_html.render_html(meta, [summary], {"eav": []}, None, conformance_causes=causes)
    assert "Conformance failures by cause" in html
    assert "CP_STOCK_OPT not in [D, S]" in html
