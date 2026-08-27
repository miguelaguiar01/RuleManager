"""analysis.analyses: the five analyses over evaluated records."""
from analysis import analyses
from analysis.records import CARecord
from helpers import and_rule, leaf


RULES = {
    "DVCA": and_rule(leaf("mnemonic", "==", "DVD_CASH"), leaf("CP_STOCK_OPT", "not in", ["D", "S"])),
    "DVSC": and_rule(leaf("mnemonic", "==", "DVD_CASH"), leaf("CP_STOCK_OPT", "==", "S")),
    "TEND": and_rule(leaf("mnemonic", "==", "DVD_CASH")),  # broad: overlaps both above
}


def _rec(ca_id, assigned, **fields):
    return CARecord(ca_id=ca_id, assigned_code=assigned, fields=fields)


def test_summary_counts_and_buckets():
    records = [
        # matches DVSC(==S) and TEND -> ambiguous; assigned DVSC (conformant)
        _rec(1, "DVSC", mnemonic="DVD_CASH", CP_STOCK_OPT="S"),
        # matches DVCA(not in D,S) and TEND -> ambiguous; assigned DVCA
        _rec(2, "DVCA", mnemonic="DVD_CASH", CP_STOCK_OPT="X"),
        # matches nothing (mnemonic differs) -> coverage gap; assigned TEND (nonconformant)
        _rec(3, "TEND", mnemonic="OTHER", CP_STOCK_OPT="X"),
        # matches only TEND -> matched_one; conformant
        _rec(4, "TEND", mnemonic="DVD_CASH", CP_STOCK_OPT="D"),  # D excluded by DVCA, not ==S -> only TEND
    ]
    evaluated = analyses.evaluate(RULES, records)
    s = analyses.summarize("eav", evaluated, RULES)

    assert s.total == 4
    assert s.matched_one == 1                       # record 4
    assert s.unmatched["count"] == 1                # record 3
    assert sum(g["count"] for g in s.ambiguous) == 2  # records 1, 2
    # record 3 assigned TEND but matches nothing -> conformance issue
    assert s.conformance["count"] == 1
    assert s.conformance["examples"][0]["ca_id"] == 3


def test_ambiguity_groups_and_assigned_breakdown():
    records = [
        _rec(1, "DVSC", mnemonic="DVD_CASH", CP_STOCK_OPT="S"),
        _rec(2, "TEND", mnemonic="DVD_CASH", CP_STOCK_OPT="S"),  # same combo, assigned differently
    ]
    evaluated = analyses.evaluate(RULES, records)
    s = analyses.summarize("eav", evaluated, RULES)
    combo = s.ambiguous[0]
    assert combo["codes"] == ["DVSC", "TEND"]
    assert combo["count"] == 2
    assert combo["assigned"] == {"DVSC": 1, "TEND": 1}


def test_resolution_audit_flags_inconsistency():
    # DVSC+TEND both match; sometimes DVSC wins, sometimes TEND -> inconsistent
    records = [
        _rec(1, "DVSC", mnemonic="DVD_CASH", CP_STOCK_OPT="S"),
        _rec(2, "TEND", mnemonic="DVD_CASH", CP_STOCK_OPT="S"),
    ]
    evaluated = analyses.evaluate(RULES, records)
    s = analyses.summarize("eav", evaluated, RULES)
    pair = next(r for r in s.resolution if set(r["pair"]) == {"DVSC", "TEND"})
    assert pair["inconsistent"] is True


def test_assigned_unknown_code_bucket():
    records = [_rec(1, "GHOST", mnemonic="DVD_CASH", CP_STOCK_OPT="S")]
    evaluated = analyses.evaluate(RULES, records)
    s = analyses.summarize("eav", evaluated, RULES)
    assert s.assigned_unknown["count"] == 1


def test_realized_for_overlaps():
    records = [
        _rec(1, "DVSC", mnemonic="DVD_CASH", CP_STOCK_OPT="S"),   # DVSC+TEND
        _rec(2, "DVCA", mnemonic="DVD_CASH", CP_STOCK_OPT="X"),   # DVCA+TEND
    ]
    evaluated = analyses.evaluate(RULES, records)
    realized = analyses.realized_for_overlaps(evaluated, [("DVSC", "TEND"), ("DVCA", "DVSC")])
    by_pair = {tuple(r["pair"]): r["realized"] for r in realized}
    assert by_pair[("DVSC", "TEND")] == 1
    assert by_pair[("DVCA", "DVSC")] == 0   # never both, they contradict


def test_counts_only_strips_examples():
    records = [_rec(3, "TEND", mnemonic="OTHER")]
    s = analyses.summarize("eav", analyses.evaluate(RULES, records), RULES)
    full = s.to_dict()
    counts = s.to_dict(counts_only=True)
    assert full["conformance"]["examples"]          # present
    assert "examples" not in counts["conformance"]  # stripped


def test_integrity_diffs_and_missing():
    eav = {
        1: CARecord(1, "DVCA", {"mnemonic": "DVD_CASH", "CP_STOCK_OPT": "S"}),
        2: CARecord(2, "TEND", {"mnemonic": "DVD_CASH"}),          # only in EAV
    }
    mv = {
        1: CARecord(1, "DVCA", {"mnemonic": "DVD_CASH", "CP_STOCK_OPT": "D"}),  # differs
        3: CARecord(3, "TEND", {"mnemonic": "DVD_CASH"}),          # only in MV
    }
    report = analyses.integrity(eav, mv, {"mnemonic", "CP_STOCK_OPT"})
    assert report["mismatches"]["count"] == 1
    assert report["mismatches"]["examples"][0]["ca_id"] == 1
    assert report["only_in_eav"]["count"] == 1
    assert report["only_in_mv"]["count"] == 1


def test_integrity_type_tolerant():
    # "07" (MV string) vs 7 (EAV int) must NOT be flagged as a mismatch.
    eav = {1: CARecord(1, "X", {"UD006A": 7})}
    mv = {1: CARecord(1, "X", {"UD006A": "07"})}
    report = analyses.integrity(eav, mv, {"UD006A"})
    assert report["mismatches"]["count"] == 0
