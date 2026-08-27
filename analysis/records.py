"""Turn raw database rows into uniform CA records keyed by *rule* column names.

Two independent sources, same output shape:
  - EAV: a base row per CA (ca_id, mnemonic, swift_code) plus attribute rows
    (ca_id, attribute, value). The `attribute` is the exact rule column name.
  - MV : one condensed row per CA whose columns are the *lowercased* rule column
    names; we map them back to the rule column names so the matcher sees the
    same keys from either source.

Both are pure functions over row iterables — no database dependency.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional


@dataclass
class CARecord:
    ca_id: Any
    assigned_code: Optional[str]      # swift_code the engine assigned (post-enrichment)
    fields: Dict[str, Any] = field(default_factory=dict)  # matchable data, keyed by rule column


def build_records_from_eav(
    base_rows: Iterable[Dict],
    attribute_rows: Iterable[Dict],
    *,
    ca_id_key: str = "ca_id",
    mnemonic_key: str = "mnemonic",
    swift_code_key: str = "swift_code",
    attribute_key: str = "attribute",
    value_key: str = "value",
) -> Dict[Any, CARecord]:
    """Reconstruct records by pivoting attribute rows onto their base CA."""
    records: Dict[Any, CARecord] = {}

    for row in base_rows:
        cid = row[ca_id_key]
        fields = {}
        mnemonic = row.get(mnemonic_key)
        if mnemonic is not None:  # absent column or NULL -> leave MISSING
            fields[mnemonic_key] = mnemonic
        records[cid] = CARecord(ca_id=cid, assigned_code=row.get(swift_code_key), fields=fields)

    for row in attribute_rows:
        cid = row[ca_id_key]
        rec = records.get(cid)
        if rec is None:  # attribute for a CA with no base row — keep it, flag later
            rec = records[cid] = CARecord(ca_id=cid, assigned_code=None, fields={})
        rec.fields[row[attribute_key]] = row[value_key]

    return records


def build_records_from_mv(
    mv_rows: Iterable[Dict],
    columns: Iterable[str],
    *,
    ca_id_key: str = "ca_id",
    mnemonic_key: str = "mnemonic",
    swift_code_key: str = "swift_code",
) -> Dict[Any, CARecord]:
    """Load MV rows, remapping lowercase MV columns back to rule column names."""
    lower_to_rule = {c.lower(): c for c in columns}
    records: Dict[Any, CARecord] = {}

    for row in mv_rows:
        cid = row[ca_id_key]
        fields: Dict[str, Any] = {}
        if mnemonic_key in row:
            fields[mnemonic_key] = row[mnemonic_key]
        for key, value in row.items():
            if key in (ca_id_key, swift_code_key):
                continue
            rule_col = lower_to_rule.get(key)
            if rule_col is not None:
                fields[rule_col] = value
        records[cid] = CARecord(ca_id=cid, assigned_code=row.get(swift_code_key), fields=fields)

    return records
