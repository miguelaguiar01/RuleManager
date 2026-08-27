"""Read-only Postgres adapter. The only module that touches a database.

No special database role is required. Reads are kept safe three ways:
  1. The session is opened read-only (any user can do this; the server then
     rejects writes in the session — no elevated privileges needed).
  2. Every statement is validated at runtime before execution: only SELECT /
     WITH / SET / SHOW are allowed; anything that could modify data is refused.
  3. The module only ever composes SELECTs — enforced statically by
     tests/test_analysis_security.py.

Identifiers come from the validated ProviderSchema and still go through
psycopg.sql.Identifier; values go through parameters.
"""
from typing import Dict, Iterable, Iterator, List

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .schema import ProviderSchema, validate_identifier

# Statement kinds that cannot modify data.
_READ_ONLY_PREFIXES = ("select", "with", "set", "show")

# libpq connection keywords accepted directly from [connection], so a local or
# Docker Postgres can be configured with plain host/port/dbname/user.
_LIBPQ_KEYS = ("dsn", "service", "host", "port", "dbname", "user", "password",
               "sslmode", "connect_timeout")


class WriteAttemptError(RuntimeError):
    """Raised if a non-read-only statement is ever about to run."""


def _assert_read_only(query, conn) -> None:
    text = query.as_string(conn) if hasattr(query, "as_string") else str(query)
    tokens = text.lstrip().lstrip("(").lstrip().split(None, 1)
    first = tokens[0].lower() if tokens else ""
    if first not in _READ_ONLY_PREFIXES:
        raise WriteAttemptError(f"Refusing non-read-only statement: {text.strip()[:80]!r}")


def _run(conn, query, params=None):
    """Validate, then execute, returning a dict-row cursor. Read-only only."""
    _assert_read_only(query, conn)
    cur = conn.cursor(row_factory=dict_row)
    cur.execute(query, params)
    return cur


def _qualified(schema: ProviderSchema, table: str):
    """Schema-qualified table reference: "db_schema"."table"."""
    return sql.Identifier(schema.db_schema, table)


def _connection_params(conn_cfg: Dict):
    """Split a [connection] block into (dsn, libpq kwargs), ignoring our own
    non-libpq keys (e.g. statement_timeout_ms)."""
    dsn = conn_cfg.get("dsn")
    kwargs = {k: conn_cfg[k] for k in _LIBPQ_KEYS if k != "dsn" and k in conn_cfg}
    return dsn, kwargs


def connect(config: Dict):
    """Open a read-only connection from a [connection] config block.

    Accepts a `dsn`, a pg `service`, or plain libpq keywords (host, port,
    dbname, user, password, sslmode) — whichever the config provides.
    """
    conn_cfg = config.get("connection", {})
    dsn, kwargs = _connection_params(conn_cfg)
    # Fail fast on an unreachable host instead of hanging (overridable in config).
    kwargs.setdefault("connect_timeout", int(conn_cfg.get("connect_timeout", 10)))

    conn = psycopg.connect(dsn, **kwargs) if dsn else psycopg.connect(**kwargs)
    conn.read_only = True
    conn.autocommit = True

    # Generous default so large legitimate reads aren't cancelled; still a
    # backstop against a runaway query. Tune with connection.statement_timeout_ms.
    timeout = int(conn_cfg.get("statement_timeout_ms", 300000))
    for statement in _session_statements(timeout):
        _run(conn, statement).close()
    return conn


def _session_statements(timeout_ms: int):
    """Session GUCs. SET does not accept bind parameters, so the (integer,
    config-controlled) timeout is inlined as a SQL literal, not a %s param."""
    ms = sql.Literal(int(timeout_ms))
    return [
        sql.SQL("SET default_transaction_read_only = on"),
        sql.SQL("SET statement_timeout = {}").format(ms),
        sql.SQL("SET idle_in_transaction_session_timeout = {}").format(ms),
    ]


def _table_columns(conn, schema: ProviderSchema, table: str) -> List[str]:
    """The real column names of a table, from information_schema."""
    query = sql.SQL(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s"
    )
    cur = _run(conn, query, (schema.db_schema, table))
    try:
        return [row["column_name"] for row in cur]
    finally:
        cur.close()


