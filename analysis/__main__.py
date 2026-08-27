"""CLI entry point:

    uv run python -m analysis --config ~/.rulemanager/audit.local.toml \\
        --provider bb --rules enrichment_calculation_rules_bb.json \\
        --source both --export exports/audit_bb.json

Reads the DB (read-only), scores every CA against the ruleset, and reports the
five analyses. The config file must live outside the repository.
"""
import argparse
from typing import Dict

from rich.console import Console

import rule_manager

from . import analyses, records as rec, report
from .matcher import ruleset_columns
from .schema import build_provider_schema, load_config, naming_from_config


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="python -m analysis", description="Corporate-action rule/data audit")
    p.add_argument("--config", required=True, help="Path to the laptop-only TOML config (outside the repo)")
    p.add_argument("--provider", required=True, help="Provider key substituted into name templates (e.g. bb, wm)")
    p.add_argument("--rules", required=True, help="The ruleset JSON you pass to RuleManager for this provider")
    p.add_argument("--source", choices=["eav", "mv", "both"], default="both",
                   help="Reconstruct records from the attribute tables (eav), the materialized view (mv), or both")
    p.add_argument("--export", help="Write findings as JSON to this path (use exports/ — it is gitignored)")
    p.add_argument("--examples", type=int, default=analyses.EXAMPLES, help="Max example ca_ids kept per finding")
    p.add_argument("--counts-only", action="store_true", help="Drop example ca_ids from the export (counts only)")
    return p.parse_args(argv)


def _audit(console: Console, source_name: str, records_map: Dict, rules: Dict,
           overlaps, examples: int):
    evaluated = analyses.evaluate(rules, records_map.values())
    summary = analyses.summarize(source_name, evaluated, rules, examples=examples)
    realized = analyses.realized_for_overlaps(evaluated, overlaps, examples=examples)
    report.render_summary(console, summary)
    report.render_realized(console, realized)
    return summary, realized


def main(argv=None):
    args = parse_args(argv)
    console = Console()

    config = load_config(args.config)
    naming = naming_from_config(config)
    schema = build_provider_schema(args.provider, naming)

    manager = rule_manager.RuleManager(args.rules)
    rules = manager.rules
    columns = ruleset_columns(rules)
    overlaps = manager.validate_rules().overlaps
    console.print(f"[dim]{len(rules)} rules, {len(columns)} referenced columns, "
                  f"{len(overlaps)} flagged overlaps.[/dim]")

    from . import db  # lazy import: psycopg only needed when actually hitting the DB
    conn = db.connect(config)
    summaries, realized_by_source = [], {}
    eav_records = mv_records = None
    integrity_report = None
    try:
        if args.source in ("eav", "both"):
            base = list(db.fetch_base(conn, schema))
            attrs = list(db.fetch_attributes(conn, schema, columns))
            eav_records = rec.build_records_from_eav(base, attrs)
            summary, realized = _audit(console, "eav", eav_records, rules, overlaps, args.examples)
            summaries.append(summary)
            realized_by_source["eav"] = realized

        if args.source in ("mv", "both"):
            mv_rows = list(db.fetch_mv(conn, schema, columns))
            mv_records = rec.build_records_from_mv(mv_rows, columns)
            summary, realized = _audit(console, "mv", mv_records, rules, overlaps, args.examples)
            summaries.append(summary)
            realized_by_source["mv"] = realized

        if args.source == "both" and eav_records is not None and mv_records is not None:
            integrity_report = analyses.integrity(eav_records, mv_records, columns)
            report.render_integrity(console, integrity_report)
    finally:
        conn.close()

    if args.export:
        payload = report.build_payload(summaries, realized_by_source, integrity_report,
                                       counts_only=args.counts_only)
        path = report.export_json(args.export, payload)
        console.print(f"\n[green]✓ Wrote findings to {path}[/green]")


if __name__ == "__main__":
    main()
