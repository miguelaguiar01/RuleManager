"""BA report outputs: full-list iterators, CSV bundle, HTML rendering."""
import csv

from analysis import analyses, report, report_html
from analysis.analyses import EvaluatedRecord


def _evaluated():
    return [
        EvaluatedRecord(1, "DVSC", ["DVSC", "TEND"]),   # ambiguous, conformant
        EvaluatedRecord(2, "TEND", []),                 # coverage gap + nonconformant
        EvaluatedRecord(3, "DVCA", ["DVCA"]),           # clean
        EvaluatedRecord(4, "GHOST", ["TEND"]),          # assigned code not matched
    ]


RULES = {"DVCA": {}, "DVSC": {}, "TEND": {}}   # GHOST intentionally absent


def test_iter_gaps():
    gaps = list(analyses.iter_gaps(_evaluated()))
    assert [ev.ca_id for ev in gaps] == [2]


def test_iter_ambiguous():
    amb = list(analyses.iter_ambiguous(_evaluated()))
    assert [ev.ca_id for ev in amb] == [1]


def test_iter_conformance_excludes_unknown_code():
    # ca 2 (assigned TEND, matches nothing) is a conformance issue;
    # ca 4 (assigned GHOST, not in rules) is NOT — it's "assigned unknown".
    conf = list(analyses.iter_conformance(_evaluated(), RULES))
    assert [ev.ca_id for ev in conf] == [2]


def test_write_csv_bundle_full_rows(tmp_path):
    integ = [{"ca_id": 9, "column": "CP_X", "eav": "S", "mv": "D"}]
    paths = report.write_csv_bundle(tmp_path, "bb_eav", _evaluated(), RULES, integ)
    names = {p.name for p in paths}
    assert names == {
        "bb_eav_coverage_gaps.csv", "bb_eav_ambiguous.csv",
        "bb_eav_conformance.csv", "bb_eav_integrity_mismatches.csv",
    }

    gaps = list(csv.reader(open(tmp_path / "bb_eav_coverage_gaps.csv")))
    assert gaps[0] == ["ca_id", "assigned_code"]
    assert gaps[1] == ["2", "TEND"]

    amb = list(csv.reader(open(tmp_path / "bb_eav_ambiguous.csv")))
    assert amb[1] == ["1", "DVSC + TEND", "DVSC"]

    integ_rows = list(csv.reader(open(tmp_path / "bb_eav_integrity_mismatches.csv")))
    assert integ_rows[1] == ["9", "CP_X", "S", "D"]


def test_write_csv_bundle_without_integrity(tmp_path):
    paths = report.write_csv_bundle(tmp_path, "wm_mv", _evaluated(), RULES, None)
    assert not any("integrity" in p.name for p in paths)


def test_render_html_contains_sections_and_values():
    summary = analyses.summarize("eav", _evaluated(), RULES)
    meta = {"provider": "bb", "rules_path": "/x/rules_bb.json", "generated_at": "2026-08-27 13:00",
            "sources": ["eav"], "rule_count": 3, "overlap_count": 2}
    html = report_html.render_html(meta, summary and [summary], {"eav": [{"pair": ["DVSC", "TEND"], "realized": 1}]}, None)

    assert "<!doctype html>" in html.lower()
    assert "Corporate-action rule audit — bb" in html
    assert "Realized ambiguity" in html and "Coverage gaps" in html and "Conformance" in html
    assert "Resolution audit" in html
    assert "rules_bb.json" in html
    # ambiguity row present
    assert "DVSC + TEND" in html