def _base_query(schema: ProviderSchema, present_columns: Iterable[str], ruleset_columns: Iterable[str]):
    """Base CA query. Selects ca_id + swift_code plus every ruleset column that
    actually exists on the base table (matched case-insensitively, aliased back
    to the rule column name). Rule columns not on the base table come from the
    attribute tables instead."""
    present_lower = {c.lower(): c for c in present_columns}
    cols = [
        sql.SQL("{} AS ca_id").format(sql.Identifier(schema.ca_id)),
        sql.SQL("{} AS swift_code").format(sql.Identifier(schema.swift_code)),
    ]
    for rule_col in sorted(set(ruleset_columns)):
        real = present_lower.get(rule_col.lower())
        if real and real not in (schema.ca_id, schema.swift_code):
            cols.append(sql.SQL("{} AS {}").format(sql.Identifier(real), sql.Identifier(rule_col)))
    return sql.SQL("SELECT {cols} FROM {tbl}").format(
        cols=sql.SQL(", ").join(cols),
        tbl=_qualified(schema, schema.ca_table),
    )


def fetch_base(conn, schema: ProviderSchema, columns: Iterable[str]) -> Iterator[Dict]:
    """Yield {ca_id, swift_code, <base rule columns...>} for every CA."""
    present = _table_columns(conn, schema, schema.ca_table)
    cur = _run(conn, _base_query(schema, present, columns))
    try:
        yield from cur
    finally:
        cur.close()


def _attributes_query(schema: ProviderSchema, wanted: List[str]):
    """Build the UNION-ALL over the typed attribute tables. `value` is cast to
    text in every branch — the columns have different types (date/int/numeric/
    varchar) and UNION requires one common type; text also matches how the
    tolerant comparator treats values."""
    parts, params = [], []
    for table_name in schema.matchable_attribute_tables().values():
        parts.append(
            sql.SQL(
                "SELECT {ca} AS ca_id, {attr} AS attribute, CAST({val} AS text) AS value "
                "FROM {tbl} WHERE {attr} = ANY(%s)"
            ).format(
                ca=sql.Identifier(schema.ca_id),
                attr=sql.Identifier(schema.attribute_name),
                val=sql.Identifier(schema.attribute_value),
                tbl=_qualified(schema, table_name),
            )
        )
        params.append(wanted)
    return sql.SQL(" UNION ALL ").join(parts), params


def fetch_attributes(conn, schema: ProviderSchema, columns: Iterable[str]) -> Iterator[Dict]:
    """Yield {ca_id, attribute, value} across the matchable typed tables,
    restricted to the attributes the ruleset actually references."""
    wanted: List[str] = list(columns)
    if not wanted:
        return

    query, params = _attributes_query(schema, wanted)
    cur = _run(conn, query, params)
    try:
        yield from cur
    finally:
        cur.close()


def _mv_query(schema: ProviderSchema, columns: Iterable[str]):
    """MV query: ca_id + swift_code plus each ruleset column, lowercased (the MV
    stores lowercase rule-column names); caller remaps them."""
    reserved = {schema.ca_id.lower(), schema.swift_code.lower()}
    select_cols = [
        sql.SQL("{} AS ca_id").format(sql.Identifier(schema.ca_id)),
        sql.SQL("{} AS swift_code").format(sql.Identifier(schema.swift_code)),
    ]
    for col in sorted(set(columns)):
        low = validate_identifier(col.lower(), "mv_column")
        if low not in reserved:
            select_cols.append(sql.Identifier(low))
    return sql.SQL("SELECT {cols} FROM {tbl}").format(
        cols=sql.SQL(", ").join(select_cols),
        tbl=_qualified(schema, schema.materialized_view),
    )


def fetch_mv(conn, schema: ProviderSchema, columns: Iterable[str]) -> Iterator[Dict]:
    """Yield one condensed row per CA from the materialized view."""
    cur = _run(conn, _mv_query(schema, columns))
    try:
        yield from cur
    finally:
        cur.close()
