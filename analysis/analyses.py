"""The five analyses, computed over evaluated records. All pure.

  1. Realized ambiguity  — records matching >=2 codes, grouped by combination.
  2. Coverage gaps       — records matching zero codes (unhandled).
  3. Conformance         — records whose assigned code they do NOT match
                           (drift / override / semantic divergence).
  4. Resolution audit    — among multi-match records, which code actually won,
                           and whether that tie-break is consistent.
  5. MV-vs-EAV integrity — field-level disagreement between the two sources.

A record is scored once (`evaluate`); every analysis derives from that, so the
expensive matching runs a single time per record.

Known limitation: date columns compare by equality/string only (the shared
numeric path can't order dates); range operators on dates evaluate False.
"""
import itertools
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import rule_semantics as sem

from .matcher import matching_codes
from .records import CARecord

EXAMPLES = 20


@dataclass
class EvaluatedRecord:
    ca_id: Any
    assigned_code: Optional[str]
    matched_codes: List[str]


@dataclass
class AuditSummary:
    source: str
    total: int
    matched_one: int
    unmatched: Dict            # {count, examples}
    ambiguous: List[Dict]      # [{codes, count, assigned, examples}]
    conformance: Dict          # {count, examples}
    assigned_unknown: Dict     # {count, examples} — assigned a code with no rule
    resolution: List[Dict]     # [{pair, winners, inconsistent}]

    def to_dict(self, counts_only: bool = False) -> Dict:
        data = asdict(self)
        if counts_only:
            _strip_examples(data)
        return data


def evaluate(rules: Dict[str, Dict], records: Iterable[CARecord]) -> List[EvaluatedRecord]:
    return [
        EvaluatedRecord(r.ca_id, r.assigned_code, matching_codes(r.fields, rules))
        for r in records
    ]


def summarize(source: str, evaluated: List[EvaluatedRecord], rules: Dict[str, Dict],
              *, examples: int = EXAMPLES) -> AuditSummary:
    matched_one = 0
    unmatched_count, unmatched = 0, []
    combos: Dict[Tuple, Dict] = defaultdict(lambda: {"count": 0, "assigned": Counter(), "examples": []})
    conformance_count, conformance = 0, []
    unknown_count, unknown = 0, []
    pair_winner: Dict[Tuple[str, str], Counter] = defaultdict(Counter)

    for ev in evaluated:
        n = len(ev.matched_codes)
        if n == 0:
            unmatched_count += 1
            if len(unmatched) < examples:
                unmatched.append({"ca_id": ev.ca_id, "assigned": ev.assigned_code})
        elif n == 1:
            matched_one += 1
        else:
            g = combos[tuple(ev.matched_codes)]
            g["count"] += 1
            g["assigned"][ev.assigned_code] += 1
            if len(g["examples"]) < examples:
                g["examples"].append(ev.ca_id)
            if ev.assigned_code in ev.matched_codes:
                for a, b in itertools.combinations(ev.matched_codes, 2):
                    pair_winner[(a, b)][ev.assigned_code] += 1

        # conformance is independent of match count
        if ev.assigned_code is not None:
            if ev.assigned_code not in rules:
                unknown_count += 1
                if len(unknown) < examples:
                    unknown.append({"ca_id": ev.ca_id, "assigned": ev.assigned_code})
            elif ev.assigned_code not in ev.matched_codes:
                conformance_count += 1
                if len(conformance) < examples:
                    conformance.append({"ca_id": ev.ca_id, "assigned": ev.assigned_code,
                                        "matches": ev.matched_codes})

    ambiguous = [
        {"codes": list(codes), "count": g["count"], "assigned": dict(g["assigned"]),
         "examples": g["examples"]}
        for codes, g in sorted(combos.items(), key=lambda kv: -kv[1]["count"])
    ]
    resolution = [
        {"pair": [a, b], "winners": dict(w), "inconsistent": len(w) > 1}
        for (a, b), w in sorted(pair_winner.items())
    ]

    return AuditSummary(
        source=source,
        total=len(evaluated),
        matched_one=matched_one,
        unmatched={"count": unmatched_count, "examples": unmatched},
        ambiguous=ambiguous,
        conformance={"count": conformance_count, "examples": conformance},
        assigned_unknown={"count": unknown_count, "examples": unknown},
        resolution=resolution,
    )


