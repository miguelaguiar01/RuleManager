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
- **Read-only, no special role needed.** The session is opened read-only so the
  server rejects writes; every statement is validated at runtime and refused
  unless it's a plain read (SELECT/WITH/SET/SHOW); statement/idle timeouts bound
  every query; and `tests/test_analysis_security.py` fails the build if any
  write-SQL or DSN/password ever appears in `analysis/`.
- **No injection.** Config identifiers are validated against `^[a-z_][a-z0-9_]*$`
  and passed through `psycopg.sql.Identifier`; values go through parameters.
- **Exports contain real ids/values** → they land in the gitignored `exports/`.
  Use `--counts-only` to drop example ids entirely.

## One-time setup on the laptop

No special database role is required — connect with whatever user you already
have; the engine keeps the session read-only and refuses non-read statements.

1. **Copy the config out of the repo** and fill in real values:
   ```bash
   cp config.example.toml ~/.rulemanager/audit.local.toml
   ```
2. **Fill in `[connection]`.** For a Docker Postgres, use the plain fields
   (`host`, `port`, `dbname`, `user`, `password`/`~/.pgpass`, `sslmode`). If you
   only have a **JDBC** URL like
   `jdbc:postgresql://localhost:5432/db?user=me&password=pw&sslmode=disable`,
   drop the `jdbc:` prefix and copy each piece into the matching field.
3. **Fill in `[naming]`/`[columns]`** with your real name templates.

## Run

Both providers are declared once in the config (`[providers.bb]`,
`[providers.wm]`, each with its `rules` path), so day-to-day you only pick the
provider:

```bash
uv run audit.py --provider bb            # BB, both sources
uv run audit.py --provider wm --source mv
uv run audit.py                          # every provider in the config
uv run audit.py --provider bb --export exports/audit_bb.json
```

(`uv run audit.py` is a thin wrapper for `uv run python -m analysis` — either works.)

- `--config` defaults to `~/.rulemanager/audit.local.toml`; pass `--config` to
  point elsewhere.
- `--rules` is optional — it defaults to `[providers.<provider>].rules` and only
  needs to be passed to override.
- `--source eav` reconstructs records from the attribute tables; `--source mv`
  reads the materialized view; `--source both` runs each and adds the integrity
  diff.
- Omitting `--provider` runs every configured provider; with `--export`, the
  provider name is appended to each filename automatically.

## Notes / current limits

- Missing attributes follow **SQL-NULL semantics**: any comparison on an absent
  field is non-matching (same as the engine's own `WHERE`).
- Value comparison is **type-tolerant** (`"07"` == `7`) — WM values arrive as
  strings, BB already typed; this keeps them comparable and is shared with the
  validator so record-scoring matches how rules are reasoned about.
- **Dates** compare by equality/string only; range operators (`<`, `>`) on date
  columns evaluate False. Tell me if any rules order dates and I'll add it.
