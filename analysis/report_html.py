"""Self-contained HTML audit report for business analysts.

No external assets — inline CSS, opens in any browser, safe to email. Contains
real ca_ids (capped example lists); the full lists live in the CSV bundle.
"""
import html
from typing import Dict, List, Optional

from .analyses import AuditSummary


def _esc(value) -> str:
    return html.escape(str(value))


def _table(headers: List[str], rows: List[List]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="muted">none</td></tr>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _summary_section(summary: AuditSummary) -> str:
    ambiguous_total = sum(g["count"] for g in summary.ambiguous)
    cards = [
        ("Total records", summary.total, ""),
        ("Matched one code", summary.matched_one, "ok"),
        ("Ambiguous (matched >1)", ambiguous_total, "warn" if ambiguous_total else ""),
        ("Coverage gaps (matched 0)", summary.unmatched["count"], "warn" if summary.unmatched["count"] else ""),
        ("Conformance issues", summary.conformance["count"], "bad" if summary.conformance["count"] else ""),
        ("Assigned unknown code", summary.assigned_unknown["count"], "bad" if summary.assigned_unknown["count"] else ""),
    ]
    tiles = "".join(
        f'<div class="card {cls}"><div class="num">{_esc(v)}</div><div class="lbl">{_esc(lbl)}</div></div>'
        for lbl, v, cls in cards
    )
    return f'<div class="cards">{tiles}</div>'


def _ambiguity_section(summary: AuditSummary) -> str:
    rows = [
        [" + ".join(g["codes"]), g["count"],
         ", ".join(f"{k}:{v}" for k, v in g["assigned"].items()),
         ", ".join(str(x) for x in g["examples"][:10])]
        for g in summary.ambiguous
    ]
    return _table(["Matched codes", "Records", "Assigned to", "Example ca_ids"], rows)


def _resolution_section(summary: AuditSummary) -> str:
    rows = [
        [" vs ".join(r["pair"]),
         ", ".join(f"{k}:{v}" for k, v in r["winners"].items()),
         "⚠ INCONSISTENT" if r["inconsistent"] else "consistent"]
        for r in summary.resolution
    ]
    return _table(["Code pair", "Winners (assigned)", "Verdict"], rows)


def _examples_table(bucket: Dict, headers: List[str], keys: List[str]) -> str:
    rows = [[ex.get(k) for k in keys] for ex in bucket.get("examples", [])]
    return _table(headers, rows)


def _realized_section(realized_by_source: Dict[str, List[Dict]]) -> str:
    blocks = []
    for source, realized in realized_by_source.items():
        hit = [r for r in realized if r["realized"] > 0]
        rows = [[" ↔ ".join(r["pair"]), r["realized"]] for r in hit]
        blocks.append(f"<h4>source: {_esc(source)}</h4>" + _table(["Flagged overlap", "Real collisions"], rows))
    return "".join(blocks)


def _conformance_causes_section(report: Optional[Dict]) -> str:
    if not report or not report.get("causes"):
        return '<p class="muted">No conformance failures.</p>'
    rows = []
    for c in report["causes"]:
        condition = " AND ".join(c["conditions"])
        samples = ", ".join(f'{s["value"]}×{s["count"]}' for s in c["sample_actuals"])
        rows.append([c["assigned"], condition, c["count"], samples])
    return _table(["Assigned", "Violated condition", "Records", "Sample actual values"], rows)


def _integrity_section(report: Optional[Dict]) -> str:
    if not report:
        return '<p class="muted">Run with <code>--source both</code> to compare the MV against the attribute tables.</p>'
    summary_rows = [
        ["Field mismatches", report["mismatches"]["count"]],
        ["Only in EAV (missing from MV)", report["only_in_eav"]["count"]],
        ["Only in MV (missing from source)", report["only_in_mv"]["count"]],
    ]
    out = _table(["Check", "Count"], summary_rows)
    ex = report["mismatches"]["examples"]
    if ex:
        rows = []
        for m in ex[:50]:
            for d in m["diffs"]:
                rows.append([m["ca_id"], d["column"], d["eav"], d["mv"]])
        out += "<h4>Example mismatches</h4>" + _table(["ca_id", "column", "EAV value", "MV value"], rows)
    return out


_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem auto; max-width: 1100px; padding: 0 1rem; line-height: 1.5; }
h1 { margin-bottom: 0.2rem; } h2 { border-bottom: 2px solid #8884; padding-bottom: .3rem; margin-top: 2.2rem; }
.meta { color: #888; font-size: .9rem; margin-bottom: 1rem; }
.desc { color: #666; font-size: .92rem; margin: .2rem 0 .8rem; }
.cards { display: flex; flex-wrap: wrap; gap: .8rem; margin: 1rem 0; }
.card { flex: 1 1 150px; border: 1px solid #8883; border-radius: 8px; padding: .8rem 1rem; }
.card .num { font-size: 1.8rem; font-weight: 700; } .card .lbl { color: #888; font-size: .82rem; }
.card.ok .num { color: #1a7f37; } .card.warn .num { color: #b7791f; } .card.bad .num { color: #cf222e; }
table { border-collapse: collapse; width: 100%; margin: .4rem 0 1rem; font-size: .9rem; }
th, td { border: 1px solid #8883; padding: .35rem .6rem; text-align: left; vertical-align: top; }
th { background: #8881; } .muted { color: #999; } code { background: #8882; padding: 0 .3rem; border-radius: 3px; }
"""


def render_html(meta: Dict, summaries: List[AuditSummary],
                realized_by_source: Dict[str, List[Dict]],
                integrity_report: Optional[Dict],
                conformance_causes: Optional[Dict[str, Dict]] = None) -> str:
    conformance_causes = conformance_causes or {}
    parts = [
        f"<h1>Corporate-action rule audit — {_esc(meta.get('provider', ''))}</h1>",
        f'<div class="meta">Generated {_esc(meta.get("generated_at", ""))} · '
        f'rules: <code>{_esc(meta.get("rules_path", ""))}</code> · '
        f'{_esc(meta.get("rule_count", ""))} rules · {_esc(meta.get("overlap_count", ""))} flagged overlaps · '
        f'sources: {_esc(", ".join(meta.get("sources", [])))}</div>',
    ]

    for summary in summaries:
        parts.append(f"<h2>Summary — source: {_esc(summary.source)}</h2>")
        parts.append(_summary_section(summary))

        parts.append("<h2>Realized ambiguity</h2>")
        parts.append('<p class="desc">CAs matching more than one Swift code — the overlaps that actually happen in the data, and how enrichment resolved them.</p>')
        parts.append(_ambiguity_section(summary))

        parts.append("<h2>Resolution audit</h2>")
        parts.append('<p class="desc">For each colliding pair, which code enrichment picked. <b>INCONSISTENT</b> means the same pair was resolved different ways — nondeterministic and worth investigating first.</p>')
        parts.append(_resolution_section(summary))

        parts.append("<h2>Coverage gaps (sample)</h2>")
        parts.append('<p class="desc">CAs matching no Swift code. Full list in the accompanying CSV.</p>')
        parts.append(_examples_table(summary.unmatched, ["ca_id", "assigned code"], ["ca_id", "assigned"]))

        parts.append("<h2>Conformance failures by cause</h2>")
        parts.append('<p class="desc">CAs whose assigned code they do not actually match, grouped by the exact rule condition they violate — each record counted once, so this turns the raw count into a short list of root causes. Full per-record reasons in the CSV.</p>')
        parts.append(_conformance_causes_section(conformance_causes.get(summary.source)))

        parts.append("<h2>Conformance issues (sample)</h2>")
        parts.append('<p class="desc">A sample of the individual records behind the causes above.</p>')
        parts.append(_examples_table(summary.conformance, ["ca_id", "assigned code", "actually matches"], ["ca_id", "assigned", "matches"]))

    parts.append("<h2>Flagged overlaps that actually collided</h2>")
    parts.append(_realized_section(realized_by_source))

    parts.append("<h2>MV vs EAV integrity</h2>")
    parts.append(_integrity_section(integrity_report))

    body = "\n".join(parts)
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Audit — {_esc(meta.get('provider',''))}</title><style>{_CSS}</style></head><body>{body}</body></html>"
