"""End-to-end through the pure pipeline (records -> analyses -> report/export),
with synthetic rows standing in for the database."""
import io
import json

from rich.console import Console

from analysis import analyses, records as rec, report
from analysis.matcher import ruleset_columns
from helpers import and_rule, leaf


RULES = {
    "DVCA": and_rule(leaf("mnemonic", "==", "DVD_CASH"), leaf("CP_STOCK_OPT", "not in", ["D", "S"])),
    "DVSC": and_rule(leaf("mnemonic", "==", "DVD_CASH"), leaf("CP_STOCK_OPT", "==", "S")),
    "TEND": and_rule(leaf("mnemonic", "==", "DVD_CASH")),
}

BASE = [
    {"ca_id": 1, "mnemonic": "DVD_CASH", "swift_code": "DVSC"},
    {"ca_id": 2, "mnemonic": "DVD_CASH", "swift_code": "DVCA"},
]
ATTRS = [
    {"ca_id": 1, "attribute": "CP_STOCK_OPT", "value": "S"},
    {"ca_id": 2, "attribute": "CP_STOCK_OPT", "value": "X"},
]
# MV: lowercase columns; ca 1 disagrees with EAV on CP_STOCK_OPT (integrity bug)
MV_ROWS = [
    {"ca_id": 1, "mnemonic": "DVD_CASH", "swift_code": "DVSC", "cp_stock_opt": "D"},
    {"ca_id": 2, "mnemonic": "DVD_CASH", "swift_code": "DVCA", "cp_stock_opt": "X"},
]


def test_full_pipeline_and_export(tmp_path):
    columns = ruleset_columns(RULES)

    eav = rec.build_records_from_eav(BASE, ATTRS)
    mv = rec.build_records_from_mv(MV_ROWS, columns)

    eav_eval = analyses.evaluate(RULES, eav.values())
    eav_summary = analyses.summarize("eav", eav_eval, RULES)
    realized = analyses.realized_for_overlaps(eav_eval, [("DVSC", "TEND"), ("DVCA", "TEND")])
    integ = analyses.integrity(eav, mv, columns)

    # ca 1 matches DVSC+TEND, ca 2 matches DVCA+TEND -> both ambiguous
    assert sum(g["count"] for g in eav_summary.ambiguous) == 2
    assert {tuple(r["pair"]): r["realized"] for r in realized}[("DVSC", "TEND")] == 1
    # EAV says CP_STOCK_OPT=S for ca 1, MV says D -> one integrity mismatch
    assert integ["mismatches"]["count"] == 1

    payload = report.build_payload([eav_summary], {"eav": realized}, integ)
    out = report.export_json(tmp_path / "exports" / "audit.json", payload)
    assert out.exists()
    reloaded = json.loads(out.read_text())
    assert reloaded["summaries"][0]["source"] == "eav"
    assert reloaded["integrity"]["mismatches"]["count"] == 1


def test_renderers_do_not_crash():
    console = Console(file=io.StringIO(), width=100)
    evaluated = analyses.evaluate(RULES, rec.build_records_from_eav(BASE, ATTRS).values())
    summary = analyses.summarize("eav", evaluated, RULES)
    realized = analyses.realized_for_overlaps(evaluated, [("DVSC", "TEND")])
    integ = analyses.integrity(
        rec.build_records_from_eav(BASE, ATTRS),
        rec.build_records_from_mv(MV_ROWS, ruleset_columns(RULES)),
        ruleset_columns(RULES),
    )
    report.render_summary(console, summary)
    report.render_realized(console, realized)
    report.render_integrity(console, integ)
    output = console.file.getvalue()
    assert "Audit" in output and "integrity" in output.lower()