def realized_for_overlaps(evaluated: List[EvaluatedRecord],
                          overlaps: Iterable[Tuple[str, str]],
                          *, examples: int = EXAMPLES) -> List[Dict]:
    """For each validator-flagged overlap (A,B), how many real CAs matched both."""
    out = []
    for a, b in overlaps:
        count, ex = 0, []
        for ev in evaluated:
            if a in ev.matched_codes and b in ev.matched_codes:
                count += 1
                if len(ex) < examples:
                    ex.append(ev.ca_id)
        out.append({"pair": [a, b], "realized": count, "examples": ex})
    return sorted(out, key=lambda d: -d["realized"])


# --- full-list iterators (uncapped) — for CSV export / BA analysis ----------

def iter_gaps(evaluated: List[EvaluatedRecord]):
    """Every record that matches no code."""
    return (ev for ev in evaluated if not ev.matched_codes)


def iter_ambiguous(evaluated: List[EvaluatedRecord]):
    """Every record that matches two or more codes."""
    return (ev for ev in evaluated if len(ev.matched_codes) >= 2)


def iter_conformance(evaluated: List[EvaluatedRecord], rules: Dict[str, Dict]):
    """Every record whose assigned code it does not actually match."""
    return (
        ev for ev in evaluated
        if ev.assigned_code and ev.assigned_code in rules
        and ev.assigned_code not in ev.matched_codes
    )


def iter_integrity_mismatches(eav_records: Dict[Any, CARecord],
                              mv_records: Dict[Any, CARecord],
                              columns: Iterable[str]):
    """Yield every field-level EAV-vs-MV disagreement (uncapped)."""
    cols = sorted(set(columns))
    for cid, erec in eav_records.items():
        mrec = mv_records.get(cid)
        if mrec is None:
            continue
        for col in cols:
            ev = erec.fields.get(col, sem.MISSING)
            mv = mrec.fields.get(col, sem.MISSING)
            if not _integrity_equal(ev, mv):
                yield {"ca_id": cid, "column": col, "eav": _show(ev), "mv": _show(mv)}


def integrity(eav_records: Dict[Any, CARecord], mv_records: Dict[Any, CARecord],
              columns: Iterable[str], *, examples: int = 50) -> Dict:
    """Field-level agreement between the EAV reconstruction and the MV."""
    cols = set(columns)
    only_eav = [cid for cid in eav_records if cid not in mv_records]
    only_mv = [cid for cid in mv_records if cid not in eav_records]

    mismatches = []
    for cid, erec in eav_records.items():
        mrec = mv_records.get(cid)
        if mrec is None:
            continue
        diffs = []
        for col in sorted(cols):
            ev = erec.fields.get(col, sem.MISSING)
            mv = mrec.fields.get(col, sem.MISSING)
            if not _integrity_equal(ev, mv):
                diffs.append({"column": col, "eav": _show(ev), "mv": _show(mv)})
        if diffs:
            mismatches.append({"ca_id": cid, "diffs": diffs})

    return {
        "only_in_eav": {"count": len(only_eav), "examples": only_eav[:examples]},
        "only_in_mv": {"count": len(only_mv), "examples": only_mv[:examples]},
        "mismatches": {"count": len(mismatches), "examples": mismatches[:examples]},
    }


def _integrity_equal(a: Any, b: Any) -> bool:
    if a is sem.MISSING or b is sem.MISSING:
        return a is b  # both missing == equal; one missing == mismatch
    return sem.values_equal(a, b)


def _show(value: Any) -> Any:
    return None if value is sem.MISSING else value


def _strip_examples(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("examples", None)
        for v in node.values():
            _strip_examples(v)
    elif isinstance(node, list):
        for v in node:
            _strip_examples(v)
