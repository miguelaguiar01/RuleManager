"""Structural security guarantees for the data-audit engine.

These tests make the ground rules enforceable rather than aspirational:
  1. The analysis code contains no data-modifying SQL (read-only, by proof).
  2. No connection strings or embedded passwords in tracked Python source.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ANALYSIS = REPO / "analysis"


def _py_sources():
    files = list(ANALYSIS.rglob("*.py"))
    files.append(REPO / "rule_semantics.py")
    return files


# UPPERCASE SQL keywords (our convention for any SQL we'd write).
_WRITE_SQL_UPPER = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|COPY|GRANT|REVOKE|CREATE)\b"
)
# Lowercase SQL only when it carries tell-tale clause context (avoids matching
# English prose like "on insert" or "created").
_WRITE_SQL_CONTEXT = re.compile(
    r"\b(insert\s+into|delete\s+from|update\s+\w+\s+set|drop\s+table"
    r"|alter\s+table|truncate\s+table|create\s+(table|view|index)|grant\s+|revoke\s+)",
    re.IGNORECASE,
)


def test_no_write_sql_in_analysis_sources():
    offenders = []
    for path in _py_sources():
        text = path.read_text()
        for pattern in (_WRITE_SQL_UPPER, _WRITE_SQL_CONTEXT):
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.relative_to(REPO)}:{line}: {m.group(0)!r}")
    assert not offenders, "write-capable SQL found:\n" + "\n".join(offenders)


def test_no_connection_strings_or_passwords_in_source():
    offenders = []
    for path in _py_sources():
        text = path.read_text()
        if "postgresql://" in text or re.search(r"(?i)password\s*=\s*['\"]", text):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, "possible secret/DSN in source: " + ", ".join(offenders)


def test_example_config_is_placeholders_only():
    example = (REPO / "config.example.toml").read_text()
    assert "REPLACE_ME" in example
    # Any DSN shown in the example must be a placeholder, not a live host.
    placeholders = ("REPLACE_ME", "HOST", "DBNAME", "USER")
    for line in example.splitlines():
        if "postgresql://" in line:
            assert any(p in line for p in placeholders), f"non-placeholder DSN in example: {line!r}"
