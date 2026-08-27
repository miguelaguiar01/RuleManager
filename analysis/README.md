# Data-audit engine

Scores real corporate-action records (from Postgres) against a RuleManager
ruleset and reports five things:

| Analysis | Question it answers |
|---|---|
| **Realized ambiguity** | Which flagged rule overlaps actually collided in the data, and how was each resolved? |
| **Coverage gaps** | Which CAs match *no* Swift code (silently unhandled)? |
| **Conformance** | Which CAs don't satisfy the rule for the code they were assigned? (stale rules / manual overrides / engine-vs-validator semantic drift) |
| **Resolution audit** | For multi-match CAs, which code won — and is that tie-break *consistent*? |
| **MV-vs-EAV integrity** | Does the materialized view agree, field-by-field, with the raw attribute tables? |

## Security posture (by construction)

- **No company data in the repo.** Every table/column name comes from a config
  file that lives only on your laptop. The repo has `config.example.toml` with
  placeholders. `.gitignore` blocks `*.local.toml`, `.env`, `.pgpass`, `exports/`.
- **Read-only, four ways.** Use a `SELECT`-only role (the real guarantee); the
  session is opened read-only so the server rejects writes; statement/idle
  timeouts bound every query; and `tests/test_analysis_security.py` fails the
  build if any write-SQL or DSN/password ever appears in `analysis/`.
- **No injection.** Config identifiers are validated against `^[a-z_][a-z0-9_]*$`
  and passed through `psycopg.sql.Identifier`; values go through parameters.
- **Exports contain real ids/values** → they land in the gitignored `exports/`.
  Use `--counts-only` to drop example ids entirely.

## One-time setup on the laptop

1. **Create a read-only role** (the actual boundary):
   ```sql
   CREATE ROLE ca_auditor LOGIN PASSWORD '...';
   GRANT CONNECT ON DATABASE yourdb TO ca_auditor;
   GRANT USAGE ON SCHEMA public TO ca_auditor;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO ca_auditor;
   -- and on the materialized view
   ```
2. **Put the password in `~/.pgpass`** (`chmod 600`) or a `pg_service` entry —
   not in the config file.
3. **Copy the config out of the repo** and fill in real names:
   ```bash
   cp config.example.toml ~/.rulemanager/audit.local.toml
   # edit: connection.service (or dsn), and the naming/columns templates
   ```

## Run

```bash
uv run python -m analysis \
  --config ~/.rulemanager/audit.local.toml \
  --provider bb \
  --rules enrichment_calculation_rules_bb.json \
  --source both \
  --export exports/audit_bb.json
```

`--source eav` reconstructs records from the attribute tables; `--source mv`
reads the materialized view; `--source both` runs each and adds the integrity
diff. Repeat with `--provider wm` and the WM ruleset.

## Notes / current limits

- Missing attributes follow **SQL-NULL semantics**: any comparison on an absent
  field is non-matching (same as the engine's own `WHERE`).
- Value comparison is **type-tolerant** (`"07"` == `7`) — WM values arrive as
  strings, BB already typed; this keeps them comparable and is shared with the
  validator so record-scoring matches how rules are reasoned about.
- **Dates** compare by equality/string only; range operators (`<`, `>`) on date
  columns evaluate False. Tell me if any rules order dates and I'll add it.
