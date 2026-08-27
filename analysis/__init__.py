"""Data-audit engine: score real corporate-action records against a RuleManager
ruleset to surface realized ambiguity, coverage gaps, conformance drift and
materialized-view integrity issues.

The pure core (semantics, matcher, records, analyses) has no database
dependency and is fully unit-tested with synthetic records. Only `db` talks to
Postgres, and only ever reads.
"""
