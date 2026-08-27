"""CLI entry point for the data audit.

Everything a provider needs lives in one config file, so day-to-day you only
pick the provider:

    uv run audit.py --provider bb
    uv run audit.py --provider wm --source mv
    uv run audit.py                     # run every provider in [providers.*]

The ruleset path comes from [providers.<provider>].rules (override with
--rules). Table/column names come from the shared [naming]/[columns] templates
(override per provider under [providers.<provider>]).
"""
import argparse
from pathlib import Path
from typing import Dict, List

from rich.console import Console

import rule_manager

from . import analyses, records as rec, report
from .matcher import ruleset_columns
from .schema import (
    build_provider_schema,
    configured_providers,
    load_config,
    naming_for_provider,
    provider_rules_path,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="audit", description="Corporate-action rule/data audit")
    p.add_argument("--config", default="~/.rulemanager/audit.local.toml",
                   help="Path to the laptop-only TOML config (outside the repo)")
    p.add_argument("--provider", help="Provider to run (e.g. bb, wm). Omit to run every configured provider.")
    p.add_argument("--rules", help="Ruleset JSON (overrides [providers.<provider>].rules)")
    p.add_argument("--source", choices=["eav", "mv", "both"], default="both",
                   help="Records from the attribute tables (eav), the materialized view (mv), or both")
    p.add_argument("--export", help="Write findings as JSON here (use exports/ — gitignored). "
                                    "With multiple providers the provider is appended to the filename.")
    p.add_argument("--examples", type=int, default=analyses.EXAMPLES, help="Max example ca_ids kept per finding")
    p.add_argument("--counts-only", action="store_true", help="Drop example ca_ids from the export")
    return p.parse_args(argv)


def resolve_providers(provider, config: Dict) -> List[str]:
    if provider:
        return [provider]
    providers = configured_providers(config)
    if not providers:
        raise SystemExit("No --provider given and no [providers.*] configured in the config.")
    return providers


def resolve_rules_path(rules_arg, config: Dict, provider: str) -> str:
    path = rules_arg or provider_rules_path(config, provider)
    if not path:
        raise SystemExit(
            f"No ruleset for provider {provider!r}: pass --rules or set "
            f"[providers.{provider}].rules in the config."
        )
    return str(Path(path).expanduser())


def export_path(base: str, provider: str, multi: bool) -> Path:
    p = Path(base)
    return p.with_name(f"{p.stem}_{provider}{p.suffix}") if multi else p


def _audit(console: Console, source_name: str, records_map: Dict, rules: Dict, overlaps, examples: int):
    evaluated = analyses.evaluate(rules, records_map.values())
    summary = analyses.summarize(source_name, evaluated, rules, examples=examples)
    realized = analyses.realized_for_overlaps(evaluated, overlaps, examples=examples)
    report.render_summary(console, summary)
    report.render_realized(console, realized)
    return summary, realized


def _run_provider(console: Console, conn, config: Dict, provider: str, args, multi: bool):
    from . import db  # lazy: psycopg only needed when hitting the DB

    schema = build_provider_schema(provider, naming_for_provider(config, provider))
    rules_path = resolve_rules_path(args.rules, config, provider)

    manager = rule_manager.RuleManager(rules_path)
    rules = manager.rules
    columns = ruleset_columns(rules)
    overlaps = manager.validate_rules().overlaps
    console.print(f"\n[bold cyan]▶ Provider {provider}[/bold cyan] — "
                  f"{len(rules)} rules, {len(columns)} columns, {len(overlaps)} flagged overlaps "
                  f"[dim]({rules_path})[/dim]")

    summaries, realized_by_source = [], {}
    eav_records = mv_records = None
    integrity_report = None

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

    if args.export:
        path = export_path(args.export, provider, multi)
        payload = report.build_payload(summaries, realized_by_source, integrity_report,
                                       counts_only=args.counts_only)
        report.export_json(path, payload)
        console.print(f"[green]✓ Wrote {path}[/green]")


def main(argv=None):
    args = parse_args(argv)
    console = Console()

    config = load_config(str(Path(args.config).expanduser()))
    providers = resolve_providers(args.provider, config)
    multi = len(providers) > 1

    from . import db
    conn = db.connect(config)
    try:
        for provider in providers:
            _run_provider(console, conn, config, provider, args, multi)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
