"""Render audit findings to the terminal and export them as JSON.

Exports contain real corporate-action identifiers, so they are written under
the gitignored `exports/` directory and can be reduced to counts-only.
"""
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional

from rich import box
from rich.console import Console
from rich.table import Table

from . import analyses as _an
from .analyses import AuditSummary


def render_summary(console: Console, summary: AuditSummary) -> None:
    console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
    console.print(f"[bold]Audit — source: {summary.source.upper()}[/bold]")
    console.print(f"[bold cyan]{'='*60}[/bold cyan]")

    table = Table(box=box.SIMPLE)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="yellow")
    table.add_row("Total records", str(summary.total))
    table.add_row("Matched exactly one code", str(summary.matched_one))
    table.add_row("Matched multiple (ambiguous)", str(sum(g["count"] for g in summary.ambiguous)))
    table.add_row("Matched none (coverage gap)", str(summary.unmatched["count"]))
    table.add_row("Conformance issues", str(summary.conformance["count"]))
    table.add_row("Assigned an unknown code", str(summary.assigned_unknown["count"]))
    console.print(table)

    if summary.ambiguous:
        console.print("\n[bold yellow]Realized ambiguity (top combinations):[/bold yellow]")
        t = Table(box=box.SIMPLE)
        t.add_column("Matched codes", style="cyan")
        t.add_column("Records", justify="right", style="yellow")
        t.add_column("Assigned to", style="green")
        for g in summary.ambiguous[:15]:
            assigned = ", ".join(f"{k}:{v}" for k, v in g["assigned"].items())
            t.add_row(" + ".join(g["codes"]), str(g["count"]), assigned)
        console.print(t)

    inconsistent = [r for r in summary.resolution if r["inconsistent"]]
    if inconsistent:
        console.print("\n[bold red]⚠ Inconsistent resolution (same pair resolved different ways):[/bold red]")
        for r in inconsistent:
            winners = ", ".join(f"{k}:{v}" for k, v in r["winners"].items())
            console.print(f"  {r['pair'][0]} vs {r['pair'][1]} → {winners}")

    if summary.conformance["count"]:
        console.print(f"\n[bold red]Conformance issues: {summary.conformance['count']}[/bold red] "
                      "[dim](stale rules, manual override, or engine≠validator semantics)[/dim]")


def render_realized(console: Console, realized: List[Dict]) -> None:
    hit = [r for r in realized if r["realized"] > 0]
    if not hit:
        console.print("\n[green]No validator-flagged overlap actually collided in the data.[/green]")
        return
    console.print("\n[bold yellow]Flagged overlaps that actually collided:[/bold yellow]")
    t = Table(box=box.SIMPLE)
    t.add_column("Overlap", style="cyan")
    t.add_column("Real collisions", justify="right", style="red")
    for r in hit:
        t.add_row(f"{r['pair'][0]} ↔ {r['pair'][1]}", str(r["realized"]))
    console.print(t)


def render_conformance_causes(console: Console, report: Dict, *, top: int = 20) -> None:
    causes = report.get("causes", [])
    if not causes:
        return
    console.print(f"\n[bold red]Conformance failures by cause[/bold red] "
                  f"[dim]({report.get('total', 0)} records)[/dim]")
    t = Table(box=box.SIMPLE)
    t.add_column("Assigned", style="cyan")
    t.add_column("Violated condition", style="yellow")
    t.add_column("Records", justify="right", style="red")
    t.add_column("Sample actuals", style="dim")
    for c in causes[:top]:
        condition = " AND ".join(c["conditions"])
        samples = ", ".join(f'{s["value"]}×{s["count"]}' for s in c["sample_actuals"])
        t.add_row(c["assigned"], condition, str(c["count"]), samples)
    console.print(t)


def render_integrity(console: Console, report: Dict) -> None:
    console.print("\n[bold yellow]MV vs EAV integrity:[/bold yellow]")
    t = Table(box=box.SIMPLE)
    t.add_column("Check", style="cyan")
    t.add_column("Count", justify="right", style="yellow")
    t.add_row("Field mismatches", str(report["mismatches"]["count"]))
    t.add_row("Only in EAV (missing from MV)", str(report["only_in_eav"]["count"]))
    t.add_row("Only in MV (missing from source)", str(report["only_in_mv"]["count"]))
    console.print(t)


def build_payload(summaries: List[AuditSummary], realized_by_source: Dict[str, List[Dict]],
                  integrity_report: Optional[Dict], *, counts_only: bool = False,
                  conformance_causes: Optional[Dict[str, Dict]] = None) -> Dict:
    payload = {
        "summaries": [s.to_dict(counts_only=counts_only) for s in summaries],
        "realized_overlaps": realized_by_source,
        "conformance_causes": conformance_causes or {},
        "integrity": integrity_report,
    }
    return payload


def export_json(path, payload: Dict) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    return out


def _write_csv(path: Path, headers: List[str], rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def write_csv_bundle(directory, prefix: str, evaluated: List, rules: Dict,
                     integrity_rows=None) -> List[Path]:
    """Full (uncapped) per-record CSVs for a source, for BAs to slice in Excel.

    `evaluated` is the full EvaluatedRecord list; `integrity_rows` (optional) is
    the full mismatch iterator from analyses.iter_integrity_mismatches.
    """
    directory = Path(directory)
    written = []

    written.append(_write_csv(
        directory / f"{prefix}_coverage_gaps.csv",
        ["ca_id", "assigned_code"],
        ([ev.ca_id, ev.assigned_code] for ev in _an.iter_gaps(evaluated)),
    ))
    written.append(_write_csv(
        directory / f"{prefix}_ambiguous.csv",
        ["ca_id", "matched_codes", "assigned_code"],
        ([ev.ca_id, " + ".join(ev.matched_codes), ev.assigned_code] for ev in _an.iter_ambiguous(evaluated)),
    ))
    written.append(_write_csv(
        directory / f"{prefix}_conformance.csv",
        ["ca_id", "assigned_code", "actually_matches"],
        ([ev.ca_id, ev.assigned_code, " + ".join(ev.matched_codes)] for ev in _an.iter_conformance(evaluated, rules)),
    ))
    if integrity_rows is not None:
        written.append(_write_csv(
            directory / f"{prefix}_integrity_mismatches.csv",
            ["ca_id", "column", "eav_value", "mv_value"],
            ([m["ca_id"], m["column"], m["eav"], m["mv"]] for m in integrity_rows),
        ))
    return written


def write_conformance_reasons_csv(directory, prefix: str, records, rules: Dict):
    """Full per-record conformance reasons (one row per violated condition)."""
    path = Path(directory) / f"{prefix}_conformance_reasons.csv"
    rows = (
        [d["ca_id"], d["assigned_code"], d["column"], d["operator"], d["expected"], d["actual"]]
        for d in _an.iter_conformance_reasons(records, rules)
    )
    return _write_csv(path, ["ca_id", "assigned_code", "column", "operator", "expected", "actual"], rows)
